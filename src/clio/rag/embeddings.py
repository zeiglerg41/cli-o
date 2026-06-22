"""Embedding generation for conversation messages."""
import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from pathlib import Path

# Silence Hugging Face / transformers noise before they are imported. Without
# this, loading the embedding model dumps "Loading weights" progress bars and an
# "unauthenticated requests to the HF Hub" warning straight into the chat output.
# Must be set before transformers/sentence_transformers are first imported.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# The "unauthenticated requests to the HF Hub" warning is printed (from compiled
# code) whenever the loader makes a network request to check the cached model.
# If the model is already cached, force offline mode so no request is made at
# all -- this kills the warning at the source, which is race-proof (no fd/thread
# timing tricks needed). Only do this when cached, so a fresh machine can still
# download the model on first run.
def _embedding_model_is_cached() -> bool:
    from pathlib import Path
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    try:
        return hub.exists() and any(
            hub.glob("models--sentence-transformers--all-MiniLM-L6-v2")
        )
    except OSError:
        return False

if _embedding_model_is_cached():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logger = logging.getLogger(__name__)

# Global thread pool for model loading
_thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag_model")


class EmbeddingManager:
    """Manages embedding generation for conversation messages."""

    def __init__(self):
        """Initialize embedding manager with lazy model loading."""
        self._model = None
        self._model_name = "all-MiniLM-L6-v2"
        self._loading = False
        self._load_task = None

    def _load_model_sync(self):
        """Synchronous model loading (runs in thread pool)."""
        # Quiet the HF hub + transformers loggers/progress bars at the source.
        # (We can't redirect stdout/stderr here: this runs in a worker thread
        # while the main thread is printing the chat response, and redirection
        # is process-global -- it would swallow the real output.)
        for name in ("huggingface_hub", "transformers", "sentence_transformers"):
            logging.getLogger(name).setLevel(logging.ERROR)
        try:
            from huggingface_hub.utils import disable_progress_bars
            disable_progress_bars()
        except Exception:
            pass
        try:
            from transformers.utils import logging as hf_logging
            hf_logging.set_verbosity_error()
            hf_logging.disable_progress_bar()
        except Exception:
            pass

        logger.info(f"Loading embedding model: {self._model_name}")
        import sys

        def _muted_construct():
            """Build the model with OS-level stderr muted.

            transformers 5.x writes a "Loading weights" bar and an HF-token
            warning straight to OS fd 2, bypassing Python's sys.stderr, so
            logging levels can't catch them. We mute fd 2 for the load + warmup.
            This is a backup; the primary fix below is to avoid the HF network
            request entirely (offline mode) so there's nothing to print.
            """
            try:
                stderr_fd = sys.stderr.fileno()
            except (AttributeError, ValueError, OSError):
                stderr_fd = 2
            saved_fd = os.dup(stderr_fd)
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(devnull_fd, stderr_fd)
                from sentence_transformers import SentenceTransformer
                m = SentenceTransformer(self._model_name)
                try:
                    m.encode("warmup", convert_to_numpy=True)
                except Exception:
                    pass
                return m
            finally:
                os.dup2(saved_fd, stderr_fd)
                os.close(saved_fd)
                os.close(devnull_fd)

        model = _muted_construct()
        logger.info("Embedding model loaded successfully")
        return model

    async def load_model_async(self) -> bool:
        """Asynchronously load the embedding model in background thread.

        Returns:
            True if model loaded successfully, False otherwise
        """
        if self._model is not None:
            return True  # Already loaded

        if self._loading:
            # Already loading, wait for it
            if self._load_task:
                await self._load_task
            return self._model is not None

        self._loading = True
        try:
            loop = asyncio.get_event_loop()
            self._load_task = loop.run_in_executor(_thread_pool, self._load_model_sync)
            self._model = await self._load_task
            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. RAG features disabled. "
                "Install with: pip install sentence-transformers"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            return False
        finally:
            self._loading = False
            self._load_task = None

    @property
    def model(self):
        """Lazy-load the sentence transformer model (synchronous fallback)."""
        if self._model is None:
            try:
                self._model = self._load_model_sync()
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed. RAG features disabled. "
                    "Install with: pip install sentence-transformers"
                )
                raise
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
                raise
        return self._model

    def is_loaded(self) -> bool:
        """Check if model is already loaded."""
        return self._model is not None

    def is_available(self) -> bool:
        """Check if RAG features are available."""
        try:
            _ = self.model
            return True
        except Exception as e:
            logger.debug(f"RAG not available: {e}")
            return False

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            384-dimensional embedding vector or None if unavailable
        """
        if not text or not text.strip():
            return None

        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of 384-dimensional embedding vectors
        """
        if not texts:
            return []

        try:
            # Filter out empty texts but maintain indices
            valid_texts = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
            if not valid_texts:
                return [None] * len(texts)

            indices, valid_text_list = zip(*valid_texts)
            embeddings = self.model.encode(list(valid_text_list), convert_to_numpy=True)

            # Map back to original indices
            result = [None] * len(texts)
            for idx, embedding in zip(indices, embeddings):
                result[idx] = embedding.tolist()

            return result
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return [None] * len(texts)

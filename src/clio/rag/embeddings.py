"""Embedding generation for conversation messages."""
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from pathlib import Path

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
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model: {self._model_name}")
        model = SentenceTransformer(self._model_name)
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
        except:
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

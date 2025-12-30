"""Embedding generation for conversation messages."""
import logging
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """Manages embedding generation for conversation messages."""

    def __init__(self):
        """Initialize embedding manager with lazy model loading."""
        self._model = None
        self._model_name = "all-MiniLM-L6-v2"

    @property
    def model(self):
        """Lazy-load the sentence transformer model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self._model_name}")
                self._model = SentenceTransformer(self._model_name)
                logger.info("Embedding model loaded successfully")
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

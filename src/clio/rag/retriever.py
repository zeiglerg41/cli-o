"""Context retrieval using semantic search."""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
import chromadb
from chromadb.config import Settings

from .embeddings import EmbeddingManager

logger = logging.getLogger(__name__)


class ContextRetriever:
    """Retrieves relevant context from conversation history using semantic search."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize context retriever.

        Args:
            db_path: Path to ChromaDB storage (defaults to ~/.clio/chroma)
        """
        if db_path is None:
            db_path = Path.home() / ".clio" / "chroma"

        self.db_path = db_path
        self.db_path.mkdir(parents=True, exist_ok=True)

        self.embedding_manager = EmbeddingManager()
        self._client = None
        self._collection = None

    @property
    def client(self):
        """Lazy-load ChromaDB client."""
        if self._client is None:
            try:
                self._client = chromadb.PersistentClient(
                    path=str(self.db_path),
                    settings=Settings(anonymized_telemetry=False)
                )
                logger.info(f"ChromaDB initialized at {self.db_path}")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                raise
        return self._client

    def get_collection(self, conversation_id: int):
        """Get or create collection for a conversation.

        Args:
            conversation_id: ID of the conversation

        Returns:
            ChromaDB collection
        """
        collection_name = f"conversation_{conversation_id}"
        try:
            collection = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"conversation_id": conversation_id}
            )
            return collection
        except Exception as e:
            logger.error(f"Failed to get/create collection: {e}")
            raise

    async def add_message_async(self, conversation_id: int, message_id: int, role: str, content: str) -> bool:
        """Add a message to the vector store asynchronously.

        Loads the embedding model in background thread if needed (first time).

        Args:
            conversation_id: ID of the conversation
            message_id: ID of the message
            role: Message role (user/assistant)
            content: Message content

        Returns:
            True if model needed loading (so caller can show status), False otherwise
        """
        if not content or not content.strip():
            return False

        # Check if model needs loading
        needs_loading = not self.embedding_manager.is_loaded()

        try:
            # Load model asynchronously if needed (first time)
            if needs_loading:
                logger.info("First RAG message - loading embedding model in background...")
                success = await self.embedding_manager.load_model_async()
                if not success:
                    return False

            # Generate embedding (model is now loaded)
            embedding = self.embedding_manager.embed_text(content)
            if embedding is None:
                logger.warning(f"Failed to generate embedding for message {message_id}")
                return needs_loading

            # Add to collection
            collection = self.get_collection(conversation_id)
            collection.add(
                ids=[f"msg_{message_id}"],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{"role": role, "message_id": message_id}]
            )
            logger.debug(f"Added message {message_id} to vector store")
            return needs_loading

        except Exception as e:
            logger.error(f"Failed to add message to vector store: {e}")
            return needs_loading

    def add_message(self, conversation_id: int, message_id: int, role: str, content: str):
        """Add a message to the vector store (synchronous version).

        Args:
            conversation_id: ID of the conversation
            message_id: ID of the message
            role: Message role (user/assistant)
            content: Message content
        """
        if not content or not content.strip():
            return

        try:
            # Generate embedding
            embedding = self.embedding_manager.embed_text(content)
            if embedding is None:
                logger.warning(f"Failed to generate embedding for message {message_id}")
                return

            # Add to collection
            collection = self.get_collection(conversation_id)
            collection.add(
                ids=[f"msg_{message_id}"],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{"role": role, "message_id": message_id}]
            )
            logger.debug(f"Added message {message_id} to vector store")

        except Exception as e:
            logger.error(f"Failed to add message to vector store: {e}")

    def retrieve_context(
        self,
        conversation_id: int,
        query: str,
        n_results: int = 10,
        exclude_recent: int = 20
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant context from conversation history.

        Args:
            conversation_id: ID of the conversation
            query: Query text to find relevant context for
            n_results: Number of results to return
            exclude_recent: Exclude last N messages (they're sent verbatim)

        Returns:
            List of relevant message dicts with content and metadata
        """
        if not query or not query.strip():
            return []

        try:
            # Generate query embedding
            query_embedding = self.embedding_manager.embed_text(query)
            if query_embedding is None:
                logger.warning("Failed to generate query embedding")
                return []

            # Search collection
            collection = self.get_collection(conversation_id)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results + exclude_recent,  # Get extra to filter recent
            )

            if not results or not results['ids'] or not results['ids'][0]:
                return []

            # Parse results
            retrieved = []
            for i in range(len(results['ids'][0])):
                message_id = results['metadatas'][0][i]['message_id']
                content = results['documents'][0][i]
                role = results['metadatas'][0][i]['role']
                distance = results['distances'][0][i] if 'distances' in results else 0

                retrieved.append({
                    'message_id': message_id,
                    'role': role,
                    'content': content,
                    'distance': distance
                })

            # Sort by message_id and filter out recent messages
            retrieved.sort(key=lambda x: x['message_id'])

            # Find max message_id to determine cutoff
            if retrieved:
                max_id = max(r['message_id'] for r in retrieved)
                cutoff_id = max_id - exclude_recent

                # Filter out recent messages
                retrieved = [r for r in retrieved if r['message_id'] < cutoff_id]

            return retrieved[:n_results]

        except Exception as e:
            logger.error(f"Failed to retrieve context: {e}")
            return []

    def clear_conversation(self, conversation_id: int):
        """Clear all messages for a conversation from vector store.

        Args:
            conversation_id: ID of the conversation
        """
        try:
            collection_name = f"conversation_{conversation_id}"
            self.client.delete_collection(name=collection_name)
            logger.info(f"Cleared vector store for conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to clear conversation: {e}")

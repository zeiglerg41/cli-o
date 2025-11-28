"""Base provider interface."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, List, Optional


class Message(dict):
    """Message in conversation."""
    pass


class Provider(ABC):
    """Base provider interface."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with config."""
        self.config = config
    
    @abstractmethod
    async def chat(
        self, 
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send chat completion request."""
        pass
    
    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion."""
        pass
    
    @abstractmethod
    async def list_models(self) -> List[str]:
        """List available models."""
        pass

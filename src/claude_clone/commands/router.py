"""Command router for slash commands."""
import re
from typing import Optional, Tuple, Dict, Any, Callable, Awaitable


class CommandRouter:
    """Routes slash commands to handlers."""
    
    def __init__(self):
        """Initialize command router."""
        self.commands: Dict[str, Callable] = {}
    
    def register(self, command: str, handler: Callable) -> None:
        """Register a command handler."""
        self.commands[command] = handler
    
    def parse(self, user_input: str) -> Tuple[Optional[str], Optional[str], str]:
        """
        Parse user input.
        
        Returns:
            (command, args, original_input) if slash command
            (None, None, original_input) if regular message
        """
        user_input = user_input.strip()
        
        if not user_input.startswith("/"):
            return None, None, user_input
        
        parts = user_input.split(maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        return command, args, user_input
    
    async def execute(self, command: str, args: str) -> str:
        """Execute a command."""
        if command not in self.commands:
            return f"Unknown command: {command}. Type /help for available commands."
        
        handler = self.commands[command]
        
        # Call handler
        if asyncio.iscoroutinefunction(handler):
            return await handler(args)
        else:
            return handler(args)
    
    def extract_mentions(self, text: str) -> list[str]:
        """
        Extract @file and @folder mentions from text.
        
        Returns list of paths mentioned.
        """
        # Match @word or @"path with spaces"
        pattern = r'@(?:"([^"]+)"|(\S+))'
        matches = re.findall(pattern, text)
        
        # Flatten matches (one of the groups will be empty)
        mentions = [m[0] or m[1] for m in matches]
        
        return mentions


import asyncio

"""Core agent implementation."""
import json
from typing import List, Dict, Any, Optional, Callable, Awaitable
from ..providers import Provider, Message, create_provider
from ..config.manager import ConfigManager
from .tools import Tools


class Agent:
    """AI agent with tool use capabilities."""
    
    def __init__(
        self,
        config_manager: ConfigManager,
        permission_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None
    ):
        """Initialize agent."""
        self.config_manager = config_manager
        self.tools = Tools(permission_callback)
        self.messages: List[Message] = []
        
        # Load current provider and model
        config = config_manager.load()
        self.current_provider_name = config.defaults.provider
        self.current_model = config.defaults.model
        
        # Initialize provider
        provider_config = config.providers[self.current_provider_name]
        # Convert config to snake_case for provider
        provider_dict = {
            "base_url": provider_config.baseURL,
            "api_key": provider_config.apiKey,
            "headers": provider_config.headers,
            "models": provider_config.models
        }
        self.provider = create_provider(
            provider_config.type,
            provider_dict
        )
        
        # System prompt
        self.system_prompt = """You are a helpful AI coding assistant. You help users with coding tasks.

## Available Tools
You have access to tools to read, write, and edit files, execute bash commands, and list directories.

## Safety Guidelines - CRITICAL
Before executing ANY command or file operation, you MUST:

1. **Verify Context**: Understand the current working directory and file structure
2. **Check for Destructive Operations**: NEVER execute commands that:
   - Use `rm -rf` (especially with `/`, `/home`, `/etc`, `/usr`, `/var`)
   - Modify system directories (`/etc`, `/boot`, `/sys`, `/proc`, `/dev`)
   - Use `dd` on block devices without explicit user confirmation
   - Drop or truncate databases without backup confirmation
   - Use `chmod -R 777` or similar permission changes on system files
   - Execute `:(){ :|:& };:` (fork bombs) or similar resource exhaustion
   - Use `mkfs` or format commands on mounted filesystems
   - Modify `/etc/passwd`, `/etc/shadow`, or authentication files
   - Use `sudo` or `su` commands
3. **Double-Check**: Before executing destructive operations, explicitly state:
   - What will be modified/deleted
   - Whether it's reversible
   - Request explicit confirmation if uncertain

## File Operations Best Practices
- Understand existing code conventions before making changes
- Mimic code style and patterns already present in the file
- Use existing libraries and utilities instead of reinventing
- Never add comments unless explicitly requested
- Verify file paths before writing or editing

## Response Style
- Be direct and concise - avoid conversational fillers like "Great!" or "Sure!"
- Explain your reasoning BEFORE using tools
- If an operation fails, attempt to fix it, but escalate after 2-3 attempts
- Stay focused on the specific task without assumption

## Context Handling
When the user mentions @file or @folder, those files will be included in your context automatically."""

    async def switch_model(self, provider_name: str, model: str) -> None:
        """Switch to a different provider and model."""
        config = self.config_manager.load()
        
        if provider_name not in config.providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        
        provider_config = config.providers[provider_name]
        
        if model not in provider_config.models:
            raise ValueError(f"Model {model} not available in provider {provider_name}")
        
        # Update current provider and model
        self.current_provider_name = provider_name
        self.current_model = model
        
        # Reinitialize provider
        # Convert config to snake_case for provider
        provider_dict = {
            "base_url": provider_config.baseURL,
            "api_key": provider_config.apiKey,
            "headers": provider_config.headers,
            "models": provider_config.models
        }
        self.provider = create_provider(
            provider_config.type,
            provider_dict
        )
        
        # Update config
        self.config_manager.set_default_model(provider_name, model)
    
    async def chat(self, user_message: str, context: str = "") -> str:
        """Send a message and get response."""
        # Add context if provided
        if context:
            user_message = f"{context}\n\n{user_message}"
        
        # Add user message
        self.messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Prepare messages with system prompt
        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.messages
        ]
        
        # Get tool definitions
        tools = self.tools.get_tool_definitions()
        
        # Call LLM
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                model=self.current_model,
                tools=tools
            )
            
            choice = response["choices"][0]
            message = choice["message"]
            
            # Add assistant message
            self.messages.append(message)
            messages.append(message)
            
            # Check if done
            if choice["finish_reason"] == "stop" or not message.get("tool_calls"):
                content = message.get("content")
                if content is None or content == "":
                    return "[No response from model]"
                return content
            
            # Execute tool calls
            if message.get("tool_calls"):
                for tool_call in message["tool_calls"]:
                    function = tool_call["function"]
                    tool_name = function["name"]
                    
                    try:
                        arguments = json.loads(function["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}
                    
                    # Execute tool
                    result = await self.tools.execute_tool(tool_name, arguments)
                    
                    # Add tool result
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result
                    }
                    
                    self.messages.append(tool_message)
                    messages.append(tool_message)
        
        return "Max iterations reached"
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
    
    def get_history(self) -> List[Message]:
        """Get conversation history."""
        return self.messages.copy()

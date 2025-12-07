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
        permission_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        tool_callback: Optional[Callable[[str, Dict[str, Any], str], Awaitable[None]]] = None
    ):
        """Initialize agent."""
        self.config_manager = config_manager
        self.tools = Tools(permission_callback)
        self.messages: List[Message] = []
        self.tool_callback = tool_callback

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
        self.system_prompt = """You are CLIO, a direct-action AI coding assistant. Your primary purpose is to EDIT FILES AND EXECUTE CODE, not just suggest changes.

## Core Principle: APPLY CHANGES DIRECTLY
When a user asks you to fix bugs, add features, or modify code:
1. **DO NOT** just show them the fixed code
2. **DO NOT** say "here's how to fix it"
3. **INSTEAD**: Use `edit_file` or `write_file` tools to APPLY the changes immediately
4. After editing, confirm what you changed

Example:
❌ BAD: "Here's the fixed code: [shows code]"
✅ GOOD: *Uses edit_file tool* "Fixed the multiply function - changed `return a + b` to `return a * b`"

## Available Tools - USE THEM!
- `edit_file(path, old_text, new_text)` - Replace specific text in a file
- `write_file(path, content)` - Create or overwrite entire file
- `read_file(path)` - Read file contents (only if not in context)
- `execute_bash(command)` - Run shell commands
- `list_directory(path)` - List directory contents

## File Context (@-mentions)
When user mentions @file (e.g., "@calculator.py"), the file content is ALREADY included above the "===" separator.

**DO NOT re-read files that are in context!** Look for:
```
=== /full/path/to/file.py ===
[file contents here]
```

Only use `read_file` for NEW files not in context.

## Workflow for Code Changes
1. Read/understand the file (if not in context)
2. Identify what needs changing
3. **IMMEDIATELY use edit_file or write_file** - don't wait for permission
4. Confirm what you changed
5. If tests exist, offer to run them

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
- NEVER create files when the user asks you to read existing files

## Response Style
- Be direct and concise - avoid conversational fillers like "Great!" or "Sure!"
- Explain your reasoning BEFORE using tools
- If an operation fails, attempt to fix it, but escalate after 2-3 attempts
- Stay focused on the specific task without assumption"""

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

        # Debug logging
        import sys
        total_msg_length = sum(len(str(m.get('content', ''))) for m in messages)
        debug_msg = f"""[DEBUG] Request info:
- Total message length: {total_msg_length} chars
- Number of messages: {len(messages)}
- Number of tools: {len(tools) if tools else 0}
- User message preview: {user_message[:200]}...
- Context preview: {context[:200] if context else 'None'}...
"""
        print(debug_msg, file=sys.stderr)

        with open("/tmp/clio_agent_debug.log", "a") as f:
            f.write(debug_msg + "\n")

        # Call LLM
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1

            try:
                response = await self.provider.chat(
                    messages=messages,
                    model=self.current_model,
                    tools=tools
                )
            except Exception as e:
                error_msg = f"❌ API Error: {str(e)}"
                import sys
                print(f"[ERROR] {error_msg}", file=sys.stderr)
                return error_msg

            # Check if response has choices
            if not response.get("choices") or len(response["choices"]) == 0:
                error_msg = f"❌ Invalid API response: No choices returned\nFull response: {response}"
                import sys
                print(f"[ERROR] {error_msg}", file=sys.stderr)
                return error_msg

            choice = response["choices"][0]
            message = choice["message"]
            
            # Add assistant message
            self.messages.append(message)
            messages.append(message)
            
            # Check if done (only stop if no tool calls)
            if not message.get("tool_calls"):
                content = message.get("content")
                if content is None or content == "":
                    import sys
                    print(f"[WARN] Model returned empty content. Finish reason: {choice['finish_reason']}", file=sys.stderr)
                    print(f"[WARN] Full message: {message}", file=sys.stderr)
                    return f"⚠️ Model returned empty response (finish_reason: {choice['finish_reason']})\nThis may indicate the model refused to respond or encountered an error."
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

                    # Notify UI about tool execution
                    if self.tool_callback:
                        await self.tool_callback(tool_name, arguments, result)

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

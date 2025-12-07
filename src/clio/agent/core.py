"""Core agent implementation."""
import json
from typing import List, Dict, Any, Optional, Callable, Awaitable
from ..providers import Provider, Message, create_provider
from ..config.manager import ConfigManager
from .tools import Tools
from .session_logger import SessionLogger


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

        # Initialize session logger
        self.session_logger = SessionLogger()

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

## Error Recovery - CRITICAL
If a tool returns an error (especially "Text not found in file"):
1. **IMMEDIATELY read the file again** to see the current state
2. The file may have been edited by the user or another process
3. Do NOT assume the file still contains what you think it does
4. After reading, analyze what changed and adjust your approach
5. NEVER repeatedly try the same edit that failed - always check first

Example of CORRECT error recovery:
❌ BAD: Tool returns "Text not found" → Try same edit again → Fails again
✅ GOOD: Tool returns "Text not found" → Use read_file to check current state → Adjust edit based on what's actually there

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
        # Log user message
        self.session_logger.log_user_message(user_message, context)

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

        # Log request details
        total_msg_length = sum(len(str(m.get('content', ''))) for m in messages)
        self.session_logger.log_llm_request(
            model=self.current_model,
            message_count=len(messages),
            tool_count=len(tools) if tools else 0,
            total_chars=total_msg_length
        )

        # Call LLM
        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self.session_logger.log_iteration(iteration, max_iterations)

            try:
                response = await self.provider.chat(
                    messages=messages,
                    model=self.current_model,
                    tools=tools
                )
            except Exception as e:
                error_msg = f"❌ API Error: {str(e)}"
                self.session_logger.log_error(error_msg)
                return error_msg

            # Check if response has choices
            if not response.get("choices") or len(response["choices"]) == 0:
                error_msg = f"❌ Invalid API response: No choices returned\nFull response: {response}"
                self.session_logger.log_error(error_msg)
                return error_msg

            choice = response["choices"][0]
            message = choice["message"]

            # Log LLM response
            self.session_logger.log_llm_response(
                content=message.get("content"),
                has_tool_calls=bool(message.get("tool_calls")),
                finish_reason=choice.get("finish_reason", "unknown")
            )

            # Add assistant message
            self.messages.append(message)
            messages.append(message)

            # Check if done (only stop if no tool calls)
            if not message.get("tool_calls"):
                content = message.get("content")
                if content is None or content == "":
                    error_msg = f"⚠️ Model returned empty response (finish_reason: {choice['finish_reason']})"
                    self.session_logger.log_error(error_msg)
                    return f"{error_msg}\nThis may indicate the model refused to respond or encountered an error."
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

                    # Log tool call
                    self.session_logger.log_tool_call(tool_name, arguments)

                    # Execute tool
                    result = await self.tools.execute_tool(tool_name, arguments)

                    # Log tool result
                    self.session_logger.log_tool_result(tool_name, result)

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

        error_msg = "Max iterations reached"
        self.session_logger.log_error(error_msg)
        return error_msg
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
    
    def get_history(self) -> List[Message]:
        """Get conversation history."""
        return self.messages.copy()

"""Core agent implementation."""
import json
import os
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
from ..providers import Provider, Message, create_provider
from ..config.manager import ConfigManager
from .tools import Tools
from .session_logger import SessionLogger
from ..history.database import HistoryDatabase


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> tags and their content from model output."""
    if not text:
        return text
    # Remove <think>...</think> blocks (case insensitive, handles newlines)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove orphaned opening tags
    text = re.sub(r'<think>', '', text, flags=re.IGNORECASE)
    # Remove orphaned closing tags
    text = re.sub(r'</think>', '', text, flags=re.IGNORECASE)
    # Clean up excessive whitespace
    text = re.sub(r'\n\n\n+', '\n\n', text)
    return text.strip()


class Agent:
    """AI agent with tool use capabilities."""

    def __init__(
        self,
        config_manager: ConfigManager,
        permission_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        tool_callback: Optional[Callable[[str, Dict[str, Any], str], Awaitable[None]]] = None,
        conversation_id: Optional[int] = None
    ):
        """Initialize agent.

        Args:
            conversation_id: If provided, resume from this conversation ID
        """
        self.config_manager = config_manager
        self.tools = Tools(permission_callback)
        self.messages: List[Message] = []
        self.tool_callback = tool_callback

        # Initialize session logger
        self.session_logger = SessionLogger()

        # Initialize history database
        self.history_db = HistoryDatabase()
        self.conversation_id = conversation_id

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

        # Create or resume conversation in database
        if self.conversation_id:
            # Resume existing conversation - load recent messages only
            messages = self.history_db.get_conversation_messages(self.conversation_id)

            # Use hybrid approach: last 20 messages verbatim, RAG for older context
            # (RAG retrieval happens per-query in chat() method)
            if len(messages) > 20:
                # Load only recent messages to avoid context window issues
                self.messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages[-20:]]
                self.session_logger.logger.info(
                    f"Loaded last 20 of {len(messages)} messages. "
                    f"RAG will retrieve relevant older context as needed."
                )
            else:
                self.messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages]
        else:
            # Create new conversation
            working_dir = os.getcwd()
            self.conversation_id = self.history_db.create_conversation(
                working_dir=working_dir,
                model=self.current_model,
                provider=self.current_provider_name
            )

        # System prompt - Based on Qwen3 best practices: keep concise, single-purpose
        self.system_prompt = """You are a coding assistant that directly edits files using tools.

When user says "@file change X to Y", immediately:
1. read_file("file")
2. edit_file("file", "X", "Y")
3. Respond: "Changed X to Y"

Never explain or ask - just execute the edits.

Available tools: edit_file, read_file, write_file, execute_bash, grep_files, find_files, list_directory"""

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

        # NOTE: Context injection removed - @ mentions should trigger tool calls
        # The model should use read_file tool when it sees @filename references
        # if context:
        #     user_message = f"{context}\n\n{user_message}"

        # Add user message
        self.messages.append({
            "role": "user",
            "content": user_message
        })

        # Save user message to history
        self.history_db.add_message(
            conversation_id=self.conversation_id,
            role="user",
            content=user_message
        )

        # Retrieve relevant context using RAG (if available)
        rag_context = []
        if len(self.messages) > 20:  # Only use RAG if we have a long conversation
            rag_context = self.history_db.retrieve_rag_context(
                conversation_id=self.conversation_id,
                query=user_message,
                n_results=10,
                exclude_recent=20
            )
            if rag_context:
                self.session_logger.logger.info(f"Retrieved {len(rag_context)} relevant messages via RAG")

        # Build context with system prompt + RAG context + recent messages
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add RAG retrieved context if available
        if rag_context:
            rag_summary = "# Relevant Context from Earlier in Conversation:\n\n"
            for ctx in rag_context:
                role_label = "You" if ctx['role'] == "user" else "Assistant"
                rag_summary += f"**{role_label}:** {ctx['content'][:200]}...\n\n"

            messages.append({
                "role": "system",
                "content": rag_summary
            })

        # Add recent messages
        messages.extend(self.messages)

        # Get tool definitions
        tools = self.tools.get_tool_definitions()

        # Check if model supports tool calling
        if tools and not self.provider.supports_tools(self.current_model):
            warning_msg = (
                f"⚠️  Warning: Model '{self.current_model}' does not support tool calling. "
                f"Tools will be disabled for this conversation. "
                f"Consider switching to a model that supports tools."
            )
            self.session_logger.logger.warning(warning_msg)
            print(warning_msg)  # Also print to console
            tools = None  # Disable tools

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

            # Save assistant message to history
            tool_calls_json = json.dumps(message.get("tool_calls")) if message.get("tool_calls") else None
            self.history_db.add_message(
                conversation_id=self.conversation_id,
                role="assistant",
                content=message.get("content", ""),
                tool_calls=tool_calls_json
            )

            # Check if done (only stop if no tool calls)
            if not message.get("tool_calls"):
                content = message.get("content")
                if content is None or content == "":
                    error_msg = f"⚠️ Model returned empty response (finish_reason: {choice['finish_reason']})"
                    self.session_logger.log_error(error_msg)
                    return f"{error_msg}\nThis may indicate the model refused to respond or encountered an error."
                # Strip thinking tags before returning
                return strip_thinking_tags(content)
            
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

                    # Save tool result to history
                    self.history_db.add_message(
                        conversation_id=self.conversation_id,
                        role="tool",
                        content=result
                    )

        error_msg = "Max iterations reached"
        self.session_logger.log_error(error_msg)
        return error_msg
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
    
    def get_history(self) -> List[Message]:
        """Get conversation history."""
        return self.messages.copy()

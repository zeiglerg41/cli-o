"""Core agent implementation."""
import asyncio
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

    # Model pricing (input/output per 1M tokens)
    MODEL_PRICING = {
        # OpenAI models (per 1M tokens)
        "gpt-5.2": {"input": 1.25, "output": 10.00},
        "gpt-5.1": {"input": 1.50, "output": 12.00},
        "gpt-5": {"input": 2.00, "output": 15.00},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4.1-mini": {"input": 0.50, "output": 2.00},
        "gpt-4.1-nano": {"input": 0.10, "output": 0.50},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "o1": {"input": 15.00, "output": 60.00},
        "o1-preview": {"input": 15.00, "output": 60.00},
        "o1-mini": {"input": 3.00, "output": 12.00},
        "o3-mini": {"input": 1.10, "output": 4.40},

        # Anthropic Claude models (per 1M tokens)
        # Claude 4.5 family (latest - Nov 2025)
        "claude-opus-4-5": {"input": 5.00, "output": 25.00},
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
        # Claude 4.1 family (Aug 2025)
        "claude-opus-4-1": {"input": 15.00, "output": 75.00},
        # Claude 4 family
        "claude-opus-4": {"input": 15.00, "output": 75.00},
        "claude-sonnet-4": {"input": 3.00, "output": 15.00},
        # Claude 3.7 family
        "claude-3-7-sonnet": {"input": 3.00, "output": 15.00},
        # Claude 3.5 family
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
        # Claude 3 family (deprecated)
        "claude-3-opus": {"input": 15.00, "output": 75.00},
        "claude-3-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},

        # Google Gemini models (per 1M tokens)
        "gemini-2.0-flash": {"input": 0.00, "output": 0.00},  # Free tier
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},

        # DeepSeek models (per 1M tokens)
        "deepseek-chat": {"input": 0.14, "output": 0.28},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
        "deepseek-coder": {"input": 0.14, "output": 0.28},
    }

    def __init__(
        self,
        config_manager: ConfigManager,
        permission_callback: Optional[Callable[[str, str, Optional[dict]], Awaitable[bool]]] = None,
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
                self.messages = self._reconstruct_messages(messages[-20:])
                self.session_logger.logger.info(
                    f"Loaded last 20 of {len(messages)} messages. "
                    f"RAG will retrieve relevant older context as needed."
                )
            else:
                self.messages = self._reconstruct_messages(messages)
        else:
            # Create new conversation
            working_dir = os.getcwd()
            self.conversation_id = self.history_db.create_conversation(
                working_dir=working_dir,
                model=self.current_model,
                provider=self.current_provider_name
            )

        # System prompt - Based on Qwen3 best practices: keep concise, single-purpose
        # Load system prompt from config, or use default
        default_system_prompt = """You are a coding assistant that directly edits files using tools.

@ MENTIONS: When user writes @filename or @path, strip the @ prefix before using in tool calls.
Example: "@clio/" → list_directory("clio/")

When user says "@file change X to Y", immediately:
1. read_file("file")
2. edit_file("file", "X", "Y")
3. Respond: "Changed X to Y"

SPELLING & TYPOS:
- Autocorrect obvious typos and misspellings in user requests
- Use context clues to infer intended meaning (e.g., "Securtoy" → "Security")
- Don't ask for clarification on minor spelling errors - just proceed with the corrected version

RESPONSE RULES (CRITICAL):
- Zero fluff. No greetings, pleasantries, or filler phrases like "Let me know" or "Feel free to ask"
- Answer questions with minimum viable words. "Yes" not "Yes, I can do that"
- State facts only. Never pad responses
- Never explain unless explicitly asked "why" or "how"
- Execute tool calls immediately without narration

Available tools: edit_file, read_file, write_file, execute_bash, grep_files, find_files, list_directory"""

        # Use custom system prompt from config if provided
        from ..config.manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.load()
        self.system_prompt = config.preferences.system_prompt or default_system_prompt

    def _reconstruct_messages(self, db_messages: List[Dict]) -> List[Message]:
        """Reconstruct messages from database format to API format.

        For old conversations, tool messages may not have tool_call_id saved.
        We extract them from the preceding assistant's tool_calls and match them up.

        Args:
            db_messages: Messages from database with role, content, tool_calls, tool_call_id

        Returns:
            List of properly formatted messages for the API
        """
        reconstructed = []
        pending_tool_call_ids = []  # Queue of tool_call_ids waiting for tool responses

        # DEBUG: Log what we're reconstructing
        with open("/tmp/clio_reconstruct_debug.log", "w") as f:
            f.write(f"=== RECONSTRUCTING {len(db_messages)} MESSAGES ===\n")
            for i, msg in enumerate(db_messages):
                f.write(f"{i}: role={msg['role']}, has_tool_calls={bool(msg.get('tool_calls'))}, has_tool_call_id={bool(msg.get('tool_call_id'))}\n")

        for i, msg in enumerate(db_messages):
            message = {"role": msg["role"], "content": msg["content"]}

            # Handle assistant messages with tool_calls
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                try:
                    tool_calls = json.loads(msg["tool_calls"])
                    message["tool_calls"] = tool_calls

                    # Extract tool_call_ids for matching with subsequent tool messages
                    pending_tool_call_ids.extend([tc["id"] for tc in tool_calls])

                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: Added {len(tool_calls)} pending tool_call_ids\n")
                except (json.JSONDecodeError, TypeError):
                    # If tool_calls is malformed, skip it
                    self.session_logger.logger.warning("Malformed tool_calls JSON in database")
                    pass

            # Handle tool messages
            elif msg["role"] == "tool":
                if msg.get("tool_call_id"):
                    # New format: tool_call_id is saved in database
                    # But check if this tool_call_id is in our pending list
                    # If not, it means the parent assistant message was truncated (outside 20-message window)
                    if msg["tool_call_id"] not in pending_tool_call_ids:
                        with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                            f.write(f"  {i}: SKIPPING tool message - parent assistant truncated\n")
                        self.session_logger.logger.info(
                            "Skipping tool message whose parent assistant was truncated"
                        )
                        continue

                    message["tool_call_id"] = msg["tool_call_id"]
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: Using saved tool_call_id: {msg['tool_call_id']}\n")

                    # Remove this tool_call_id from pending list to mark it as fulfilled
                    pending_tool_call_ids.remove(msg["tool_call_id"])
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: Removed from pending (remaining: {len(pending_tool_call_ids)})\n")
                elif pending_tool_call_ids:
                    # Old format: reconstruct by matching with pending tool_call_ids
                    message["tool_call_id"] = pending_tool_call_ids.pop(0)
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: Reconstructed tool_call_id (pending left: {len(pending_tool_call_ids)})\n")
                    self.session_logger.logger.info(
                        f"Reconstructed tool_call_id for old tool message"
                    )
                else:
                    # Orphaned tool message with no preceding assistant tool_call
                    # This shouldn't happen but handle gracefully by skipping
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: SKIPPING orphaned tool message\n")
                    self.session_logger.logger.warning(
                        "Skipping orphaned tool message (no matching tool_call_id)"
                    )
                    continue

            reconstructed.append(message)

        # Final cleanup: If there are any pending tool_call_ids left (orphaned tool_calls with no responses),
        # we need to remove the user message that triggered them, the assistant response, and any tool messages
        # This prevents the agent from trying to re-execute cancelled requests when resuming a conversation
        if pending_tool_call_ids:
            with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                f.write(f"WARNING: {len(pending_tool_call_ids)} orphaned tool_call_ids remain - cleaning up\n")
            self.session_logger.logger.warning(
                f"Removing incomplete request with {len(pending_tool_call_ids)} orphaned tool_calls (likely from cancelled permission)"
            )
            # Find and remove the last assistant message with tool_calls
            assistant_idx = None
            for i in range(len(reconstructed) - 1, -1, -1):
                if reconstructed[i].get("role") == "assistant" and reconstructed[i].get("tool_calls"):
                    assistant_idx = i
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  Found orphaned assistant message at index {i}\n")
                    break

            if assistant_idx is not None:
                # Remove any tool messages that follow the assistant message
                num_tool_calls = len(pending_tool_call_ids)
                removed_tools = 0
                i = assistant_idx + 1
                while i < len(reconstructed) and removed_tools < num_tool_calls:
                    if reconstructed[i].get("role") == "tool":
                        with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                            f.write(f"  Removing orphaned tool message at index {i}\n")
                        reconstructed.pop(i)
                        removed_tools += 1
                    else:
                        # Stop when we hit a non-tool message
                        break

                # Remove the assistant message
                with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                    f.write(f"  Removing assistant message at index {assistant_idx}\n")
                reconstructed.pop(assistant_idx)

                # Also remove the user message that preceded it (the cancelled request)
                # This prevents the agent from trying to re-execute the request
                if assistant_idx > 0 and reconstructed[assistant_idx - 1].get("role") == "user":
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  Removing cancelled user request at index {assistant_idx - 1}\n")
                    reconstructed.pop(assistant_idx - 1)
                    self.session_logger.logger.info("Removed cancelled request from conversation history")

                pending_tool_call_ids.clear()

        # Additional cleanup: Remove empty assistant messages and merge consecutive assistant messages
        # This happens when permission is denied and we get assistant → tool → assistant → tool pattern
        cleaned = []
        for i, msg in enumerate(reconstructed):
            # Skip empty assistant messages (no content and no tool_calls)
            if msg["role"] == "assistant" and not msg.get("content") and not msg.get("tool_calls"):
                with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                    f.write(f"  Skipping empty assistant message at index {i}\n")
                continue

            # Merge consecutive assistant messages
            if cleaned and cleaned[-1]["role"] == "assistant" and msg["role"] == "assistant":
                with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                    f.write(f"  Merging consecutive assistant messages at index {i}\n")
                # Merge content
                if msg.get("content"):
                    if cleaned[-1].get("content"):
                        cleaned[-1]["content"] += "\n\n" + msg["content"]
                    else:
                        cleaned[-1]["content"] = msg["content"]
                # Merge tool_calls
                if msg.get("tool_calls"):
                    if cleaned[-1].get("tool_calls"):
                        cleaned[-1]["tool_calls"].extend(msg["tool_calls"])
                    else:
                        cleaned[-1]["tool_calls"] = msg["tool_calls"]
                continue

            cleaned.append(msg)

        with open("/tmp/clio_reconstruct_debug.log", "a") as f:
            f.write(f"\n=== FINAL: {len(cleaned)} messages reconstructed (from {len(reconstructed)} before cleanup) ===\n")

        return cleaned

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

    async def _save_message_with_rag(self, conversation_id: int, role: str, content: str,
                                     tool_calls: Optional[str] = None, tool_call_id: Optional[str] = None):
        """Save message with RAG in background (fire-and-forget).

        Logs when RAG model is loaded for the first time.
        """
        try:
            rag_model_loaded = await self.history_db.add_message_async(
                conversation_id=conversation_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id
            )
            if rag_model_loaded:
                self.session_logger.logger.info("✓ RAG embedding model loaded successfully (one-time setup)")
        except Exception as e:
            self.session_logger.logger.error(f"Failed to save message with RAG: {e}")

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate cost in USD for a model request.

        Args:
            model: Model name
            prompt_tokens: Input tokens
            completion_tokens: Output tokens

        Returns:
            Cost in USD
        """
        # Find pricing for this model (check for exact match or prefix)
        pricing = None
        model_lower = model.lower()

        # Try exact match first
        if model_lower in self.MODEL_PRICING:
            pricing = self.MODEL_PRICING[model_lower]
        else:
            # Try prefix match (e.g., "gpt-4o-2024-05-13" matches "gpt-4o")
            for model_prefix, model_pricing in self.MODEL_PRICING.items():
                if model_lower.startswith(model_prefix):
                    pricing = model_pricing
                    break

        if not pricing:
            # Unknown model - return 0 cost
            return 0.0

        # Calculate cost (prices are per 1M tokens)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

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

        # Save user message to history (fire-and-forget - don't wait for RAG model loading)
        asyncio.create_task(self._save_message_with_rag(
            conversation_id=self.conversation_id,
            role="user",
            content=user_message
        ))

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
        # Add current date to system prompt dynamically
        from datetime import datetime
        current_date = datetime.now().strftime("%B %d, %Y")  # e.g., "December 31, 2025"
        system_prompt_with_date = f"{self.system_prompt}\n\nCurrent date: {current_date}"

        messages = [{"role": "system", "content": system_prompt_with_date}]

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
            except asyncio.CancelledError:
                # Re-raise cancellation to propagate to UI
                raise
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

            # Capture usage statistics
            if response.get("usage"):
                usage = response["usage"]
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # Calculate cost
                cost_usd = self._calculate_cost(
                    self.current_model,
                    prompt_tokens,
                    completion_tokens
                )

                # Store in database
                self.history_db.add_usage_stat(
                    conversation_id=self.conversation_id,
                    model=self.current_model,
                    provider=self.current_provider_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd
                )

            # Add assistant message
            self.messages.append(message)
            messages.append(message)

            # Save assistant message to history (fire-and-forget)
            tool_calls_json = json.dumps(message.get("tool_calls")) if message.get("tool_calls") else None
            asyncio.create_task(self._save_message_with_rag(
                conversation_id=self.conversation_id,
                role="assistant",
                content=message.get("content", ""),
                tool_calls=tool_calls_json
            ))

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

                    # Save tool result to history (fire-and-forget)
                    asyncio.create_task(self._save_message_with_rag(
                        conversation_id=self.conversation_id,
                        role="tool",
                        content=result,
                        tool_call_id=tool_call["id"]
                    ))

        error_msg = "Max iterations reached"
        self.session_logger.log_error(error_msg)
        return error_msg
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
    
    def get_history(self) -> List[Message]:
        """Get conversation history."""
        return self.messages.copy()

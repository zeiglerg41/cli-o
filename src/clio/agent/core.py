"""Core agent implementation."""
import asyncio
import json
import os
import random
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


_INTENT_PHRASES = (
    "let me ", "let's ", "let us ", "i'll ", "i will ", "i'm going to ", "i am going to ",
    "now i", "next, i", "next i", "i need to search", "i need to look", "i need to check",
    "i need to find", "searching for", "let me search", "let me look", "let me check",
    "let me find", "let me investigate", "i should search", "i should look",
)


def _looks_like_unfinished_intent(text: str) -> bool:
    """True if the assistant text announces a next action but doesn't take it.

    Smaller local models often emit "Let me search more broadly:" with no tool
    call, which would otherwise end the turn. Conservative: only fires on short
    messages that trail off (end with a colon) or announce an action via a known
    intent phrase, so genuine final answers are not mistaken for unfinished ones.
    """
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith(":"):
        return True
    if len(t) < 240:
        low = t.lower()
        if any(p in low for p in _INTENT_PHRASES):
            return True
    return False


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
        conversation_id: Optional[int] = None,
        token_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """Initialize agent.

        Args:
            conversation_id: If provided, resume from this conversation ID
            token_callback: If set, the assistant's text is streamed to it token
                by token (and the provider streams instead of waiting for the
                full response).
        """
        self.config_manager = config_manager
        self.tools = Tools(permission_callback)
        self.messages: List[Message] = []
        self.tool_callback = tool_callback
        self.token_callback = token_callback

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
        self.original_working_dir = None
        self.recent_files = []  # Track files worked on in this conversation
        if self.conversation_id:
            # Resume existing conversation - load recent messages only
            messages = self.history_db.get_conversation_messages(self.conversation_id)

            # Get conversation metadata (working directory, etc.)
            conversation = self.history_db.get_conversation(self.conversation_id)
            if conversation:
                self.original_working_dir = conversation.get('working_dir')

            # Extract recently edited/written files from full history (for context)
            self.recent_files = self._extract_recent_files(messages)

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
            self.original_working_dir = working_dir
            self.conversation_id = self.history_db.create_conversation(
                working_dir=working_dir,
                model=self.current_model,
                provider=self.current_provider_name
            )

        # System prompt - Based on Qwen3 best practices: keep concise, single-purpose
        # Load system prompt from config, or use default
        from .constants import DEFAULT_SYSTEM_PROMPT
        from ..config.manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.load()
        self.system_prompt = config.preferences.system_prompt or DEFAULT_SYSTEM_PROMPT

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
                # Skip assistant messages that ONLY have tool_calls with no text response
                # Since we're skipping tool results, these incomplete messages are useless
                if not msg.get("content") or not msg["content"].strip():
                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: SKIPPING assistant with tool_calls but no content\n")
                    self.session_logger.logger.info(
                        "Skipping assistant message with only tool_calls (no text response)"
                    )
                    continue

                try:
                    tool_calls = json.loads(msg["tool_calls"])
                    # Don't include tool_calls in the reconstructed message - they're not useful without results
                    # message["tool_calls"] = tool_calls

                    with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                        f.write(f"  {i}: Stripped {len(tool_calls)} tool_calls from assistant message\n")
                except (json.JSONDecodeError, TypeError):
                    # If tool_calls is malformed, skip it
                    self.session_logger.logger.warning("Malformed tool_calls JSON in database")
                    pass

            # Handle tool messages - SKIP THEM to save tokens (observation masking)
            # Tool results are ephemeral - the assistant's response already captures what it learned
            elif msg["role"] == "tool":
                with open("/tmp/clio_reconstruct_debug.log", "a") as f:
                    f.write(f"  {i}: SKIPPING tool message to save tokens (observation masking)\n")
                self.session_logger.logger.info(
                    "Skipping tool message when loading history (observation masking)"
                )
                # Remove from pending list if present to keep tracking consistent
                if msg.get("tool_call_id") and msg["tool_call_id"] in pending_tool_call_ids:
                    pending_tool_call_ids.remove(msg["tool_call_id"])
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

    def _extract_recent_files(self, messages: List[Dict]) -> List[str]:
        """Extract file paths from tool calls in conversation history.

        Scans assistant messages for write_file, edit_file tool calls
        and returns unique file paths (most recent first).
        """
        files = []
        seen = set()

        # Iterate in reverse to get most recent files first
        for msg in reversed(messages):
            if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                try:
                    tool_calls = json.loads(msg['tool_calls']) if isinstance(msg['tool_calls'], str) else msg['tool_calls']
                    for call in tool_calls:
                        func = call.get('function', {})
                        name = func.get('name')
                        if name in ['write_file', 'edit_file']:
                            try:
                                args = json.loads(func.get('arguments', '{}'))
                                path = args.get('path')
                                if path and path not in seen:
                                    files.append(path)
                                    seen.add(path)
                            except:
                                pass
                except:
                    pass

        # Return up to 10 most recent files
        return files[:10]

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
                self.session_logger.logger.info("RAG embedding model loaded successfully (one-time setup)")
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
        # Add current date and working directory to system prompt dynamically
        from datetime import datetime
        current_date = datetime.now().strftime("%B %d, %Y")  # e.g., "December 31, 2025"
        system_prompt_with_date = f"{self.system_prompt}\n\nCurrent date: {current_date}"

        # Always tell the model where it is running, so it uses "." / the actual
        # path instead of guessing (e.g. inventing "~/RTS" while already inside it).
        cwd = os.getcwd()
        system_prompt_with_date += (
            f"\n\nCurrent working directory: {cwd}"
            "\nWhen the user refers to \"this\"/\"the current\" directory or a project "
            "by its folder name, operate on this directory (use \".\") rather than "
            "constructing a path from the home directory."
        )
        if self.original_working_dir and cwd != self.original_working_dir:
            system_prompt_with_date += f"\n\nNote: This conversation was originally started in: {self.original_working_dir}"

        # Persistent project memory: load CLIO.md files (global + project chain)
        # so standing conventions/instructions survive across sessions.
        from .memory import load_project_memory
        project_memory = load_project_memory(cwd)
        if project_memory:
            system_prompt_with_date += (
                "\n\n# Project memory (from CLIO.md)\n"
                "Standing instructions and context for this project. Follow these.\n\n"
                f"{project_memory}"
            )

        # Add recently edited files context if resuming
        if self.recent_files:
            files_list = "\n".join(f"  - {f}" for f in self.recent_files[:5])
            system_prompt_with_date += f"\n\nFiles you recently worked on in this conversation:\n{files_list}"

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

        # Apply sliding window: keep only last N messages to prevent unbounded growth
        # This prevents token explosion during long sessions
        # Reduced from 40 to 20 to handle code-heavy conversations
        MAX_CONTEXT_MESSAGES = 20  # Keep last 20 messages (10 user/assistant pairs)

        # Take only recent messages
        recent_messages = self.messages[-MAX_CONTEXT_MESSAGES:] if len(self.messages) > MAX_CONTEXT_MESSAGES else self.messages

        # Additional safety: Estimate tokens and truncate further if needed
        # Use tiktoken for accurate token counting
        MAX_CONTEXT_TOKENS = 15000  # Conservative limit to leave room for response

        try:
            import tiktoken
            # Get encoding for current model (fallback to cl100k_base for GPT-4/Claude)
            try:
                encoding = tiktoken.encoding_for_model(self.current_model)
            except KeyError:
                # Model not recognized, use cl100k_base (GPT-4, Claude, most modern models)
                encoding = tiktoken.get_encoding("cl100k_base")

            # Count tokens accurately
            estimated_tokens = 0
            for msg in recent_messages:
                content = str(msg.get('content', ''))
                estimated_tokens += len(encoding.encode(content))
                # Add overhead for role, function calls, etc.
                estimated_tokens += 4  # Rough overhead per message

        except ImportError:
            # Fallback to character-based estimation if tiktoken not available
            estimated_tokens = sum(len(str(msg.get('content', ''))) // 4 for msg in recent_messages)

        # If still too large, aggressively reduce to last 10 messages
        if estimated_tokens > MAX_CONTEXT_TOKENS:
            recent_messages = self.messages[-10:] if len(self.messages) > 10 else self.messages
            self.session_logger.logger.warning(
                f"Context reduced to last 10 messages due to token count: {estimated_tokens}"
            )

        # Add recent messages while maintaining API contract
        # Track which tool_call_ids have been declared to avoid orphaned tool messages
        declared_tool_call_ids = set()

        # First pass: collect all tool_call_ids from assistant messages
        for msg in recent_messages:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                for tool_call in msg["tool_calls"]:
                    declared_tool_call_ids.add(tool_call["id"])

        # Second pass: add messages, skipping orphaned tool results
        for msg in recent_messages:
            # Skip tool messages that don't have a corresponding assistant tool_call
            if msg["role"] == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id and tool_call_id not in declared_tool_call_ids:
                    continue  # Skip orphaned tool message
            messages.append(msg)

        # Get tool definitions
        tools = self.tools.get_tool_definitions()

        # Check if model supports tool calling
        if tools and not self.provider.supports_tools(self.current_model):
            warning_msg = (
                f"Warning: Model '{self.current_model}' does not support tool calling. "
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

        # Agentic loop: Turn = one LLM call + all tool executions
        # Following OpenAI Agents SDK, Claude Code, and LangChain patterns
        max_turns = 20  # Industry standard: 15-20 turns for most tasks
        turn = 0
        rate_limit_retries = 0  # Track 429-specific retries
        MAX_RATE_LIMIT_RETRIES = 5  # Max retries for rate limit errors

        # Repetitive action detection (sliding window)
        recent_tool_calls = []  # Track last 3 tool calls to detect loops
        recent_tool_results = []  # Track results to show user what failed
        MAX_IDENTICAL_CALLS = 3  # Terminate if same tool call repeats 3 times

        # Continuation nudges: smaller local models sometimes narrate a next step
        # ("Let me search more broadly:") without emitting the tool call, which would
        # otherwise end the turn. Nudge them to actually act, capped to avoid loops.
        continuation_nudges = 0
        MAX_CONTINUATION_NUDGES = 2

        while turn < max_turns:
            turn += 1
            self.session_logger.log_iteration(turn, max_turns)

            try:
                if self.token_callback is not None and hasattr(self.provider, "chat_streaming"):
                    response = await self.provider.chat_streaming(
                        messages=messages,
                        model=self.current_model,
                        tools=tools,
                        token_callback=self.token_callback,
                    )
                else:
                    response = await self.provider.chat(
                        messages=messages,
                        model=self.current_model,
                        tools=tools
                    )
                # Reset retry counter on successful request
                rate_limit_retries = 0

            except asyncio.CancelledError:
                # Re-raise cancellation to propagate to UI
                raise
            except Exception as e:
                error_str = str(e)

                # Handle 429 rate limit errors with automatic retry
                if "429" in error_str or "rate_limit_exceeded" in error_str:
                    rate_limit_retries += 1

                    # Check if exceeded max retries
                    if rate_limit_retries > MAX_RATE_LIMIT_RETRIES:
                        error_msg = f"X Rate limit exceeded after {MAX_RATE_LIMIT_RETRIES} retries. Please try again later."
                        self.session_logger.log_error(error_msg)
                        return error_msg

                    # Extract wait time from error message (e.g., "Please try again in 7.806s")
                    wait_match = re.search(r'try again in ([\d.]+)([ms])', error_str)
                    if wait_match:
                        wait_time = float(wait_match.group(1))
                        unit = wait_match.group(2)
                        # Convert to seconds if needed
                        if unit == 'ms':
                            wait_time = wait_time / 1000

                        # Add jitter (0-1 second randomization)
                        jitter = random.uniform(0, 1)
                        total_wait = wait_time + 0.5 + jitter

                        self.session_logger.logger.warning(
                            f"Rate limit hit (attempt {rate_limit_retries}/{MAX_RATE_LIMIT_RETRIES}), "
                            f"waiting {total_wait:.2f}s before retry"
                        )
                        await asyncio.sleep(total_wait)
                        continue  # Retry the same iteration
                    else:
                        # No wait time found, use exponential backoff with jitter
                        base_wait = min(2 ** (rate_limit_retries - 1), 60)  # Cap at 60s
                        jitter = random.uniform(0, 3)  # 0-3 second jitter
                        total_wait = base_wait + jitter

                        self.session_logger.logger.warning(
                            f"Rate limit hit (attempt {rate_limit_retries}/{MAX_RATE_LIMIT_RETRIES}), "
                            f"waiting {total_wait:.2f}s before retry"
                        )
                        await asyncio.sleep(total_wait)
                        continue  # Retry the same iteration

                error_msg = f"X API Error: {error_str}"
                self.session_logger.log_error(error_msg)
                return error_msg

            # Check if response has choices
            if not response.get("choices") or len(response["choices"]) == 0:
                error_msg = f"X Invalid API response: No choices returned\nFull response: {response}"
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
                    error_msg = f"Model returned empty response (finish_reason: {choice['finish_reason']})"
                    self.session_logger.log_error(error_msg)
                    return f"{error_msg}\nThis may indicate the model refused to respond or encountered an error."

                # The model announced a next step but didn't call a tool. Nudge it
                # to actually act instead of ending the turn (common on small local
                # models). Capped by MAX_CONTINUATION_NUDGES to prevent loops.
                if continuation_nudges < MAX_CONTINUATION_NUDGES and _looks_like_unfinished_intent(content):
                    continuation_nudges += 1
                    nudge = (
                        "You described a next step but did not call a tool. If you still "
                        "need to investigate, call the tool now (grep_files / find_files / "
                        "read_file / list_directory). If you already have enough information, "
                        "give your complete final answer now."
                    )
                    nudge_msg = {"role": "user", "content": nudge}
                    messages.append(nudge_msg)
                    self.messages.append(nudge_msg)  # keep history role-alternating
                    self.session_logger.logger.info(
                        f"Continuation nudge {continuation_nudges}/{MAX_CONTINUATION_NUDGES} "
                        "(model narrated without a tool call)"
                    )
                    continue

                # Trim in-memory messages to prevent unbounded growth
                # Keep only last 20 messages (full history is in database)
                # Reduced to prevent 429 rate limit errors in code-heavy conversations
                MAX_CONTEXT_MESSAGES = 20
                if len(self.messages) > MAX_CONTEXT_MESSAGES:
                    trimmed_count = len(self.messages) - MAX_CONTEXT_MESSAGES
                    self.messages = self.messages[-MAX_CONTEXT_MESSAGES:]
                    self.session_logger.logger.info(
                        f"Trimmed {trimmed_count} old messages from memory (retained in database)"
                    )

                # Strip thinking tags before returning
                return strip_thinking_tags(content)
            
            # Execute tool calls
            if message.get("tool_calls"):
                # Check for repetitive tool calls (loop detection)
                for tool_call in message["tool_calls"]:
                    function = tool_call["function"]
                    tool_signature = f"{function['name']}:{function['arguments']}"

                    # Add to sliding window
                    recent_tool_calls.append(tool_signature)
                    if len(recent_tool_calls) > MAX_IDENTICAL_CALLS:
                        recent_tool_calls.pop(0)  # Keep only last 3

                    # Check if all recent calls are identical
                    if len(recent_tool_calls) == MAX_IDENTICAL_CALLS and len(set(recent_tool_calls)) == 1:
                        # Get the last error message to show user what failed
                        last_result = recent_tool_results[-1][1] if recent_tool_results else "Unknown error"
                        # Truncate long error messages
                        if len(last_result) > 200:
                            last_result = last_result[:200] + "..."

                        error_msg = (
                            f"Repetitive loop detected: Same tool call repeated {MAX_IDENTICAL_CALLS} times.\n\n"
                            f"**Tool**: {function['name']}\n\n"
                            f"**What the agent tried**:\n{function['arguments']}\n\n"
                            f"**Error that kept occurring**:\n{last_result}\n\n"
                            f"The agent appears stuck trying the same operation that keeps failing.\n"
                            f"Please rephrase your request or try a different approach."
                        )
                        self.session_logger.log_error(error_msg)

                        # Add dummy tool responses to satisfy API contract
                        # This prevents "assistant message with 'tool_calls' must be followed by tool messages" error
                        for tc in message["tool_calls"]:
                            dummy_tool_message = {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": "Tool execution aborted: Repetitive loop detected"
                            }
                            self.messages.append(dummy_tool_message)
                            messages.append(dummy_tool_message)

                        return error_msg

                # Begin batching edits
                self.tools.begin_batch()

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

                    # Track tool results for loop detection
                    recent_tool_results.append((tool_name, result))
                    if len(recent_tool_results) > MAX_IDENTICAL_CALLS:
                        recent_tool_results.pop(0)

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

                # End batching - send all accumulated edits
                await self.tools.end_batch()

        error_msg = f"Max turns reached ({max_turns} turns). The task may be too complex or require human intervention."
        self.session_logger.log_error(error_msg)
        return error_msg
    
    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages.clear()
    
    def get_history(self) -> List[Message]:
        """Get conversation history."""
        return self.messages.copy()

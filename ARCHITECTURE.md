# Architecture Overview

This document provides a technical overview of Claude Clone's architecture and design decisions.

---

## System Architecture

Claude Clone follows a modular, layered architecture that separates concerns and makes the system extensible.

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Interface Layer                   │
│  (Textual UI - User Input, Display, Commands)           │
└─────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│                  Command Router/Parser                   │
│     (Parse slash commands, @-mentions, user input)      │
└─────────────────────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│                   Agent Core Engine                      │
│  - Conversation management                               │
│  - Tool orchestration                                    │
│  - Model interaction                                     │
└─────────────────────────────────────────────────────────┘
                            ▼
┌────────────────┬──────────────────┬─────────────────────┐
│  Tool Manager  │ Context Manager  │  Provider Manager   │
│  - File ops    │ - @file tracking │ - Model switching   │
│  - Bash exec   │ - Token limits   │ - API endpoints     │
│  - Code edit   │ - Smart pruning  │ - Auth headers      │
└────────────────┴──────────────────┴─────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│              LLM Provider Abstraction Layer             │
│  - OpenAI-compatible API                                │
│  - Anthropic API (planned)                              │
│  - Custom endpoints                                      │
└─────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. UI Layer (`ui/app.py`)

The UI layer is built with **Textual**, a modern TUI framework that provides a rich, interactive terminal experience.

**Responsibilities**:
- Render the chat interface
- Handle user input
- Display status information (current model, file count, token usage)
- Manage keyboard shortcuts and bindings

**Key Features**:
- Asynchronous event handling
- Rich text rendering with Markdown support
- Responsive layout that adapts to terminal size

### 2. Command Router (`commands/router.py`)

The command router parses user input and determines whether it's a slash command or a regular message.

**Responsibilities**:
- Parse slash commands (e.g., `/help`, `/model`)
- Extract `@-mentions` from messages
- Route commands to appropriate handlers

**Example**:
```python
# Input: "/model ollama-local llama3.1:8b"
command, args, original = router.parse(input)
# command = "/model"
# args = "ollama-local llama3.1:8b"

# Input: "Fix @auth.py and @utils.py"
mentions = router.extract_mentions(input)
# mentions = ["auth.py", "utils.py"]
```

### 3. Agent Core (`agent/core.py`)

The agent is the "brain" of the system. It manages the conversation, decides when to use tools, and orchestrates the interaction with the LLM.

**Responsibilities**:
- Maintain conversation history
- Call the LLM provider with appropriate context
- Handle tool calls returned by the LLM
- Execute tools and feed results back to the LLM
- Implement the agentic loop (up to 10 iterations)

**Agentic Loop**:
1. Send user message + context to LLM
2. LLM responds with text or tool calls
3. If tool calls, execute them and send results back to LLM
4. Repeat until LLM returns a final text response

### 4. Tool Manager (`agent/tools.py`)

The tool manager provides the agent with capabilities to interact with the filesystem and shell.

**Available Tools**:
- `read_file`: Read a file's contents
- `write_file`: Write content to a file
- `edit_file`: Replace text in a file
- `execute_bash`: Run a shell command
- `list_directory`: List directory contents

**Permission System**:
Each tool can request permission before execution via a callback. This allows the UI to prompt the user or auto-approve based on configuration.

### 5. Context Manager (`context/manager.py`)

The context manager handles `@file` and `@folder` mentions, loading their content into the conversation context.

**Responsibilities**:
- Load file contents when mentioned
- Track token usage to stay within limits
- Format context for inclusion in prompts

**Token Management**:
- Uses `tiktoken` to count tokens accurately
- Enforces a configurable token limit (default: 100,000)
- Prevents adding files that would exceed the limit

### 6. Provider Abstraction (`providers/`)

The provider layer abstracts different LLM APIs behind a common interface.

**Base Interface** (`base.py`):
```python
class Provider(ABC):
    async def chat(messages, model, tools, **kwargs) -> dict
    async def stream_chat(messages, model, tools, **kwargs) -> AsyncIterator
    async def list_models() -> list[str]
```

**Implementations**:
- `OpenAICompatibleProvider`: Works with OpenAI, Ollama, OpenWebUI, LM Studio, etc.
- `AnthropicProvider`: Planned for future release

**Why This Design?**:
- Easy to add new providers
- Consistent interface for the agent
- Allows runtime model switching

### 7. Configuration System (`config/`)

The configuration system uses **Pydantic** for type-safe, validated configuration.

**Schema** (`schema.py`):
- `ProviderConfig`: Configuration for a single provider
- `DefaultsConfig`: Default provider and model
- `PreferencesConfig`: User preferences
- `Config`: Top-level configuration

**Manager** (`manager.py`):
- Loads configuration from `~/.claude-clone/config.json`
- Creates default config on first run
- Provides methods to add providers and update settings

---

## Data Flow

### Example: User sends a message with @file mention

1. **User Input**: `"Add error handling to @auth.py"`

2. **Command Router**: 
   - Parses input, recognizes it's not a slash command
   - Extracts `@auth.py` mention

3. **Context Manager**:
   - Loads `auth.py` content
   - Counts tokens
   - Formats context

4. **Agent Core**:
   - Combines user message + file context
   - Sends to LLM provider

5. **LLM Provider**:
   - Calls OpenAI-compatible API
   - Returns response with tool calls (e.g., `read_file`, `edit_file`)

6. **Tool Manager**:
   - Executes `read_file` for `auth.py`
   - Requests permission for `edit_file`
   - Executes edit if approved

7. **Agent Core**:
   - Sends tool results back to LLM
   - LLM returns final response

8. **UI Layer**:
   - Displays assistant's response
   - Updates status bar

---

## Design Decisions

### Why Textual?

Textual provides a modern, rich terminal UI with minimal effort. It supports:
- Asynchronous event handling (critical for LLM streaming)
- Rich text rendering (Markdown, syntax highlighting)
- Mouse support
- Responsive layouts

**Alternative considered**: Rich (simpler but less interactive)

### Why OpenAI-Compatible API?

The OpenAI API format has become a de facto standard. By supporting it, we get compatibility with:
- Ollama
- OpenWebUI
- LM Studio
- LocalAI
- vLLM
- And many more

### Why Pydantic?

Pydantic provides:
- Type safety for configuration
- Automatic validation
- Easy serialization/deserialization
- Great error messages

### Why Async/Await?

Asynchronous programming is essential for:
- Non-blocking UI updates
- Streaming LLM responses (planned feature)
- Concurrent file operations
- Responsive user experience

---

## Extensibility Points

### Adding a New Provider

1. Create a new file in `providers/` (e.g., `anthropic.py`)
2. Implement the `Provider` interface
3. Update `providers/__init__.py` to register the provider
4. Users can now use it by adding to their config

### Adding a New Tool

1. Add a method to `Tools` class in `agent/tools.py`
2. Add the tool definition to `get_tool_definitions()`
3. Add a case in `execute_tool()`
4. The agent will automatically use it

### Adding a New Command

1. Define a handler function (e.g., `_cmd_mycommand`)
2. Register it in `_register_commands()` in `ui/app.py`
3. Users can now use `/mycommand`

---

## Future Enhancements

### Planned Features

1. **Streaming Responses**: Show LLM output as it's generated
2. **File Watching**: Auto-update context when files change
3. **LSP Integration**: Code intelligence for better edits
4. **MCP Support**: Integrate with Model Context Protocol servers
5. **Session Persistence**: Save and restore conversations
6. **Multi-Model Orchestration**: Use different models for different tasks

### Performance Optimizations

1. **Caching**: Cache file contents and token counts
2. **Parallel Tool Execution**: Run independent tools concurrently
3. **Smart Context Pruning**: Remove less relevant files when approaching token limits
4. **Response Streaming**: Stream LLM responses for faster perceived performance

---

## Testing Strategy

### Current Tests

- **Import Tests**: Verify all modules can be imported
- **Config Tests**: Ensure configuration loads correctly
- **Context Manager Tests**: Token counting and file management
- **Tool Tests**: File operations work as expected
- **Command Router Tests**: Parsing and mention extraction

### Planned Tests

- **Integration Tests**: End-to-end workflows
- **Provider Tests**: Mock LLM responses
- **UI Tests**: Textual provides testing utilities
- **Performance Tests**: Token counting speed, file loading

---

## Security Considerations

### File Access

The agent has full access to the filesystem. Mitigations:
- Permission callback system
- `auto_approve` setting (default: false)
- Run in Docker with volume mounts to restrict access

### Command Execution

The `execute_bash` tool can run arbitrary commands. Mitigations:
- Always request permission
- Display command before execution
- Consider sandboxing (future enhancement)

### API Keys

API keys are stored in plaintext in the config file. Mitigations:
- Config file has restricted permissions (600)
- Support environment variables (planned)
- Consider encrypted storage (future enhancement)

---

## Dependencies

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `textual` | Terminal UI framework |
| `pydantic` | Configuration and validation |
| `openai` | OpenAI-compatible API client |
| `aiofiles` | Async file I/O |
| `tiktoken` | Token counting |
| `click` | CLI argument parsing |
| `rich` | Text formatting |

### Optional Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Anthropic Claude API |
| `watchdog` | File system monitoring |
| `tree-sitter` | Code parsing (planned) |

---

## Conclusion

Claude Clone is designed to be modular, extensible, and easy to understand. Each component has a clear responsibility, and the architecture supports adding new features without major refactoring.

For more details on specific components, see the inline documentation in the source code.

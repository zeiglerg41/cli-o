# Claude Clone

**Claude Clone** provides a robust, self-contained AI coding helper that operates in your terminal. It replicates the abilities of sophisticated AI helpers similar to Claude, enabling you to integrate your own models, link with any OpenAI-compatible API, and engage effortlessly with your local file system.

Developed with Python and leveraging the **Textual** framework for the user interface, this project ensures a vibrant, engaging experience directly within your terminal.

![Chat Interface](https://user-images.githubusercontent.com/1234/claude-clone-demo.png) <!--- Placeholder for a future screenshot -->

---

## Features

- **Interactive Terminal UI**: A modern, mouse-aware, and colorful interface powered by Textual.
- **Dynamic Model Switching**: Switch between different AI models and providers on the fly with the `/model` command.
- **Bring Your Own Provider**: Connect to any OpenAI-compatible endpoint, including local models via Ollama, OpenWebUI, or any other service.
- **Full Filesystem Context**: Reference files and folders using `@-mentions` (e.g., `Refactor @my_script.py`) to pull their content directly into the conversation.
- **Agentic Tool Use**: The AI can read, write, and edit files, as well as execute shell commands, after asking for your permission.
- **Slash Commands**: A simple command system for managing the application (e.g., `/help`, `/config`, `/files`).
- **Dockerized Deployment**: Run the application in a container for a clean, isolated, and reproducible environment.
- **Extensible Architecture**: Built with a provider abstraction layer, making it easy to add support for new APIs like Anthropic or Gemini.

---

## How It Works

The application is designed with a modular architecture:

1.  **CLI Interface (Textual)**: The user-facing component that handles input, renders the chat, and manages the display.
2.  **Command Router**: Parses user input to distinguish between regular chat messages and slash commands (e.g., `/model`).
3.  **Agent Core**: The central "brain" that orchestrates the workflow. It takes user prompts, manages conversation history, and decides when to use tools.
4.  **Tool Manager**: Provides the agent with capabilities to interact with the outside world, such as reading files (`read_file`) or executing commands (`execute_bash`).
5.  **Context Manager**: Manages the files and folders mentioned with `@` syntax, loading their content into the conversation context for the AI.
6.  **Provider Abstraction Layer**: A set of adapters that allow the agent to communicate with various AI model providers (e.g., OpenAI, Ollama) through a unified interface.
7.  **Configuration System**: A Pydantic-based system that loads and saves settings from a JSON file, allowing you to configure providers, models, and preferences.

---

## Installation and Setup

### Quick Install (PyPI)

The easiest way to install Clio:

```bash
# Install with pipx (recommended - isolated environment)
pipx install clio-ai

# Or with pip
pip install clio-ai

# Run it
clio
```

### Docker (Recommended for Development)

This is the easiest way to get started. It ensures all dependencies are handled in an isolated environment.

**Prerequisites**:
- Docker and Docker Compose must be installed.

**Steps**:

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/claude-clone.git
    cd claude-clone
    ```

2.  **Run the wrapper script**:
    A convenient wrapper script `./mimic` is provided to handle building the Docker image and running the container.
    ```bash
    ./mimic
    ```
    The first time you run this, it will build the Docker image, which may take a few minutes. Subsequent runs will be much faster.

    You can now move the `mimic` script to a directory in your `$PATH` (e.g., `/usr/local/bin`) to run it from anywhere:
    ```bash
    sudo mv ./mimic /usr/local/bin/mimic
    ```

### Local Installation

If you prefer to run the application directly on your host machine.

**Prerequisites**:
- Python 3.11+

**Steps**:

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/claude-clone.git
    cd claude-clone
    ```

2.  **Run the installation script**:
    This script will install the project and its dependencies in editable mode.
    ```bash
    chmod +x install.sh
    ./install.sh
    ```

3.  **Run the application**:
    ```bash
    claude-clone
    ```

---

## Usage

Once running, you will be greeted by the interactive chat interface.

- **Chat**: Simply type your message and press `Enter`.
- **Commands**: Type a slash command like `/help` and press `Enter`.
- **Context**: Mention a file with `@path/to/file.py` in your message to add it to the conversation context.

### Configuration

The configuration is stored in `~/.claude-clone/config.json`. When using Docker, this directory is mounted from the `config/` folder in the project root.

The default configuration is set up to use a local Ollama instance. If you have Ollama running, it should work out of the box.

**Default `config.json`**:
```json
{
  "providers": {
    "ollama-local": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:11434/v1",
      "models": [
        "llama3.1:8b",
        "qwen2.5:7b",
        "mistral:7b"
      ]
    }
  },
  "defaults": {
    "provider": "ollama-local",
    "model": "llama3.1:8b"
  },
  "preferences": {
    "auto_approve": false
  }
}
```

**Supported Providers:**
- `openai` - OpenAI official API
- `anthropic` - Anthropic Claude API
- `gemini` - Google Gemini API
- `deepseek` - DeepSeek official API
- `grok` - xAI Grok API
- `openai-compatible` - Any provider using OpenAI's API format:
  - Self-hosted: Ollama, LM Studio, vLLM, text-generation-webui
  - Third-party APIs: Groq, Together AI, Fireworks, Anyscale

To add a new provider, use the `add-provider` command or edit the JSON file directly.

---

## Commands

| Command           | Description                                       |
|-------------------|---------------------------------------------------|
| `/help`           | Shows the help message with all available commands. |
| `/model`          | Lists available models and providers.               |
| `/model <p> <m>`  | Switches to a different model and provider.         |
| `/files`          | Lists all files currently in the context.         |
| `/add <path>`     | Adds a file or all files in a folder to the context.|
| `/remove <path>`  | Removes a file from the context.                  |
| `/clear`          | Clears the current conversation history.          |
| `/config`         | Displays the current configuration.               |
| `/exit`           | Exits the application.                            |

---

## Architecture Decisions

### Context Management: Hybrid Approach

**Strategy**: Clio uses 4 complementary techniques to manage conversation context efficiently while maintaining relevance:

**1. Sliding Window** (`core.py:500-535`)
- Keep last 20 messages in active context (10 user/assistant pairs)
- Token estimation with tiktoken (15k token limit)
- Prevents unbounded context growth

**2. RAG - Retrieval-Augmented Generation** (`rag/retriever.py`)
- Semantic search retrieves 10 most relevant older messages (when conversation > 20 messages)
- Uses `all-MiniLM-L6-v2` embeddings (384-dim) + ChromaDB vector store
- Excludes last 20 messages (already in sliding window)
- Maintains access to distant context beyond window

**3. Tool Message Validation** (`core.py:537-566`)
- Ensures tool messages properly correspond to each `tool_call_id`
- Strict validation: Only valid, new tool outputs are sent to the LLM
- Prevents redundant or out-of-order tool messages from reaching the context (replaces old observation masking)

**4. In-Memory Trimming** (`core.py:715-724`)
- Trim in-memory message list to last 20 after each turn
- Full history persisted to SQLite + ChromaDB (async)
- Prevents memory bloat in long sessions

**5. Turn-Based Execution** (`core.py:579-826`)
- Turn = one LLM call + all tool executions in that response
- Max 20 turns per query (following OpenAI SDK / Claude Code patterns)
- Tool executions within a turn don't count separately
- Prevents premature timeout on legitimate multi-step tasks

**Flow**:
```
Load last 20 messages → RAG retrieve 10 relevant older messages (if needed)
→ Apply observation masking → Token estimation → Send to LLM
→ Trim in-memory to 20 → Save all to DB/vector store
```

This hybrid approach combines recency bias, semantic relevance, token efficiency, and memory efficiency—similar to patterns in LangChain and LlamaIndex.

### Error Recovery: Orphaned Tool Calls

**Problem**: When the agent detects repetitive loops and aborts execution, it leaves orphaned `tool_calls` in the conversation history without corresponding tool response messages. This violates the OpenAI API contract, causing 400 errors: "An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'."

**Solution**: Before returning loop detection errors, add dummy tool response messages for all pending `tool_call_id`s to maintain valid conversation state.

**Implementation** (`src/clio/agent/core.py:771-780`):
```python
# Add dummy tool responses to satisfy API contract
for tc in message["tool_calls"]:
    dummy_tool_message = {
        "role": "tool",
        "tool_call_id": tc["id"],
        "content": "Tool execution aborted: Repetitive loop detected"
    }
    self.messages.append(dummy_tool_message)
```

**Sources**:
- [Portkey.ai Error Library](https://portkey.ai/error-library/tool-call-response-error-10067): "For every tool_call_id in your assistant message, there is a corresponding tool message"
- [joseferben.com](https://www.joseferben.com/posts/openai-tool-calls-must-be-followed-by-tool-messages): "The tool call result message must come right after the tool calls message"
- [ZenML Agent Best Practices](https://www.zenml.io/blog/llm-agents-in-production-architectures-challenges-and-best-practices): "Centralized orchestration tracks global states and implements fallback strategies"

### UTF-8 Encoding: Emoji Handling

**Problem**: The `unicode_escape` decoding in `write_file` and `edit_file` corrupted UTF-8 emojis when the LLM generated proper Unicode characters, transforming `🌙` into mangled bytes like `ð`.

**Solution**: Removed `unicode_escape` decoding and rely solely on explicit `encoding='utf-8'` parameter in file operations, as UTF-8 natively handles emojis without escape sequence processing.

**Implementation** (`src/clio/agent/tools.py`):
```python
# Write file with explicit UTF-8 encoding to preserve emojis and Unicode
async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
    await f.write(content)
```

**Sources**:
- [Python Unicode HOWTO](https://docs.python.org/3/howto/unicode.html): "Always explicitly specify `encoding='utf-8'` when opening files"
- [OpenAI Community](https://community.openai.com/t/gpt-4-1106-preview-messes-up-function-call-parameters-encoding/478500): GPT-4 variants have documented UTF-8 encoding issues in tool call parameters
- [Compile7](https://compile7.org/character-encoding-decoding/how-to-handle-character-encoding-with-utf-8-in-python/): "UTF-8 encoding handles emojis natively - explicit parameter prevents data corruption"

---

## Development

Contributions are welcome! To set up a development environment:

1.  Clone the repository.
2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
3.  Install the project with development dependencies:
    ```bash
    pip install -e ".[dev]"
    ```
4.  Run tests:
    ```bash
    pytest
    ```

### VS Code Extension Development

The project includes a VS Code/Cursor extension for IDE integration with inline diff previews and CodeLens accept/reject buttons.

**Location**: `clio-vscode/`

**Setup**:
```bash
cd clio-vscode
npm install
npm run compile
```

**Development workflow** (when extension is already installed):

If the extension is already installed at `~/.cursor/extensions/clio.clio-vscode-0.1.0/` or `~/.vscode/extensions/clio.clio-vscode-0.1.0/`, you need to copy compiled files after making changes:

```bash
# After making changes to TypeScript files
npm run compile
cp dist/extension.js* ~/.cursor/extensions/clio.clio-vscode-0.1.0/dist/

# Then reload the window
# Command Palette → Developer: Reload Window
```

**Why?** The IDE runs the extension from the installed location, not your development directory.

**See `clio-vscode/README.md` for full documentation.**

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

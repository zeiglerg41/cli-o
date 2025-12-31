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

You can run Claude Clone either using Docker (recommended for a clean setup) or by installing it locally with Python.

### Docker (Recommended)

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

To add a new provider (e.g., a remote OpenAI-compatible API), you can use the `add-provider` command or edit the JSON file directly.

### Getting Actual Billing Data

By default, the `/usage` command shows accurate token counts but **estimated costs** based on published pricing. To get **actual billing amounts** from your provider:

#### For OpenAI

1. **Get an Admin API Key**:
   - Go to https://platform.openai.com/api-keys
   - Create a new key with "Admin" permissions
   - Copy the key (starts with `sk-proj-...`)

2. **Add to your config** at `~/.clio/config.json`:
   ```json
   {
     "providers": {
       "openai": {
         "type": "openai",
         "baseURL": "https://api.openai.com/v1",
         "apiKey": "sk-proj-YOUR-REGULAR-KEY-HERE",
         "adminApiKey": "sk-proj-YOUR-ADMIN-KEY-HERE",
         "models": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
       }
     }
   }
   ```

3. **Reload clio** - The `/usage` command will now fetch actual costs from OpenAI's billing API.

#### For Anthropic (Claude)

1. **Get an Admin API Key**:
   - Go to https://console.anthropic.com/settings/keys
   - Create a new key with Admin role
   - Copy the key (starts with `sk-ant-admin-...`)

2. **Add to your config**:
   ```json
   {
     "providers": {
       "anthropic": {
         "type": "anthropic",
         "baseURL": "https://api.anthropic.com/v1",
         "apiKey": "sk-ant-YOUR-REGULAR-KEY",
         "adminApiKey": "sk-ant-admin-YOUR-ADMIN-KEY",
         "models": ["claude-3-opus", "claude-3-sonnet"]
       }
     }
   }
   ```

3. **Reload clio** - The `/usage` command will now show actual billing data.

**Note**: Admin API keys have elevated permissions. Store them securely and never commit them to version control.

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

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

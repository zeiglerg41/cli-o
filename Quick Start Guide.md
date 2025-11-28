# Quick Start Guide

Get Claude Clone up and running in 5 minutes.

---

## Option 1: Docker (Easiest)

**Prerequisites**: Docker installed on your system.

```bash
# Clone the repository
git clone https://github.com/your-username/claude-clone.git
cd claude-clone

# Run the wrapper script (builds image on first run)
./mimic

# Optional: Install globally
sudo cp mimic /usr/local/bin/mimic
```

That's it! You're now in the Claude Clone interface.

---

## Option 2: Local Installation

**Prerequisites**: Python 3.11+

```bash
# Clone the repository
git clone https://github.com/your-username/claude-clone.git
cd claude-clone

# Run the install script
./install.sh

# Activate virtual environment
source .venv/bin/activate

# Start the application
claude-clone
```

---

## First Steps

Once the application is running:

1. **Type `/help`** to see available commands
2. **Try a simple message**: `Hello! Can you help me?`
3. **Add a file to context**: `/add myfile.py` or mention it with `@myfile.py`
4. **List available models**: `/model`

---

## Configuring for Ollama (Local Models)

If you have Ollama running locally, Claude Clone works out of the box!

1. **Ensure Ollama is running**:
   ```bash
   ollama serve
   ```

2. **Pull a model** (if you haven't already):
   ```bash
   ollama pull llama3.1:8b
   ```

3. **Start Claude Clone**:
   ```bash
   ./mimic  # or claude-clone if installed locally
   ```

4. **Start chatting!**

---

## Configuring for OpenAI

To use OpenAI's models:

1. **Add your API key** to the config:
   ```bash
   # Edit the config file
   nano ~/.claude-clone/config.json
   ```

2. **Add OpenAI provider**:
   ```json
   {
     "providers": {
       "openai": {
         "type": "openai",
         "apiKey": "sk-your-api-key-here",
         "models": ["gpt-4o", "gpt-4o-mini"]
       }
     },
     "defaults": {
       "provider": "openai",
       "model": "gpt-4o-mini"
     }
   }
   ```

3. **Restart Claude Clone**

---

## Common Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/model` | List/switch models |
| `/files` | Show files in context |
| `/add <path>` | Add file to context |
| `/clear` | Clear conversation |
| `/exit` | Exit |

---

## Example Workflow

```
You: /add src/main.py

System: ✓ Added src/main.py (245 tokens)

You: Add error handling to the login function


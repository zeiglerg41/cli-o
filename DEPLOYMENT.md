# Deployment Guide

This guide covers different deployment scenarios for Claude Clone.

---

## Docker Deployment (Recommended)

Docker provides the cleanest and most reproducible deployment method.

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Quick Start

1. **Build and run with the wrapper script**:
   ```bash
   ./mimic
   ```

   This script automatically builds the image on first run and starts an interactive session.

2. **Install globally** (optional):
   ```bash
   sudo cp mimic /usr/local/bin/mimic
   ```

   Now you can run `mimic` from anywhere on your system.

### Using Docker Compose Directly

For more control, you can use Docker Compose commands directly:

```bash
# Build the image
docker-compose build

# Run interactively
docker-compose run --rm claude-clone

# Run with a specific command
docker-compose run --rm claude-clone setup
```

### Configuration with Docker

Configuration is stored in the `config/` directory in the project root, which is mounted into the container at `/root/.claude-clone`.

To customize your configuration:

1. Run setup to create the default config:
   ```bash
   ./mimic setup
   ```

2. Edit the config file:
   ```bash
   nano config/config.json
   ```

3. Start the application:
   ```bash
   ./mimic
   ```

### Accessing Local Services (e.g., Ollama)

The Docker Compose configuration uses `network_mode: host`, which allows the container to access services running on your host machine (like Ollama on `localhost:11434`).

If you prefer not to use host networking, you can:

1. Remove the `network_mode: host` line from `docker-compose.yml`
2. Update your config to use `host.docker.internal` instead of `localhost`:
   ```json
   {
     "providers": {
       "ollama-local": {
         "baseURL": "http://host.docker.internal:11434/v1"
       }
     }
   }
   ```

---

## Local Installation

For development or if you prefer to run directly on your host.

### Prerequisites

- Python 3.11 or higher
- pip

### Installation Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-username/claude-clone.git
   cd claude-clone
   ```

2. **Run the install script**:
   ```bash
   ./install.sh
   ```

   This creates a virtual environment and installs all dependencies.

3. **Activate the virtual environment**:
   ```bash
   source .venv/bin/activate
   ```

4. **Run the application**:
   ```bash
   claude-clone
   ```

### Manual Installation

If you prefer to install manually:

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Run
claude-clone
```

---

## Configuration

### Default Configuration

On first run, Claude Clone creates a default configuration at `~/.claude-clone/config.json`:

```json
{
  "providers": {
    "ollama-local": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:11434/v1",
      "models": ["llama3.1:8b", "qwen2.5:7b", "mistral:7b"]
    }
  },
  "defaults": {
    "provider": "ollama-local",
    "model": "llama3.1:8b"
  },
  "preferences": {
    "auto_approve": false,
    "context_window": 16384,
    "theme": "dark",
    "show_thinking": true
  }
}
```

### Adding Providers

#### Via CLI

```bash
claude-clone add-provider openai-remote \
  --url https://api.openai.com/v1 \
  --api-key sk-your-key-here \
  --type openai
```

#### Via Config File

Edit `~/.claude-clone/config.json` and add a new provider:

```json
{
  "providers": {
    "openai": {
      "type": "openai",
      "baseURL": "https://api.openai.com/v1",
      "apiKey": "sk-your-key-here",
      "models": ["gpt-4o", "gpt-4o-mini"]
    }
  }
}
```

### Provider Types

- **`openai-compatible`**: Works with any OpenAI-compatible API (Ollama, OpenWebUI, LM Studio, etc.)
- **`openai`**: Official OpenAI API
- **`anthropic`**: Anthropic Claude API (not yet implemented)

### Example Configurations

#### Local Ollama

```json
{
  "providers": {
    "ollama": {
      "type": "openai-compatible",
      "baseURL": "http://localhost:11434/v1",
      "models": ["llama3.1:8b", "qwen2.5:7b"]
    }
  }
}
```

#### Remote OpenWebUI

```json
{
  "providers": {
    "openwebui": {
      "type": "openai-compatible",
      "baseURL": "https://your-openwebui.com/api",
      "headers": {
        "Authorization": "Bearer your-api-key"
      },
      "models": ["llama3.1:8b"]
    }
  }
}
```

#### OpenAI

```json
{
  "providers": {
    "openai": {
      "type": "openai",
      "apiKey": "sk-your-key",
      "models": ["gpt-4o", "gpt-4o-mini"]
    }
  }
}
```

---

## Troubleshooting

### "Connection refused" when connecting to Ollama

- Ensure Ollama is running: `ollama serve`
- If using Docker, ensure `network_mode: host` is set in `docker-compose.yml`
- Alternatively, use `host.docker.internal` instead of `localhost`

### "Module not found" errors

- Ensure you're in the virtual environment: `source .venv/bin/activate`
- Reinstall dependencies: `pip install -e .`

### UI not rendering correctly

- Ensure your terminal supports 256 colors
- Try a different terminal emulator (e.g., iTerm2, Windows Terminal)
- Update Textual: `pip install --upgrade textual`

### Permission denied errors

- For Docker: Ensure Docker daemon is running and you have permissions
- For local: Ensure you have write access to `~/.claude-clone`

---

## Advanced Usage

### Running with Environment Variables

You can override configuration with environment variables:

```bash
export OPENAI_API_KEY=sk-your-key
claude-clone
```

### Custom Config Path

```bash
claude-clone --config /path/to/custom/config.json
```

(Note: This feature is not yet implemented but is planned)

### Running in CI/CD

For automated testing or CI/CD pipelines:

```bash
# Non-interactive mode (planned feature)
echo "List files in src/" | claude-clone --non-interactive
```

---

## Production Deployment

For production use cases (e.g., running as a service):

### Systemd Service (Linux)

Create `/etc/systemd/system/claude-clone.service`:

```ini
[Unit]
Description=Claude Clone AI Assistant
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/claude-clone
ExecStart=/home/your-user/claude-clone/.venv/bin/claude-clone
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable claude-clone
sudo systemctl start claude-clone
```

### Docker Compose with Restart Policy

Update `docker-compose.yml`:

```yaml
services:
  claude-clone:
    restart: unless-stopped
    # ... rest of config
```

---

## Security Considerations

1. **API Keys**: Never commit API keys to version control. Use environment variables or a `.env` file.
2. **File Access**: The agent can read and write files. Run it in a restricted directory or use Docker volumes.
3. **Command Execution**: The agent can execute shell commands. Review the `auto_approve` setting carefully.
4. **Network Access**: If running in Docker with `network_mode: host`, the container has full network access.

---

## Next Steps

- Read the [README.md](README.md) for usage instructions
- Check out the [BUILD_SPEC.md](BUILD_SPEC.md) for architecture details
- Report issues on GitHub

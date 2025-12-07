# Clio VS Code Extension

A VS Code extension that integrates with the `clio` CLI tool to provide Claude Code-like diff previews and real-time file editing.

## Features

- **Chat Interface**: Interactive chat panel to communicate with Clio AI assistant
- **Real-time Edits**: Automatically apply code changes suggested by Clio
- **Diff Visualization**: See changes with color-coded gutter decorations
  - 🟢 Green: Additions
  - 🔵 Blue: Modifications
  - 🔴 Red: Deletions
- **Status Bar Integration**: Monitor Clio's activity status
- **Multi-file Support**: Handle edits across multiple files simultaneously

## Prerequisites

- VS Code version 1.85.0 or higher
- `clio` CLI tool installed and available in your PATH

## Installation

### From Source

1. Clone this repository
2. Install dependencies:
   ```bash
   cd clio-vscode
   npm install
   ```
3. Compile the extension:
   ```bash
   npm run compile
   ```
4. Press `F5` in VS Code to launch the Extension Development Host

### From VSIX Package

1. Build the package:
   ```bash
   npm run package
   npx vsce package
   ```
2. Install the `.vsix` file in VS Code:
   - Open VS Code
   - Go to Extensions view
   - Click "..." menu → "Install from VSIX..."
   - Select the generated `.vsix` file

## Usage

1. **Start a Session**
   - Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`)
   - Run command: `Clio: Start Session`
   - The chat panel will open on the right side

2. **Chat with Clio**
   - Type your request in the input box
   - Press Enter or click "Send"
   - Clio will respond and may suggest code changes

3. **Review Changes**
   - When Clio suggests edits, you'll see gutter decorations
   - Changes are automatically applied to your files
   - Files will show as modified (unsaved) in VS Code

4. **Stop a Session**
   - Run command: `Clio: Stop Session`
   - Or close VS Code (the process will be terminated automatically)

## Architecture

### Core Components

- **ClioClient**: Manages the `clio` CLI process and handles JSON communication
- **DiffProvider**: Creates visual decorations for code changes
- **EditApplier**: Applies edits to workspace documents using VS Code's API
- **ChatPanel**: Webview-based chat interface
- **StatusBar**: Shows Clio's current status

### Message Protocol

The extension communicates with `clio` via JSON messages over stdin/stdout:

```typescript
// Edit message from clio
{
  "type": "edit",
  "file": "/path/to/file.ts",
  "edits": [{
    "range": {
      "start": { "line": 10, "character": 0 },
      "end": { "line": 10, "character": 20 }
    },
    "newText": "const result = calculate();"
  }]
}

// Response message from clio
{
  "type": "response",
  "content": "I've updated the calculate function to handle edge cases."
}

// Status message from clio
{
  "type": "status",
  "activity": "Analyzing code..."
}
```

## Development

### Project Structure

```
clio-vscode/
├── package.json              # Extension manifest
├── tsconfig.json            # TypeScript configuration
├── webpack.config.js        # Webpack bundling configuration
├── src/
│   ├── extension.ts         # Main entry point
│   ├── clioClient.ts        # Clio process management
│   ├── diffProvider.ts      # Diff visualization
│   ├── editApplier.ts       # Edit application logic
│   ├── statusBar.ts         # Status bar integration
│   └── webview/
│       ├── chatPanel.ts     # Webview controller
│       └── chatPanel.html   # Chat UI
└── dist/                    # Compiled output
```

### Scripts

- `npm run compile` - Compile TypeScript with webpack
- `npm run watch` - Watch mode for development
- `npm run package` - Build production bundle

### Testing

1. Press `F5` to launch Extension Development Host
2. Open a workspace with code files
3. Run `Clio: Start Session`
4. Test various scenarios:
   - Send messages
   - Verify edits are applied
   - Check gutter decorations
   - Monitor status updates

## Troubleshooting

### "Failed to start Clio" Error

- Ensure `clio` is installed: `which clio` (Unix) or `where clio` (Windows)
- Check that `clio --vscode` runs without errors
- Verify `clio` supports the `--vscode` flag

### Chat Panel Not Opening

- Check the Output panel (View → Output → Clio) for errors
- Try reloading the window (`Ctrl+R` or `Cmd+R`)

### Edits Not Applying

- Ensure the file paths from `clio` are correct
- Check file permissions
- Look for errors in the Debug Console

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Credits

Built with inspiration from Claude Code and other AI coding assistants.

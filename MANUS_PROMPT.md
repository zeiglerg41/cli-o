# Manus AI Prompt - Clio VS Code Extension (Complete)

Build a complete VS Code extension called "clio-vscode" that integrates with the clio CLI tool to provide Claude Code-like diff previews and real-time file editing.

## Project Setup
- Use TypeScript + webpack
- Generate initial scaffold with proper package.json
- Extension activation: on command "Clio: Start Session"
- Target VS Code API version: ^1.85.0

## Architecture

### 1. Core Files Structure
```
clio-vscode/
├── package.json
├── tsconfig.json
├── webpack.config.js
├── src/
│   ├── extension.ts           # Main entry point
│   ├── clioClient.ts          # Manages clio process
│   ├── diffProvider.ts        # Handles diff visualization
│   ├── editApplier.ts         # Applies edits with WorkspaceEdit
│   ├── statusBar.ts           # Status bar integration
│   └── webview/
│       ├── chatPanel.ts       # Webview panel controller
│       └── chatPanel.html     # Chat UI HTML
```

### 2. ClioClient (clioClient.ts)
**Responsibilities:**
- Spawn clio CLI as child process: `spawn('clio', ['--vscode'], {stdio: ['pipe', 'pipe', 'pipe']})`
- Parse JSON messages from stdout
- Send JSON messages to stdin
- Emit events: 'edit', 'response', 'status', 'error'

**Interface:**
```typescript
interface ClioClient {
  start(): Promise<void>;
  sendMessage(content: string): void;
  on(event: 'edit', callback: (msg: EditMessage) => void): void;
  on(event: 'response', callback: (msg: ResponseMessage) => void): void;
  stop(): void;
}
```

### 3. Message Protocol
```typescript
interface EditMessage {
  type: 'edit';
  file: string;
  edits: Array<{
    range: { start: { line: number, character: number }, end: { line: number, character: number } };
    newText: string;
  }>;
}

interface ResponseMessage {
  type: 'response';
  content: string;
}

interface StatusMessage {
  type: 'status';
  activity: string;
}
```

### 4. DiffProvider (diffProvider.ts)
**Responsibilities:**
- Create gutter decorations for changed lines (green for additions, red for deletions, blue for modifications)
- Show inline diff view when gutter decoration is clicked
- Track pending edits before user accepts/rejects

**Key Methods:**
```typescript
class DiffProvider {
  showPendingEdit(edit: EditMessage): void;
  applyGutterDecorations(document: TextDocument, edits: Edit[]): void;
  showInlineDiff(document: TextDocument, edit: Edit): void;
  clearDecorations(): void;
}
```

**Use:**
- `vscode.window.createTextEditorDecorationType()` for gutter indicators
- Custom decoration with `gutterIconPath`, `backgroundColor`
- Add click handler that opens inline diff

### 5. EditApplier (editApplier.ts)
**Responsibilities:**
- Convert EditMessage to VS Code WorkspaceEdit
- Apply edits to document buffers
- Handle accept/reject workflow

**Key Methods:**
```typescript
class EditApplier {
  async applyEdit(edit: EditMessage): Promise<void> {
    const workspaceEdit = new vscode.WorkspaceEdit();
    const uri = vscode.Uri.file(edit.file);

    for (const e of edit.edits) {
      const range = new vscode.Range(
        new vscode.Position(e.range.start.line, e.range.start.character),
        new vscode.Position(e.range.end.line, e.range.end.character)
      );
      workspaceEdit.replace(uri, range, e.newText);
    }

    await vscode.workspace.applyEdit(workspaceEdit);
  }
}
```

### 6. ChatPanel (webview/chatPanel.ts)
**Responsibilities:**
- Create webview panel with chat UI
- Handle user input
- Display clio responses
- Show tool execution notifications

**HTML UI (chatPanel.html):**
```html
<!DOCTYPE html>
<html>
<head>
  <style>
    #messages { height: 500px; overflow-y: auto; padding: 10px; }
    .user-message { background: #007acc; color: white; padding: 8px; margin: 4px; border-radius: 4px; }
    .assistant-message { background: #333; color: white; padding: 8px; margin: 4px; border-radius: 4px; }
    .tool-message { background: #f0ad4e; color: black; padding: 8px; margin: 4px; border-radius: 4px; }
    #input { width: 100%; padding: 8px; }
  </style>
</head>
<body>
  <div id="messages"></div>
  <input id="input" type="text" placeholder="Ask clio..."/>
  <script>
    const vscode = acquireVsCodeApi();
    const input = document.getElementById('input');
    const messages = document.getElementById('messages');

    input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        vscode.postMessage({ command: 'sendMessage', text: input.value });
        addMessage('user', input.value);
        input.value = '';
      }
    });

    window.addEventListener('message', (e) => {
      const message = e.data;
      if (message.type === 'response') {
        addMessage('assistant', message.content);
      } else if (message.type === 'tool') {
        addMessage('tool', `🔧 ${message.tool}: ${message.result}`);
      }
    });

    function addMessage(type, content) {
      const div = document.createElement('div');
      div.className = type + '-message';
      div.textContent = content;
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }
  </script>
</body>
</html>
```

### 7. Extension Activation (extension.ts)
```typescript
export function activate(context: vscode.ExtensionContext) {
  const clioClient = new ClioClient();
  const diffProvider = new DiffProvider();
  const editApplier = new EditApplier();
  let chatPanel: ChatPanel | undefined;

  // Register command
  const disposable = vscode.commands.registerCommand('clio.startSession', async () => {
    // Start clio process
    await clioClient.start();

    // Create chat panel
    chatPanel = new ChatPanel(context.extensionUri);

    // Handle messages from webview
    chatPanel.onMessage((msg) => {
      if (msg.command === 'sendMessage') {
        clioClient.sendMessage(msg.text);
      }
    });
  });

  // Listen for edits from clio
  clioClient.on('edit', (editMsg) => {
    diffProvider.showPendingEdit(editMsg);
    // For now, auto-accept edits (add accept/reject UI later)
    editApplier.applyEdit(editMsg);
  });

  // Listen for responses
  clioClient.on('response', (respMsg) => {
    chatPanel?.postMessage({ type: 'response', content: respMsg.content });
  });

  context.subscriptions.push(disposable);
}
```

### 8. Package.json
```json
{
  "name": "clio-vscode",
  "displayName": "Clio",
  "description": "VS Code integration for clio AI coding assistant",
  "version": "0.1.0",
  "engines": {
    "vscode": "^1.85.0"
  },
  "categories": ["Other"],
  "activationEvents": ["onCommand:clio.startSession"],
  "main": "./dist/extension.js",
  "contributes": {
    "commands": [
      {
        "command": "clio.startSession",
        "title": "Clio: Start Session"
      }
    ]
  },
  "scripts": {
    "vscode:prepublish": "npm run package",
    "compile": "webpack",
    "watch": "webpack --watch",
    "package": "webpack --mode production --devtool hidden-source-map"
  },
  "devDependencies": {
    "@types/vscode": "^1.85.0",
    "@types/node": "18.x",
    "@typescript-eslint/eslint-plugin": "^6.15.0",
    "@typescript-eslint/parser": "^6.15.0",
    "eslint": "^8.56.0",
    "typescript": "^5.3.3",
    "webpack": "^5.89.0",
    "webpack-cli": "^5.1.4",
    "ts-loader": "^9.5.1"
  }
}
```

## Expected Behavior

1. User runs "Clio: Start Session" command
2. Extension spawns clio CLI process
3. Chat panel opens in VS Code sidebar
4. User types: "Fix the add() function in calculator.py"
5. Clio processes request and emits edit message via stdout
6. Extension receives edit message
7. Green gutter indicator appears on modified line
8. User clicks indicator → sees inline diff
9. Edit is applied to buffer automatically
10. File shows as modified in VS Code (unsaved)

## Important Details

- **Error Handling**: Wrap all stdio operations in try/catch, handle process crashes gracefully
- **Process Cleanup**: Kill clio process when extension deactivates
- **Path Resolution**: Handle both absolute and relative file paths from clio
- **Multi-file Edits**: Support edits to multiple files in single message
- **Decoration Lifecycle**: Clear decorations after edits are applied
- **Webview State**: Persist chat history across webview reloads

## Testing Checklist
- [ ] Extension activates without errors
- [ ] Clio process spawns successfully
- [ ] Chat panel opens and accepts input
- [ ] Messages sent to clio via stdin
- [ ] Responses received from clio via stdout
- [ ] EditMessage properly parsed
- [ ] WorkspaceEdit applies changes to document
- [ ] Gutter decorations appear
- [ ] No memory leaks on process restart

## Build and Run
```bash
cd clio-vscode
npm install
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```

Generate the complete extension following this specification. Include all files, proper TypeScript types, error handling, and comments explaining key sections.

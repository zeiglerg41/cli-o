# Clio VS Code Extension - Development Plan

## Goal
Build a VS Code extension that provides Claude Code-like diff preview and real-time file editing for clio.

## Architecture

### Communication Layer
- **Extension ↔ Clio**: Use stdio to communicate with clio CLI process
- **Protocol**: JSON-RPC or simple JSON messages over stdin/stdout
- **Process Management**: Spawn clio as child process, maintain connection

### Core Components

#### 1. Extension Host (TypeScript)
```
src/
├── extension.ts          # Main activation point
├── clioClient.ts         # Manages clio process communication
├── diffProvider.ts       # Shows diffs in VS Code UI
├── editApplier.ts        # Applies edits using WorkspaceEdit API
└── statusBar.ts          # Shows clio status/activity
```

#### 2. Clio Backend Modifications
```
src/clio/
├── vscode_protocol.py    # JSON-RPC message handling
├── vscode_mode.py        # VS Code-specific agent mode
└── agent/
    └── vscode_tools.py   # Tools that emit edit messages
```

## Implementation Phases

### Phase 1: Basic Extension
- [ ] Set up extension scaffold with `yo code`
- [ ] Spawn clio process and establish stdio communication
- [ ] Add command: "Clio: Start Session"
- [ ] Show chat panel (webview) for user input
- [ ] Display clio responses in panel

### Phase 2: Edit Protocol
- [ ] Define message format:
  ```typescript
  {
    type: "edit" | "response" | "status",
    file?: string,
    edits?: Array<{range: Range, newText: string}>,
    content?: string
  }
  ```
- [ ] Modify clio tools to emit edit messages instead of writing files
- [ ] Extension receives edit messages from clio

### Phase 3: Diff Preview
- [ ] Use `vscode.workspace.applyEdit()` to show pending changes
- [ ] Add gutter decorations (green/red/blue indicators)
- [ ] Implement inline diff view on click
- [ ] Add "Accept" / "Reject" buttons for each edit

### Phase 4: Polish
- [ ] Add configuration settings
- [ ] Implement checkpoint/rewind using git or memory snapshots
- [ ] Status bar integration (show model, token count)
- [ ] File tree integration (@-mention autocomplete)
- [ ] Keybindings and commands

## Technical Details

### VS Code APIs Used
- `vscode.window.createWebviewPanel` - Chat UI
- `vscode.workspace.applyEdit` - Apply edits to buffers
- `vscode.window.createTextEditorDecorationType` - Gutter indicators
- `vscode.commands.registerCommand` - Extension commands
- `child_process.spawn` - Run clio CLI

### Message Flow
```
User types in chat panel
  → Extension sends to clio via stdin
  → Clio processes (calls tools)
  → Tool emits edit message {"type": "edit", "file": "...", "edits": [...]}
  → Extension receives on stdout
  → Extension creates WorkspaceEdit
  → VS Code shows diff in editor
  → User accepts
  → Extension applies edit to buffer
```

### Clio Changes Required

1. **Add `--vscode` flag** - Enables VS Code protocol mode
2. **Create VSCodeTransport class** - Handles stdio communication
3. **Modify tools.py**:
   ```python
   async def edit_file(self, path: str, old_text: str, new_text: str):
       if self.vscode_mode:
           # Emit edit message instead of writing file
           self.emit_vscode_message({
               "type": "edit",
               "file": path,
               "edits": [{
                   "range": self._find_range(path, old_text),
                   "newText": new_text
               }]
           })
       else:
           # Normal file I/O
           ...
   ```

## Alternatives Considered

### Option A: LSP (Language Server Protocol)
- ❌ Overkill - LSP is for language features (autocomplete, diagnostics)
- ❌ More complex than needed

### Option B: Direct File Watching + Auto-Reload
- ❌ Doesn't provide diff preview
- ❌ No accept/reject workflow
- ✅ Simplest fallback if extension fails

### Option C: Custom Protocol (CHOSEN)
- ✅ Simple stdio JSON messages
- ✅ Full control over UX
- ✅ Similar to how Claude Code works

## Success Criteria
- [ ] User sees diffs in real-time as clio suggests edits
- [ ] Green/red gutter indicators show changes
- [ ] Click indicator to see inline diff
- [ ] Accept/reject individual edits
- [ ] Works with existing clio models (qwen3-8b-clio, etc.)

## Resources
- [VS Code Extension API](https://code.visualstudio.com/api)
- [WorkspaceEdit Examples](https://github.com/Microsoft/vscode-extension-samples/tree/master/document-editing-sample)
- [Webview API Guide](https://code.visualstudio.com/api/extension-guides/webview)
- [Extension Generator](https://www.npmjs.com/package/generator-code)

## First Steps
```bash
# 1. Install prerequisites
npm install -g yo generator-code

# 2. Generate extension
cd /home/gare/Projects/claude-mimic
yo code
# Choose: New Extension (TypeScript)
# Name: clio-vscode

# 3. Start development
cd clio-vscode
npm run watch  # Auto-compile
# Press F5 in VS Code to launch Extension Development Host
```

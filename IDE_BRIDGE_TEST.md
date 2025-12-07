# Testing the IDE Bridge

## Setup

### 1. Install the VS Code Extension

```bash
cd /home/gare/Projects/claude-mimic/clio/clio-vscode

# Open in VS Code/Cursor
code .

# Press F5 to launch Extension Development Host
```

### 2. Verify Extension Started

In the Extension Development Host window:
- Open Developer Tools (Help → Toggle Developer Tools)
- Look for console messages:
  ```
  [Clio] Extension activated
  [Clio Bridge] WebSocket server started on port XXXXX
  [Clio Bridge] Wrote lock file: /home/gare/.clio/ide/bridge.json
  ```

### 3. Verify Lock File

```bash
cat ~/.clio/ide/bridge.json
```

Should show:
```json
{
  "port": 41234,
  "pid": 12345,
  "ideName": "vscode",
  "workspaceFolders": ["/path/to/workspace"],
  "timestamp": 1234567890
}
```

## Test Real-Time Diffs

### 1. Open a File in VS Code

In the Extension Development Host, open:
```
/home/gare/Projects/claude-mimic/playground/calculator-app/calculator.py
```

### 2. Run Clio in Terminal

In **any terminal** (VS Code integrated terminal or external):

```bash
cd /home/gare/Projects/claude-mimic/playground/calculator-app
clio
```

You should see:
```
✓ Connected to IDE - edits will appear in real-time!
```

### 3. Ask Clio to Fix the Calculator

In clio terminal:
```
Fix the add() function in @calculator.py to use addition instead of power
```

### 4. Watch VS Code

**You should see:**
- The file buffer updates **immediately** in VS Code
- No need to reload or close/reopen
- The change appears in real-time as clio processes it

### 5. Verify the Edit

Check `calculator.py` in VS Code:
- Line 6 should now be: `return a + b` (not `return a ** b`)
- The file should be marked as modified (unsaved) in VS Code
- You should see the change **without** having refreshed

## Troubleshooting

### Extension Not Starting

```bash
# Check logs in Extension Development Host
Help → Toggle Developer Tools → Console
```

Look for errors in bridge server startup.

### Clio Not Connecting

```bash
# Check if lock file exists
ls -la ~/.clio/ide/bridge.json

# Check env var (if using integrated terminal)
echo $CLIO_IDE_PORT
```

If no connection message appears, clio will fall back to file-based edits.

### Edits Not Appearing

1. **Check WebSocket connection:**
   - Look for `[IDE Bridge] Connected to vscode` in clio terminal
   - Check Extension Development Host console for `[Clio Bridge] Client connected`

2. **Check file path:**
   - Edits only work for files in the workspace
   - Path must be absolute

3. **Check for errors:**
   - Extension Development Host console
   - Clio terminal output

## Expected Behavior

✅ **With IDE Bridge:**
- Clio connects to IDE on startup
- Edits appear **instantly** in VS Code buffer
- No file watching needed
- Works from **any terminal** (not just VS Code integrated)

❌ **Without IDE Bridge:**
- Clio writes files to disk
- Need to reload files in editor
- Fallback behavior (current state)

## Success Criteria

- [ ] Extension starts and creates lock file
- [ ] Clio connects and shows "✓ Connected to IDE"
- [ ] File edits appear in VS Code **in real-time**
- [ ] No need to reload or close/reopen file
- [ ] Works from external terminal (not just VS Code integrated)
- [ ] Works with Cursor (same as VS Code)

## Next Steps

Once this works:
1. Add diff preview (show before/after before applying)
2. Add accept/reject buttons
3. Add gutter decorations (green/red/blue indicators)
4. Support for multiple workspaces

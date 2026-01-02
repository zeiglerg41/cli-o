# Clio IDE Bridge Protocol

## Overview
WebSocket-based protocol for communication between terminal clio and IDE extensions (VS Code, Cursor, etc.)

## Connection Discovery

### Lock File Location
`~/.clio/ide/bridge.json`

### Lock File Format
```json
{
  "port": 41234,
  "pid": 12345,
  "ideName": "vscode",
  "workspaceFolders": ["/path/to/workspace"],
  "timestamp": 1234567890
}
```

### Environment Variable (Optional)
`CLIO_IDE_PORT=41234` set in integrated terminal

## Message Protocol

All messages are JSON objects with a `type` field.

### Client → Server (CLI to IDE)

#### 1. Connect
```json
{
  "type": "connect",
  "clientVersion": "0.1.0"
}
```

#### 2. Open Diff
Shows before/after diff in IDE without applying.
```json
{
  "type": "openDiff",
  "file": "/absolute/path/to/file.py",
  "before": "def add(a, b):\n    return a ** b",
  "after": "def add(a, b):\n    return a + b",
  "description": "Fix add() to use addition"
}
```

#### 3. Propose Diff
Shows inline diff with accept/reject buttons (green added line above, red removed line below).
```json
{
  "type": "proposeDiff",
  "file": "/absolute/path/to/file.py",
  "edits": [
    {
      "range": {
        "start": { "line": 5, "character": 11 },
        "end": { "line": 5, "character": 17 }
      },
      "oldText": "a * b",
      "newText": "a + b"
    }
  ],
  "description": "Fix add() to use addition operator"
}
```

#### 4. Apply Diff (deprecated, use proposeDiff)
Directly applies edit to open document without preview.
```json
{
  "type": "applyDiff",
  "file": "/absolute/path/to/file.py",
  "edits": [
    {
      "range": {
        "start": { "line": 5, "character": 11 },
        "end": { "line": 5, "character": 17 }
      },
      "newText": "a + b"
    }
  ]
}
```

#### 5. Close Diff
Closes diff view for a file.
```json
{
  "type": "closeDiff",
  "file": "/absolute/path/to/file.py"
}
```

#### 6. Status Update
Updates status bar or notification.
```json
{
  "type": "status",
  "message": "Processing request...",
  "level": "info"  // "info" | "warning" | "error"
}
```

### Server → Client (IDE to CLI)

#### 1. Connected
Confirms connection established.
```json
{
  "type": "connected",
  "serverVersion": "0.1.0",
  "capabilities": ["diff", "apply", "status"]
}
```

#### 2. Diff Accepted
User accepted diff from preview.
```json
{
  "type": "diffAccepted",
  "file": "/absolute/path/to/file.py"
}
```

#### 3. Diff Rejected
User rejected diff from preview.
```json
{
  "type": "diffRejected",
  "file": "/absolute/path/to/file.py"
}
```

#### 4. Error
Error occurred processing request.
```json
{
  "type": "error",
  "message": "File not found",
  "code": "FILE_NOT_FOUND"
}
```

## Connection Lifecycle

1. **Extension Starts**
   - Start WebSocket server on random port
   - Write `~/.clio/ide/bridge.json`
   - Set `CLIO_IDE_PORT` in integrated terminals

2. **CLI Starts**
   - Check `CLIO_IDE_PORT` env var
   - If not set, check `~/.clio/ide/bridge.json`
   - If found, connect to WebSocket
   - Send `connect` message

3. **Extension Responds**
   - Send `connected` message with capabilities

4. **Edit Flow**
   - CLI sends `openDiff` or `applyDiff`
   - Extension shows diff or applies edit
   - Extension sends `diffAccepted` / `diffRejected` (for openDiff)

5. **Disconnection**
   - CLI disconnects on exit
   - Extension cleans up on deactivation

## Fallback Behavior

If CLI cannot connect to IDE:
- Fall back to file system edits
- Show diffs in terminal (current behavior)
- No real-time IDE integration

## Security

- WebSocket server binds to `127.0.0.1` only (localhost)
- No authentication needed (local-only)
- Lock file readable only by user (`chmod 600`)

## Example Flow

```
CLI                          Extension
 |                                |
 |-- connect ------------------>  |
 |                                |
 |  <-------------- connected ---|
 |                                |
 |-- openDiff ----------------->  |
 |    (shows diff in IDE)         |
 |                                |
 |  <---------- diffAccepted ----|
 |    (user clicked Accept)       |
 |                                |
 |-- applyDiff ----------------->  |
 |    (edit applied to buffer)    |
 |                                |
```

## Implementation Notes

- **WebSocket Library**: Use `ws` for Node.js extensions
- **Port Selection**: Use `0` to get random available port
- **Reconnection**: CLI should retry connection on disconnect
- **Multiple Workspaces**: Support multiple VS Code windows with separate ports
- **Lock File Cleanup**: Extension removes lock file on deactivation

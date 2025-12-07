# Testing Guide for Clio VS Code Extension

This document provides comprehensive testing instructions for the Clio VS Code extension.

## Prerequisites

Before testing, ensure you have:

1. **VS Code** version 1.85.0 or higher installed
2. **Node.js** and npm installed
3. **clio CLI tool** installed and available in your PATH (or a mock version for testing)

## Setup for Testing

### 1. Install Dependencies

```bash
cd clio-vscode
npm install
```

### 2. Compile the Extension

```bash
npm run compile
```

### 3. Launch Extension Development Host

In VS Code:
- Open the `clio-vscode` folder
- Press `F5` to launch the Extension Development Host
- A new VS Code window will open with the extension loaded

## Testing Checklist

### Basic Functionality Tests

#### ✓ Extension Activation

1. Open Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`)
2. Type "Clio: Start Session"
3. **Expected**: Command appears in the list
4. **Expected**: Extension activates without errors

#### ✓ Status Bar Integration

1. Look at the bottom-left status bar
2. **Expected**: "○ Clio" indicator appears
3. Click the status bar item
4. **Expected**: Same as running "Clio: Start Session" command

#### ✓ Chat Panel Creation

1. Run "Clio: Start Session"
2. **Expected**: Chat panel opens on the right side
3. **Expected**: Input box and "Send" button are visible
4. **Expected**: Status bar changes to "✓ Clio Active"

### Communication Tests

#### ✓ Process Spawning

1. Start a session
2. Check the Debug Console (View → Debug Console)
3. **Expected**: "[Clio] Extension activated" message
4. **Expected**: "[Clio] Extension setup complete" message
5. **Expected**: No error messages about process spawning

#### ✓ Message Sending

1. Type a message in the chat input: "Hello, Clio"
2. Press Enter or click "Send"
3. **Expected**: Message appears in chat as user message (blue)
4. **Expected**: Status bar shows "⟳ Clio: Processing..."
5. Check Debug Console
6. **Expected**: "[Clio] Sending message to clio: Hello, Clio"

#### ✓ Response Handling

*Note: This requires a working clio CLI that responds with JSON*

1. Send a message to clio
2. **Expected**: Response appears in chat as assistant message (gray)
3. **Expected**: Status bar returns to "✓ Clio Active"

### Edit Application Tests

#### ✓ Edit Message Parsing

Create a mock clio process that outputs:

```json
{"type":"edit","file":"/path/to/test.js","edits":[{"range":{"start":{"line":0,"character":0},"end":{"line":0,"character":0}},"newText":"// Added by Clio\n"}]}
```

**Expected**:
- File opens in editor
- Gutter decoration appears (green circle)
- Edit is applied to the file
- File shows as modified (unsaved)

#### ✓ Multi-file Edits

Test with multiple edit messages for different files.

**Expected**:
- All files open
- All edits applied correctly
- Each file shows decorations

#### ✓ Decoration Lifecycle

1. Apply an edit
2. Wait 3 seconds
3. **Expected**: Decorations clear automatically

### Status Updates Tests

#### ✓ Status Messages

Mock clio output:

```json
{"type":"status","activity":"Analyzing code..."}
```

**Expected**:
- Status bar shows "⟳ Clio: Analyzing code..."
- Chat panel shows status message

### Error Handling Tests

#### ✓ Process Not Found

1. Ensure `clio` is NOT in PATH
2. Run "Clio: Start Session"
3. **Expected**: Error message: "Failed to start Clio: ... Make sure 'clio' is installed and in your PATH."
4. **Expected**: Status bar shows "✗ Clio Error"

#### ✓ Process Crash

1. Start a session with working clio
2. Kill the clio process manually
3. **Expected**: Warning message: "Clio process exited unexpectedly"
4. **Expected**: Status bar returns to "○ Clio"

#### ✓ Invalid JSON

Mock clio that outputs invalid JSON.

**Expected**:
- Error logged in Debug Console
- Extension continues running
- No crash

### UI/UX Tests

#### ✓ Chat Message Display

1. Send multiple messages
2. **Expected**: User messages align right (blue)
3. **Expected**: Assistant messages align left (gray)
4. **Expected**: Tool messages show with 🔧 icon (orange)
5. **Expected**: Status messages show with ⚡ icon (blue, centered)
6. **Expected**: Timestamps appear on each message

#### ✓ Chat Scrolling

1. Send 20+ messages to fill the chat
2. **Expected**: Scroll bar appears
3. **Expected**: Auto-scrolls to bottom on new messages

#### ✓ Input Field

1. Type a long message
2. **Expected**: Text wraps properly
3. Press Enter
4. **Expected**: Message sends
5. **Expected**: Input clears after sending

#### ✓ State Persistence

1. Send several messages
2. Close the chat panel
3. Run "Clio: Start Session" again
4. **Expected**: Previous messages are restored

### Cleanup Tests

#### ✓ Stop Session

1. Run "Clio: Stop Session" command
2. **Expected**: Process terminates
3. **Expected**: Status bar returns to "○ Clio"
4. **Expected**: Success message appears

#### ✓ Extension Deactivation

1. Start a session
2. Close VS Code
3. **Expected**: clio process is killed
4. **Expected**: No orphaned processes remain

## Mock Clio for Testing

If you don't have the actual clio CLI, create a mock for testing:

### Simple Mock Script (mock-clio.js)

```javascript
#!/usr/bin/env node

const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

// Listen for messages
rl.on('line', (line) => {
  try {
    const message = JSON.parse(line);
    
    // Simulate processing
    setTimeout(() => {
      // Send status
      console.log(JSON.stringify({
        type: 'status',
        activity: 'Processing request...'
      }));
      
      // Send response
      setTimeout(() => {
        console.log(JSON.stringify({
          type: 'response',
          content: `You said: ${message.content}`
        }));
        
        // Optionally send an edit
        if (message.content.includes('edit')) {
          console.log(JSON.stringify({
            type: 'edit',
            file: '/tmp/test.js',
            edits: [{
              range: {
                start: { line: 0, character: 0 },
                end: { line: 0, character: 0 }
              },
              newText: '// Edited by Clio\n'
            }]
          }));
        }
      }, 500);
    }, 200);
  } catch (err) {
    console.error('Parse error:', err);
  }
});

console.error('Mock clio started');
```

### Using the Mock

1. Save as `mock-clio.js`
2. Make executable: `chmod +x mock-clio.js`
3. Create symlink: `ln -s $(pwd)/mock-clio.js /usr/local/bin/clio`
4. Test the extension

## Automated Testing

For future development, consider adding:

1. **Unit Tests**: Test individual components (ClioClient, DiffProvider, etc.)
2. **Integration Tests**: Test component interactions
3. **E2E Tests**: Use VS Code's test framework

## Performance Testing

Monitor:
- Memory usage during long sessions
- Process cleanup on restart
- Large edit handling (100+ edits)
- Multiple file operations

## Reporting Issues

When reporting issues, include:
1. VS Code version
2. Extension version
3. Operating system
4. Steps to reproduce
5. Debug Console output
6. Expected vs actual behavior

## Success Criteria

The extension passes testing if:
- ✓ All basic functionality tests pass
- ✓ No errors in Debug Console during normal operation
- ✓ Process cleanup works correctly
- ✓ UI is responsive and intuitive
- ✓ Edits apply correctly without corruption
- ✓ Error handling prevents crashes

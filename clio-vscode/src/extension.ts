import * as vscode from 'vscode';
import { ClioClient } from './clioClient';
import { DiffProvider } from './diffProvider';
import { EditApplier } from './editApplier';
import { StatusBar } from './statusBar';
import { ChatPanel } from './webview/chatPanel';
import { BridgeServer } from './bridgeServer';

/**
 * Extension activation entry point
 */
export function activate(context: vscode.ExtensionContext) {
  console.log('[Clio] Extension activated');

  // Start WebSocket bridge server for terminal CLI
  const bridgeServer = new BridgeServer();
  bridgeServer.start().then(() => {
    console.log('[Clio] Bridge server started');
  }).catch((error) => {
    console.error('[Clio] Failed to start bridge server:', error);
    vscode.window.showErrorMessage(`Clio: Failed to start IDE bridge: ${error}`);
  });

  // Cleanup bridge server on deactivation
  context.subscriptions.push({
    dispose: () => bridgeServer.stop()
  });

  // Initialize core components
  const clioClient = new ClioClient();
  const diffProvider = new DiffProvider();
  const editApplier = new EditApplier();
  const statusBar = new StatusBar();

  let chatPanel: ChatPanel | undefined;
  let isSessionActive = false;

  // Register the "Start Session" command
  const startSessionCommand = vscode.commands.registerCommand(
    'clio.startSession',
    async () => {
      try {
        // Check if session is already active
        if (isSessionActive && clioClient.isRunning()) {
          vscode.window.showInformationMessage('Clio session is already active');
          if (chatPanel) {
            // Just show the existing panel
            chatPanel = ChatPanel.createOrShow(context.extensionUri);
          }
          return;
        }

        // Update status
        statusBar.setWorking('Starting...');

        // Start the clio process
        await clioClient.start();
        isSessionActive = true;

        // Update status
        statusBar.setActive();

        // Create or show chat panel
        chatPanel = ChatPanel.createOrShow(context.extensionUri);

        // Handle messages from the webview
        chatPanel.onMessage((message) => {
          if (message.command === 'sendMessage') {
            console.log('[Clio] Sending message to clio:', message.text);
            clioClient.sendMessage(message.text);
            statusBar.setWorking('Processing...');
          }
        });

        vscode.window.showInformationMessage('Clio session started successfully');
      } catch (err) {
        console.error('[Clio] Error starting session:', err);
        statusBar.setError('Failed to start');
        vscode.window.showErrorMessage(
          `Failed to start Clio: ${err}. Make sure 'clio' is installed and in your PATH.`
        );
        isSessionActive = false;
      }
    }
  );

  // Listen for edit messages from clio
  clioClient.on('edit', async (editMsg) => {
    console.log('[Clio] Received edit message:', editMsg);
    
    try {
      // Show pending edit with decorations
      await diffProvider.showPendingEdit(editMsg);

      // Apply the edit automatically
      // (In a more advanced version, you could add accept/reject UI)
      const success = await editApplier.applyEdit(editMsg);

      if (success) {
        // Notify the chat panel
        chatPanel?.postMessage({
          type: 'tool',
          tool: 'edit',
          result: `Applied changes to ${editMsg.file}`
        });

        // Clear decorations after a delay
        setTimeout(() => {
          diffProvider.clearPendingEdit(editMsg.file);
        }, 3000);
      } else {
        chatPanel?.postMessage({
          type: 'error',
          content: `Failed to apply changes to ${editMsg.file}`
        });
      }
    } catch (err) {
      console.error('[Clio] Error handling edit:', err);
      chatPanel?.postMessage({
        type: 'error',
        content: `Error applying edit: ${err}`
      });
    }
  });

  // Listen for response messages from clio
  clioClient.on('response', (respMsg) => {
    console.log('[Clio] Received response:', respMsg.content);
    
    // Send to chat panel
    chatPanel?.postMessage({
      type: 'response',
      content: respMsg.content
    });

    // Update status
    statusBar.setActive();
  });

  // Listen for status messages from clio
  clioClient.on('status', (statusMsg) => {
    console.log('[Clio] Status update:', statusMsg.activity);
    
    // Update status bar
    statusBar.setWorking(statusMsg.activity);

    // Send to chat panel
    chatPanel?.postMessage({
      type: 'status',
      activity: statusMsg.activity
    });
  });

  // Listen for errors from clio
  clioClient.on('error', (err) => {
    console.error('[Clio] Error:', err);
    
    statusBar.setError('Error occurred');
    
    chatPanel?.postMessage({
      type: 'error',
      content: err.message || 'An error occurred'
    });
  });

  // Listen for process exit
  clioClient.on('exit', ({ code, signal }) => {
    console.log(`[Clio] Process exited: code=${code}, signal=${signal}`);
    
    isSessionActive = false;
    statusBar.setIdle();

    if (code !== 0 && code !== null) {
      vscode.window.showWarningMessage(
        `Clio process exited unexpectedly (code: ${code})`
      );
    }
  });

  // Register command to stop session
  const stopSessionCommand = vscode.commands.registerCommand(
    'clio.stopSession',
    () => {
      if (isSessionActive) {
        clioClient.stop();
        isSessionActive = false;
        statusBar.setIdle();
        vscode.window.showInformationMessage('Clio session stopped');
      }
    }
  );

  // Add disposables to context
  context.subscriptions.push(
    startSessionCommand,
    stopSessionCommand,
    statusBar,
    diffProvider,
    // Clean up on deactivation
    new vscode.Disposable(() => {
      if (isSessionActive) {
        clioClient.stop();
      }
    })
  );

  console.log('[Clio] Extension setup complete');
}

/**
 * Extension deactivation
 */
export function deactivate() {
  console.log('[Clio] Extension deactivated');
}

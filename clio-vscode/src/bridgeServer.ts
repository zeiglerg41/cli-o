import * as vscode from 'vscode';
import * as WebSocket from 'ws';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { DiffDecorator } from './diffDecorator';

/**
 * WebSocket bridge server for terminal CLI to connect to
 */
export class BridgeServer {
  private server: WebSocket.Server | undefined;
  private clients: Set<WebSocket> = new Set();
  private port: number = 0;
  private lockFilePath: string;
  private diffDecorator: DiffDecorator;

  constructor(diffDecorator: DiffDecorator) {
    const clioDir = path.join(os.homedir(), '.clio', 'ide');
    this.lockFilePath = path.join(clioDir, 'bridge.json');
    this.diffDecorator = diffDecorator;
  }

  /**
   * Start the WebSocket server
   */
  async start(): Promise<void> {
    return new Promise((resolve, reject) => {
      // Create server on random available port
      this.server = new WebSocket.Server({ host: '127.0.0.1', port: 0 }, () => {
        if (!this.server) {
          reject(new Error('Server failed to start'));
          return;
        }

        const address = this.server.address() as WebSocket.AddressInfo;
        this.port = address.port;

        console.log(`[Clio Bridge] WebSocket server started on port ${this.port}`);

        // Write lock file
        this.writeLockFile();

        // Set env var for integrated terminals
        this.setEnvironmentVariable();

        resolve();
      });

      this.server.on('connection', (ws: WebSocket) => {
        this.handleConnection(ws);
      });

      this.server.on('error', (error) => {
        console.error('[Clio Bridge] Server error:', error);
        reject(error);
      });
    });
  }

  /**
   * Stop the server and cleanup
   */
  stop(): void {
    // Close all client connections
    this.clients.forEach(client => {
      client.close();
    });
    this.clients.clear();

    // Close server
    if (this.server) {
      this.server.close();
      this.server = undefined;
    }

    // Remove lock file
    this.removeLockFile();

    console.log('[Clio Bridge] Server stopped');
  }

  /**
   * Handle new WebSocket connection
   */
  private handleConnection(ws: WebSocket): void {
    console.log('[Clio Bridge] Client connected');
    this.clients.add(ws);

    ws.on('message', (data: WebSocket.Data) => {
      try {
        const message = JSON.parse(data.toString());
        this.handleMessage(ws, message);
      } catch (error) {
        console.error('[Clio Bridge] Failed to parse message:', error);
        this.sendError(ws, 'Invalid JSON message');
      }
    });

    ws.on('close', () => {
      console.log('[Clio Bridge] Client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('[Clio Bridge] Client error:', error);
      this.clients.delete(ws);
    });
  }

  /**
   * Handle incoming message from CLI
   */
  private async handleMessage(ws: WebSocket, message: any): Promise<void> {
    console.log('[Clio Bridge] Received message:', message.type);

    switch (message.type) {
      case 'connect':
        this.handleConnect(ws, message);
        break;

      case 'proposeDiff':
        await this.handleProposeDiff(ws, message);
        break;

      case 'openDiff':
        await this.handleOpenDiff(ws, message);
        break;

      case 'applyDiff':
        await this.handleApplyDiff(ws, message);
        break;

      case 'closeDiff':
        await this.handleCloseDiff(ws, message);
        break;

      case 'status':
        this.handleStatus(message);
        break;

      default:
        this.sendError(ws, `Unknown message type: ${message.type}`);
    }
  }

  /**
   * Handle connect message
   */
  private handleConnect(ws: WebSocket, message: any): void {
    this.send(ws, {
      type: 'connected',
      serverVersion: '0.1.0',
      capabilities: ['diff', 'apply', 'status', 'proposeDiff']
    });
  }

  /**
   * Handle proposeDiff - show inline diff with accept/reject buttons
   */
  private async handleProposeDiff(ws: WebSocket, message: any): Promise<void> {
    try {
      const { file, edits, description } = message;

      console.log(`[Clio Bridge] Proposing diff for ${file}:`, description);

      // Show inline diff decorations
      await this.diffDecorator.showDiff(file, edits, description);

      // Note: We don't send a response here - waiting for user to accept/reject
      // The accept/reject commands will send diffAccepted or diffRejected

    } catch (error) {
      console.error('[Clio Bridge] Error proposing diff:', error);
      this.sendError(ws, `Failed to propose diff: ${error}`);
    }
  }

  /**
   * Handle openDiff - show before/after diff in IDE
   */
  private async handleOpenDiff(ws: WebSocket, message: any): Promise<void> {
    try {
      const { file, before, after, description } = message;

      // Create temp files for diff
      const beforeUri = vscode.Uri.parse(`clio-before:${file}`);
      const afterUri = vscode.Uri.parse(`clio-after:${file}`);

      // Register text document content providers
      const beforeProvider = new (class implements vscode.TextDocumentContentProvider {
        provideTextDocumentContent(): string {
          return before;
        }
      })();

      const afterProvider = new (class implements vscode.TextDocumentContentProvider {
        provideTextDocumentContent(): string {
          return after;
        }
      })();

      vscode.workspace.registerTextDocumentContentProvider('clio-before', beforeProvider);
      vscode.workspace.registerTextDocumentContentProvider('clio-after', afterProvider);

      // Open diff view
      const title = description || `${path.basename(file)} (Clio)`;
      await vscode.commands.executeCommand('vscode.diff', beforeUri, afterUri, title);

      // For now, auto-accept (in future, add UI buttons for accept/reject)
      this.send(ws, {
        type: 'diffAccepted',
        file: file
      });

    } catch (error) {
      console.error('[Clio Bridge] Error opening diff:', error);
      this.sendError(ws, `Failed to open diff: ${error}`);
    }
  }

  /**
   * Handle applyDiff - directly apply edits to document
   */
  private async handleApplyDiff(ws: WebSocket, message: any): Promise<void> {
    try {
      const { file, edits } = message;
      const uri = vscode.Uri.file(file);

      // Create workspace edit
      const workspaceEdit = new vscode.WorkspaceEdit();

      for (const edit of edits) {
        const range = new vscode.Range(
          new vscode.Position(edit.range.start.line, edit.range.start.character),
          new vscode.Position(edit.range.end.line, edit.range.end.character)
        );
        workspaceEdit.replace(uri, range, edit.newText);
      }

      // Apply edit
      const success = await vscode.workspace.applyEdit(workspaceEdit);

      if (!success) {
        this.sendError(ws, 'Failed to apply edit');
        return;
      }

      // Open file if not already open
      const document = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(document);

      console.log('[Clio Bridge] Applied diff to', file);

    } catch (error) {
      console.error('[Clio Bridge] Error applying diff:', error);
      this.sendError(ws, `Failed to apply diff: ${error}`);
    }
  }

  /**
   * Handle closeDiff - close diff view
   */
  private async handleCloseDiff(ws: WebSocket, message: any): Promise<void> {
    // Close any open diff editors for this file
    // VS Code doesn't have a direct API for this, so we just acknowledge
    console.log('[Clio Bridge] Close diff requested for', message.file);
  }

  /**
   * Handle status update
   */
  private handleStatus(message: any): void {
    const { message: text, level } = message;

    switch (level) {
      case 'error':
        vscode.window.showErrorMessage(`Clio: ${text}`);
        break;
      case 'warning':
        vscode.window.showWarningMessage(`Clio: ${text}`);
        break;
      default:
        vscode.window.showInformationMessage(`Clio: ${text}`);
    }
  }

  /**
   * Send message to client
   */
  private send(ws: WebSocket, message: any): void {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }

  /**
   * Broadcast message to all connected clients
   */
  private broadcast(message: any): void {
    this.clients.forEach(client => {
      if (client.readyState === WebSocket.OPEN) {
        client.send(JSON.stringify(message));
      }
    });
  }

  /**
   * Notify all clients that a diff was accepted
   */
  notifyDiffAccepted(file: string): void {
    this.broadcast({
      type: 'diffAccepted',
      file: file
    });
  }

  /**
   * Notify all clients that a diff was rejected
   */
  notifyDiffRejected(file: string): void {
    this.broadcast({
      type: 'diffRejected',
      file: file
    });
  }

  /**
   * Send error message
   */
  private sendError(ws: WebSocket, message: string, code?: string): void {
    this.send(ws, {
      type: 'error',
      message,
      code: code || 'ERROR'
    });
  }

  /**
   * Write lock file with connection info
   */
  private writeLockFile(): void {
    const lockDir = path.dirname(this.lockFilePath);

    // Create directory if it doesn't exist
    if (!fs.existsSync(lockDir)) {
      fs.mkdirSync(lockDir, { recursive: true, mode: 0o700 });
    }

    const lockData = {
      port: this.port,
      pid: process.pid,
      ideName: 'vscode',
      workspaceFolders: vscode.workspace.workspaceFolders?.map(f => f.uri.fsPath) || [],
      timestamp: Date.now()
    };

    fs.writeFileSync(this.lockFilePath, JSON.stringify(lockData, null, 2), { mode: 0o600 });
    console.log('[Clio Bridge] Wrote lock file:', this.lockFilePath);
  }

  /**
   * Remove lock file
   */
  private removeLockFile(): void {
    if (fs.existsSync(this.lockFilePath)) {
      fs.unlinkSync(this.lockFilePath);
      console.log('[Clio Bridge] Removed lock file');
    }
  }

  /**
   * Set environment variable for integrated terminals
   */
  private setEnvironmentVariable(): void {
    // This sets the env var for future integrated terminals
    // Note: VS Code doesn't provide API to modify existing terminal env
    process.env.CLIO_IDE_PORT = this.port.toString();
  }
}

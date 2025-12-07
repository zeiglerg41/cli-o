import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Manages the chat webview panel
 */
export class ChatPanel {
  public static currentPanel: ChatPanel | undefined;
  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private messageCallback?: (message: any) => void;

  /**
   * Create or show the chat panel
   */
  public static createOrShow(extensionUri: vscode.Uri): ChatPanel {
    const column = vscode.ViewColumn.Two;

    // If we already have a panel, show it
    if (ChatPanel.currentPanel) {
      ChatPanel.currentPanel.panel.reveal(column);
      return ChatPanel.currentPanel;
    }

    // Otherwise, create a new panel
    const panel = vscode.window.createWebviewPanel(
      'clioChat',
      'Clio Chat',
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'src', 'webview')]
      }
    );

    ChatPanel.currentPanel = new ChatPanel(panel, extensionUri);
    return ChatPanel.currentPanel;
  }

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this.panel = panel;
    this.extensionUri = extensionUri;

    // Set the webview's initial html content
    this.panel.webview.html = this.getHtmlContent();

    // Listen for when the panel is disposed
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    // Handle messages from the webview
    this.panel.webview.onDidReceiveMessage(
      (message) => {
        if (this.messageCallback) {
          this.messageCallback(message);
        }
      },
      null,
      this.disposables
    );
  }

  /**
   * Register a callback for messages from the webview
   */
  public onMessage(callback: (message: any) => void): void {
    this.messageCallback = callback;
  }

  /**
   * Send a message to the webview
   */
  public postMessage(message: any): void {
    this.panel.webview.postMessage(message);
  }

  /**
   * Get the HTML content for the webview
   */
  private getHtmlContent(): string {
    try {
      // Read the HTML file
      const htmlPath = path.join(
        this.extensionUri.fsPath,
        'src',
        'webview',
        'chatPanel.html'
      );
      
      let html = fs.readFileSync(htmlPath, 'utf8');

      // Add CSP meta tag for security
      const cspSource = this.panel.webview.cspSource;
      const csp = `
        <meta http-equiv="Content-Security-Policy" 
          content="default-src 'none'; 
                   style-src ${cspSource} 'unsafe-inline'; 
                   script-src ${cspSource} 'unsafe-inline';">
      `;
      
      html = html.replace('<head>', `<head>${csp}`);

      return html;
    } catch (err) {
      console.error('[ChatPanel] Error loading HTML:', err);
      return this.getErrorHtml();
    }
  }

  /**
   * Get error HTML if the main HTML fails to load
   */
  private getErrorHtml(): string {
    return `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <style>
          body {
            font-family: var(--vscode-font-family);
            color: var(--vscode-foreground);
            background-color: var(--vscode-editor-background);
            padding: 20px;
          }
        </style>
      </head>
      <body>
        <h2>Error Loading Chat Panel</h2>
        <p>Failed to load the chat interface. Please try restarting the extension.</p>
      </body>
      </html>
    `;
  }

  /**
   * Dispose of the panel and clean up resources
   */
  public dispose(): void {
    ChatPanel.currentPanel = undefined;

    // Clean up resources
    this.panel.dispose();

    while (this.disposables.length) {
      const disposable = this.disposables.pop();
      if (disposable) {
        disposable.dispose();
      }
    }
  }
}

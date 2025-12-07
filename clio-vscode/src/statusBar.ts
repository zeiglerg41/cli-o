import * as vscode from 'vscode';

/**
 * Manages the status bar item for Clio
 */
export class StatusBar {
  private statusBarItem: vscode.StatusBarItem;

  constructor() {
    // Create status bar item
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    
    this.statusBarItem.command = 'clio.startSession';
    this.setIdle();
    this.statusBarItem.show();
  }

  /**
   * Set status to idle
   */
  setIdle(): void {
    this.statusBarItem.text = '$(circle-outline) Clio';
    this.statusBarItem.tooltip = 'Click to start Clio session';
    this.statusBarItem.backgroundColor = undefined;
  }

  /**
   * Set status to active/running
   */
  setActive(): void {
    this.statusBarItem.text = '$(check) Clio Active';
    this.statusBarItem.tooltip = 'Clio is running';
    this.statusBarItem.backgroundColor = undefined;
  }

  /**
   * Set status to working/processing
   */
  setWorking(activity?: string): void {
    this.statusBarItem.text = `$(sync~spin) Clio: ${activity || 'Working...'}`;
    this.statusBarItem.tooltip = activity || 'Clio is processing';
    this.statusBarItem.backgroundColor = undefined;
  }

  /**
   * Set status to error
   */
  setError(message?: string): void {
    this.statusBarItem.text = '$(error) Clio Error';
    this.statusBarItem.tooltip = message || 'Clio encountered an error';
    this.statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
  }

  /**
   * Update status with custom text
   */
  update(text: string, tooltip?: string): void {
    this.statusBarItem.text = text;
    if (tooltip) {
      this.statusBarItem.tooltip = tooltip;
    }
  }

  /**
   * Show the status bar item
   */
  show(): void {
    this.statusBarItem.show();
  }

  /**
   * Hide the status bar item
   */
  hide(): void {
    this.statusBarItem.hide();
  }

  /**
   * Dispose of the status bar item
   */
  dispose(): void {
    this.statusBarItem.dispose();
  }
}

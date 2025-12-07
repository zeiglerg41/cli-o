import * as vscode from 'vscode';
import { EditMessage } from './clioClient';

/**
 * Manages diff visualization with gutter decorations and inline diffs
 */
export class DiffProvider {
  private additionDecorationType: vscode.TextEditorDecorationType;
  private modificationDecorationType: vscode.TextEditorDecorationType;
  private deletionDecorationType: vscode.TextEditorDecorationType;
  private pendingEdits: Map<string, EditMessage> = new Map();

  constructor() {
    // Create decoration types for different edit types
    this.additionDecorationType = vscode.window.createTextEditorDecorationType({
      backgroundColor: 'rgba(0, 255, 0, 0.1)',
      border: '0 0 0 3px solid green',
      gutterIconPath: this.createGutterIcon('green'),
      gutterIconSize: 'contain',
      isWholeLine: true,
    });

    this.modificationDecorationType = vscode.window.createTextEditorDecorationType({
      backgroundColor: 'rgba(0, 100, 255, 0.1)',
      border: '0 0 0 3px solid blue',
      gutterIconPath: this.createGutterIcon('blue'),
      gutterIconSize: 'contain',
      isWholeLine: true,
    });

    this.deletionDecorationType = vscode.window.createTextEditorDecorationType({
      backgroundColor: 'rgba(255, 0, 0, 0.1)',
      border: '0 0 0 3px solid red',
      gutterIconPath: this.createGutterIcon('red'),
      gutterIconSize: 'contain',
      isWholeLine: true,
    });
  }

  /**
   * Create a simple SVG gutter icon
   */
  private createGutterIcon(color: string): vscode.Uri {
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">
        <circle cx="8" cy="8" r="6" fill="${color}" />
      </svg>
    `;
    return vscode.Uri.parse(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`);
  }

  /**
   * Show pending edit with gutter decorations
   */
  async showPendingEdit(edit: EditMessage): Promise<void> {
    try {
      // Store the pending edit
      this.pendingEdits.set(edit.file, edit);

      // Open the file if not already open
      const uri = vscode.Uri.file(edit.file);
      const document = await vscode.workspace.openTextDocument(uri);
      const editor = await vscode.window.showTextDocument(document);

      // Apply gutter decorations
      this.applyGutterDecorations(editor, edit);
    } catch (err) {
      console.error('[DiffProvider] Error showing pending edit:', err);
      throw err;
    }
  }

  /**
   * Apply gutter decorations to the editor
   */
  private applyGutterDecorations(editor: vscode.TextEditor, edit: EditMessage): void {
    const additions: vscode.Range[] = [];
    const modifications: vscode.Range[] = [];
    const deletions: vscode.Range[] = [];

    for (const e of edit.edits) {
      const range = new vscode.Range(
        new vscode.Position(e.range.start.line, e.range.start.character),
        new vscode.Position(e.range.end.line, e.range.end.character)
      );

      // Determine edit type based on range and newText
      if (range.isEmpty && e.newText) {
        // Insertion
        additions.push(range);
      } else if (!range.isEmpty && !e.newText) {
        // Deletion
        deletions.push(range);
      } else {
        // Modification
        modifications.push(range);
      }
    }

    // Apply decorations
    editor.setDecorations(this.additionDecorationType, additions);
    editor.setDecorations(this.modificationDecorationType, modifications);
    editor.setDecorations(this.deletionDecorationType, deletions);
  }

  /**
   * Show inline diff for a specific edit
   */
  async showInlineDiff(filePath: string, editIndex: number): Promise<void> {
    const edit = this.pendingEdits.get(filePath);
    if (!edit || !edit.edits[editIndex]) {
      return;
    }

    try {
      const uri = vscode.Uri.file(filePath);
      const document = await vscode.workspace.openTextDocument(uri);
      const specificEdit = edit.edits[editIndex];

      // Create a temporary document with the new text for comparison
      const range = new vscode.Range(
        new vscode.Position(specificEdit.range.start.line, specificEdit.range.start.character),
        new vscode.Position(specificEdit.range.end.line, specificEdit.range.end.character)
      );

      const originalText = document.getText(range);
      const newText = specificEdit.newText;

      // Show diff using VS Code's diff editor
      const originalUri = uri.with({ scheme: 'clio-original', query: originalText });
      const modifiedUri = uri.with({ scheme: 'clio-modified', query: newText });

      await vscode.commands.executeCommand(
        'vscode.diff',
        originalUri,
        modifiedUri,
        `Clio Diff: ${filePath}`
      );
    } catch (err) {
      console.error('[DiffProvider] Error showing inline diff:', err);
    }
  }

  /**
   * Clear all decorations
   */
  clearDecorations(): void {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      editor.setDecorations(this.additionDecorationType, []);
      editor.setDecorations(this.modificationDecorationType, []);
      editor.setDecorations(this.deletionDecorationType, []);
    }
  }

  /**
   * Clear pending edits for a file
   */
  clearPendingEdit(filePath: string): void {
    this.pendingEdits.delete(filePath);
  }

  /**
   * Dispose of decoration types
   */
  dispose(): void {
    this.additionDecorationType.dispose();
    this.modificationDecorationType.dispose();
    this.deletionDecorationType.dispose();
    this.pendingEdits.clear();
  }
}

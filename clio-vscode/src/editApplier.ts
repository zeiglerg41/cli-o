import * as vscode from 'vscode';
import { EditMessage } from './clioClient';
import * as path from 'path';

/**
 * Applies edits to workspace documents using VS Code's WorkspaceEdit API
 */
export class EditApplier {
  /**
   * Apply an edit message to the workspace
   */
  async applyEdit(edit: EditMessage): Promise<boolean> {
    try {
      const workspaceEdit = new vscode.WorkspaceEdit();
      
      // Resolve file path (handle both absolute and relative paths)
      const filePath = this.resolveFilePath(edit.file);
      const uri = vscode.Uri.file(filePath);

      // Apply each edit in the message
      for (const e of edit.edits) {
        const range = new vscode.Range(
          new vscode.Position(e.range.start.line, e.range.start.character),
          new vscode.Position(e.range.end.line, e.range.end.character)
        );
        
        workspaceEdit.replace(uri, range, e.newText);
      }

      // Apply the workspace edit
      const success = await vscode.workspace.applyEdit(workspaceEdit);
      
      if (success) {
        console.log(`[EditApplier] Successfully applied edit to ${edit.file}`);
        
        // Open the file to show the changes
        const document = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(document);
      } else {
        console.error(`[EditApplier] Failed to apply edit to ${edit.file}`);
      }

      return success;
    } catch (err) {
      console.error('[EditApplier] Error applying edit:', err);
      vscode.window.showErrorMessage(`Failed to apply edit: ${err}`);
      return false;
    }
  }

  /**
   * Apply multiple edits in sequence
   */
  async applyEdits(edits: EditMessage[]): Promise<boolean> {
    let allSuccessful = true;
    
    for (const edit of edits) {
      const success = await this.applyEdit(edit);
      if (!success) {
        allSuccessful = false;
      }
    }

    return allSuccessful;
  }

  /**
   * Resolve file path (handle relative paths from workspace root)
   */
  private resolveFilePath(filePath: string): string {
    // If absolute path, return as-is
    if (path.isAbsolute(filePath)) {
      return filePath;
    }

    // If relative, resolve from workspace root
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders && workspaceFolders.length > 0) {
      return path.join(workspaceFolders[0].uri.fsPath, filePath);
    }

    // Fallback: return as-is and let VS Code handle it
    return filePath;
  }

  /**
   * Revert an edit (undo)
   */
  async revertEdit(edit: EditMessage): Promise<boolean> {
    try {
      const filePath = this.resolveFilePath(edit.file);
      const uri = vscode.Uri.file(filePath);
      const document = await vscode.workspace.openTextDocument(uri);

      // Execute undo command
      await vscode.commands.executeCommand('undo');
      
      console.log(`[EditApplier] Reverted edit to ${edit.file}`);
      return true;
    } catch (err) {
      console.error('[EditApplier] Error reverting edit:', err);
      return false;
    }
  }

  /**
   * Preview edit without applying (opens diff view)
   */
  async previewEdit(edit: EditMessage): Promise<void> {
    try {
      const filePath = this.resolveFilePath(edit.file);
      const uri = vscode.Uri.file(filePath);
      const document = await vscode.workspace.openTextDocument(uri);

      // Create a copy of the document with edits applied
      let modifiedContent = document.getText();
      
      // Apply edits in reverse order to maintain correct positions
      const sortedEdits = [...edit.edits].sort((a, b) => {
        const aStart = a.range.start.line * 10000 + a.range.start.character;
        const bStart = b.range.start.line * 10000 + b.range.start.character;
        return bStart - aStart; // Reverse order
      });

      for (const e of sortedEdits) {
        const startOffset = document.offsetAt(
          new vscode.Position(e.range.start.line, e.range.start.character)
        );
        const endOffset = document.offsetAt(
          new vscode.Position(e.range.end.line, e.range.end.character)
        );
        
        modifiedContent = 
          modifiedContent.substring(0, startOffset) +
          e.newText +
          modifiedContent.substring(endOffset);
      }

      // Show diff
      const originalUri = uri.with({ scheme: 'clio-original' });
      const modifiedUri = uri.with({ scheme: 'clio-modified' });

      // Register temporary document providers
      // (Note: This is simplified; in production you'd register proper content providers)
      
      await vscode.commands.executeCommand(
        'vscode.diff',
        uri,
        modifiedUri,
        `Clio Preview: ${path.basename(filePath)}`
      );
    } catch (err) {
      console.error('[EditApplier] Error previewing edit:', err);
    }
  }
}

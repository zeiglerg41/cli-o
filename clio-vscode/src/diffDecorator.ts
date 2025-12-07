/**
 * DiffDecorator - Highlights changed lines with green background and hover tooltip
 */
import * as vscode from 'vscode';

interface DiffEdit {
    range: {
        start: { line: number; character: number };
        end: { line: number; character: number };
    };
    oldText: string;
    newText: string;
}

interface PendingDiff {
    file: string;
    edits: DiffEdit[];
    description: string;
}

export class DiffDecorator {
    private pendingDiffs: Map<string, PendingDiff> = new Map();

    // Decoration type for changed lines (green highlight)
    private changedDecorationType: vscode.TextEditorDecorationType;

    constructor() {
        // Green background for changed lines with gutter marker
        this.changedDecorationType = vscode.window.createTextEditorDecorationType({
            backgroundColor: 'rgba(0, 255, 0, 0.15)',
            isWholeLine: true,
            gutterIconPath: vscode.Uri.parse('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIGZpbGw9IiM2Njk5NjYiLz48L3N2Zz4='),
            gutterIconSize: 'contain',
        });
    }

    /**
     * Show highlight for changed lines with hover tooltip
     */
    async showDiff(file: string, edits: DiffEdit[], description: string): Promise<void> {
        const uri = vscode.Uri.file(file);

        // Open the file
        const document = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(document);

        const decorations: vscode.DecorationOptions[] = [];

        // Highlight each changed line with tooltip showing old text
        for (const edit of edits) {
            const lineRange = new vscode.Range(
                new vscode.Position(edit.range.start.line, 0),
                new vscode.Position(edit.range.start.line, Number.MAX_SAFE_INTEGER)
            );

            // Create hover message showing old text
            const hoverMessage = new vscode.MarkdownString();
            hoverMessage.appendMarkdown(`**Clio Edit:** ${description}\n\n`);
            hoverMessage.appendMarkdown(`**Previous text:**\n\`\`\`\n${edit.oldText}\n\`\`\`\n\n`);
            hoverMessage.appendMarkdown(`**New text:**\n\`\`\`\n${edit.newText}\n\`\`\``);

            decorations.push({
                range: lineRange,
                hoverMessage: hoverMessage,
            });
        }

        // Apply decorations
        editor.setDecorations(this.changedDecorationType, decorations);

        // Store pending diff for undo
        this.pendingDiffs.set(file, {
            file,
            edits,
            description,
        });

        console.log(`[DiffDecorator] Showing ${edits.length} change(s) for ${file}`);
    }

    /**
     * Clear decorations (when user clicks "Undo")
     */
    async clearDiff(file: string): Promise<boolean> {
        const pending = this.pendingDiffs.get(file);
        if (!pending) {
            return false;
        }

        const uri = vscode.Uri.file(file);
        const document = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(document);

        // Clear decorations
        editor.setDecorations(this.changedDecorationType, []);

        // Clean up
        this.pendingDiffs.delete(file);

        console.log(`[DiffDecorator] Cleared decorations for ${file}`);
        return true;
    }

    /**
     * Undo the changes using VS Code's undo command
     */
    async undoDiff(file: string): Promise<boolean> {
        const pending = this.pendingDiffs.get(file);
        if (!pending) {
            return false;
        }

        // Clear decorations first
        await this.clearDiff(file);

        // Execute undo command
        await vscode.commands.executeCommand('undo');

        console.log(`[DiffDecorator] Undid changes for ${file}`);
        return true;
    }

    /**
     * Check if there's a pending diff for a file
     */
    hasPendingDiff(file: string): boolean {
        return this.pendingDiffs.has(file);
    }

    /**
     * Get pending diff for a file
     */
    getPendingDiff(file: string): PendingDiff | undefined {
        return this.pendingDiffs.get(file);
    }

    /**
     * Dispose all decorations
     */
    dispose(): void {
        this.changedDecorationType.dispose();
        this.pendingDiffs.clear();
    }
}

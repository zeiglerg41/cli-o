/**
 * DiffCodeLensProvider - Provides Keep/Undo CodeLens buttons above each edit chunk
 */
import * as vscode from 'vscode';
import { DiffDecorator } from './diffDecorator';

export class DiffCodeLensProvider implements vscode.CodeLensProvider {
    private _onDidChangeCodeLenses: vscode.EventEmitter<void> = new vscode.EventEmitter<void>();
    public readonly onDidChangeCodeLenses: vscode.Event<void> = this._onDidChangeCodeLenses.event;

    constructor(private diffDecorator: DiffDecorator) {}

    /**
     * Trigger CodeLens refresh
     */
    public refresh(): void {
        this._onDidChangeCodeLenses.fire();
    }

    /**
     * Provide CodeLenses for pending diffs
     */
    provideCodeLenses(document: vscode.TextDocument, token: vscode.CancellationToken): vscode.CodeLens[] | Thenable<vscode.CodeLens[]> {
        const file = document.uri.fsPath;
        const pending = this.diffDecorator.getPendingDiff(file);

        if (!pending || pending.edits.length === 0) {
            return [];
        }

        const codeLenses: vscode.CodeLens[] = [];

        // Add "Keep All / Undo All" at the top of the first edit
        if (pending.edits.length > 0) {
            const firstEdit = pending.edits[0];
            const topRange = new vscode.Range(
                new vscode.Position(firstEdit.range.start.line, 0),
                new vscode.Position(firstEdit.range.start.line, 0)
            );

            // Keep All
            codeLenses.push(new vscode.CodeLens(topRange, {
                title: `✓ Keep All (${pending.edits.length})`,
                tooltip: 'Accept all changes',
                command: 'clio.acceptAllEdits',
                arguments: [file]
            }));

            // Undo All
            codeLenses.push(new vscode.CodeLens(topRange, {
                title: '✗ Undo All',
                tooltip: 'Reject all changes and revert to original',
                command: 'clio.rejectAllEdits',
                arguments: [file]
            }));
        }

        // Add individual Keep/Undo for each edit chunk
        pending.edits.forEach((edit, index) => {
            const range = new vscode.Range(
                new vscode.Position(edit.range.start.line, 0),
                new vscode.Position(edit.range.start.line, 0)
            );

            // Keep button
            codeLenses.push(new vscode.CodeLens(range, {
                title: '✓ Keep',
                tooltip: 'Accept this change',
                command: 'clio.acceptEdit',
                arguments: [file, index]
            }));

            // Undo button
            codeLenses.push(new vscode.CodeLens(range, {
                title: '✗ Undo',
                tooltip: 'Reject this change and revert',
                command: 'clio.rejectEdit',
                arguments: [file, index]
            }));
        });

        return codeLenses;
    }

    /**
     * Resolve CodeLens (already resolved in provideCodeLenses)
     */
    resolveCodeLens(codeLens: vscode.CodeLens, token: vscode.CancellationToken): vscode.CodeLens | Thenable<vscode.CodeLens> {
        return codeLens;
    }
}

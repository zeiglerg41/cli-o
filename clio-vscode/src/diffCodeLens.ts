/**
 * DiffCodeLensProvider - Provides Undo button above changed lines
 */
import * as vscode from 'vscode';
import { DiffDecorator } from './diffDecorator';

export class DiffCodeLensProvider implements vscode.CodeLensProvider {
    private _onDidChangeCodeLenses: vscode.EventEmitter<void> = new vscode.EventEmitter<void>();
    public readonly onDidChangeCodeLenses: vscode.Event<void> = this._onDidChangeCodeLenses.event;

    constructor(private diffDecorator: DiffDecorator) {}

    /**
     * Provide CodeLens items for files with pending diffs
     */
    provideCodeLenses(
        document: vscode.TextDocument,
        token: vscode.CancellationToken
    ): vscode.CodeLens[] | Thenable<vscode.CodeLens[]> {
        const codeLenses: vscode.CodeLens[] = [];
        const filePath = document.uri.fsPath;

        // Check if this file has a pending diff
        const pendingDiff = this.diffDecorator.getPendingDiff(filePath);
        if (!pendingDiff) {
            return codeLenses;
        }

        // Add Undo button above the first changed line
        if (pendingDiff.edits.length > 0) {
            const firstEdit = pendingDiff.edits[0];
            const range = new vscode.Range(
                firstEdit.range.start.line,
                0,
                firstEdit.range.start.line,
                0
            );

            // Accept button
            const acceptLens = new vscode.CodeLens(range, {
                title: '✓ Accept',
                tooltip: `Accept changes: ${pendingDiff.description}`,
                command: 'clio.acceptDiff',
                arguments: [filePath],
            });
            codeLenses.push(acceptLens);

            // Undo button
            const undoLens = new vscode.CodeLens(range, {
                title: '↶ Undo',
                tooltip: `Undo changes: ${pendingDiff.description}`,
                command: 'clio.undoDiff',
                arguments: [filePath],
            });
            codeLenses.push(undoLens);
        }

        return codeLenses;
    }

    /**
     * Refresh CodeLens display
     */
    refresh(): void {
        this._onDidChangeCodeLenses.fire();
    }
}

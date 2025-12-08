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

        // Add Accept All / Reject All buttons above the first changed line
        if (pendingDiff.edits.length > 0) {
            const firstEdit = pendingDiff.edits[0];
            const topRange = new vscode.Range(
                firstEdit.range.start.line,
                0,
                firstEdit.range.start.line,
                0
            );

            // Accept All button
            const acceptAllLens = new vscode.CodeLens(topRange, {
                title: `✓ Accept All (${pendingDiff.edits.length})`,
                tooltip: `Accept all changes: ${pendingDiff.description}`,
                command: 'clio.acceptAllEdits',
                arguments: [filePath],
            });
            codeLenses.push(acceptAllLens);

            // Reject All button
            const rejectAllLens = new vscode.CodeLens(topRange, {
                title: `✗ Reject All`,
                tooltip: `Reject all changes and undo: ${pendingDiff.description}`,
                command: 'clio.rejectAllEdits',
                arguments: [filePath],
            });
            codeLenses.push(rejectAllLens);
        }

        // Add individual Accept/Reject buttons for each edit
        pendingDiff.edits.forEach((edit, index) => {
            const range = new vscode.Range(
                edit.range.start.line,
                0,
                edit.range.start.line,
                0
            );

            // Accept this edit
            const acceptLens = new vscode.CodeLens(range, {
                title: '✓ Accept',
                tooltip: `Accept this change`,
                command: 'clio.acceptEdit',
                arguments: [filePath, index],
            });
            codeLenses.push(acceptLens);

            // Reject this edit
            const rejectLens = new vscode.CodeLens(range, {
                title: '✗ Reject',
                tooltip: `Reject this change`,
                command: 'clio.rejectEdit',
                arguments: [filePath, index],
            });
            codeLenses.push(rejectLens);
        });

        return codeLenses;
    }

    /**
     * Refresh CodeLens display
     */
    refresh(): void {
        this._onDidChangeCodeLenses.fire();
    }
}

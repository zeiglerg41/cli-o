"""IDE integration via CLI commands (like `code` for VS Code)."""
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class IDEIntegration:
    """Integrate with IDE using CLI commands."""

    def __init__(self, ide_type: str = "vscode"):
        """Initialize IDE integration."""
        self.ide_type = ide_type
        self.cli_command = self._detect_cli_command()

    def _detect_cli_command(self) -> Optional[str]:
        """Detect which IDE CLI is available."""
        # Try common CLI commands
        commands = ["code", "cursor", "code-insiders"]

        for cmd in commands:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        return None

    def is_available(self) -> bool:
        """Check if IDE CLI is available."""
        return self.cli_command is not None

    def apply_edit(self, file_path: str, old_content: str, new_content: str) -> bool:
        """Apply edit by showing diff in IDE."""
        if not self.cli_command:
            return False

        try:
            # Create temp files for diff
            with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as old_file:
                old_file.write(old_content)
                old_path = old_file.name

            with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as new_file:
                new_file.write(new_content)
                new_path = new_file.name

            # Show diff in IDE
            subprocess.run(
                [self.cli_command, "--diff", old_path, new_path],
                check=True,
                timeout=5
            )

            # Clean up temp files
            Path(old_path).unlink(missing_ok=True)
            Path(new_path).unlink(missing_ok=True)

            return True

        except Exception as e:
            print(f"Error showing diff: {e}")
            return False

    def open_file(self, file_path: str, line: Optional[int] = None) -> bool:
        """Open file in IDE at specific line."""
        if not self.cli_command:
            return False

        try:
            args = [self.cli_command]
            if line is not None:
                args.extend(["--goto", f"{file_path}:{line}"])
            else:
                args.append(file_path)

            subprocess.run(args, check=True, timeout=5)
            return True

        except Exception:
            return False

    def execute_command(self, command: str) -> bool:
        """Execute a command in the IDE."""
        if not self.cli_command:
            return False

        try:
            subprocess.run(
                [self.cli_command, "--command", command],
                check=True,
                timeout=5
            )
            return True

        except Exception:
            return False

"""VSCode extension protocol handler."""
import sys
import json
import asyncio
from typing import Dict, Any, Optional, Callable
from pathlib import Path


class VSCodeProtocol:
    """Handles JSON-based communication with VS Code extension via stdio."""

    def __init__(self, message_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        """Initialize protocol handler."""
        self.message_callback = message_callback
        self.running = False

    def send_message(self, message: Dict[str, Any]) -> None:
        """Send JSON message to VS Code extension via stdout."""
        try:
            json_str = json.dumps(message)
            # Write to stdout with newline delimiter
            sys.stdout.write(json_str + '\n')
            sys.stdout.flush()
        except Exception as e:
            self.send_error(f"Failed to send message: {str(e)}")

    def send_edit(self, file_path: str, edits: list) -> None:
        """Send edit message to VS Code."""
        self.send_message({
            "type": "edit",
            "file": str(Path(file_path).resolve()),
            "edits": edits
        })

    def send_response(self, content: str) -> None:
        """Send text response to VS Code."""
        self.send_message({
            "type": "response",
            "content": content
        })

    def send_status(self, activity: str) -> None:
        """Send status update to VS Code."""
        self.send_message({
            "type": "status",
            "activity": activity
        })

    def send_error(self, error: str) -> None:
        """Send error message to VS Code."""
        self.send_message({
            "type": "error",
            "error": error
        })

    def send_tool_execution(self, tool_name: str, arguments: Dict[str, Any], result: str) -> None:
        """Send tool execution notification to VS Code."""
        self.send_message({
            "type": "tool",
            "tool": tool_name,
            "arguments": arguments,
            "result": result
        })

    async def read_messages(self) -> None:
        """Read messages from stdin asynchronously."""
        self.running = True

        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # Read from stdin non-blocking
                line = await loop.run_in_executor(None, sys.stdin.readline)

                if not line:
                    # EOF reached
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse JSON
                try:
                    message = json.loads(line)
                    if self.message_callback:
                        self.message_callback(message)
                except json.JSONDecodeError as e:
                    self.send_error(f"Invalid JSON: {str(e)}")

            except Exception as e:
                self.send_error(f"Error reading message: {str(e)}")
                break

    def stop(self) -> None:
        """Stop reading messages."""
        self.running = False

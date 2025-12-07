"""Tools for the AI agent."""
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any
import aiofiles
from ..ide_bridge import get_bridge


class Tools:
    """Collection of tools for the agent."""

    def __init__(
        self,
        permission_callback: Optional[Callable[[str, str], Awaitable[bool]]] = None,
        vscode_protocol: Optional[Any] = None
    ):
        """Initialize tools."""
        self.permission_callback = permission_callback
        self.vscode_protocol = vscode_protocol
    
    async def request_permission(self, operation: str, details: str) -> bool:
        """Request permission for an operation."""
        if self.permission_callback:
            return await self.permission_callback(operation, details)
        return True  # Auto-approve if no callback
    
    async def read_file(self, path: str) -> str:
        """Read a file and return its contents."""
        try:
            file_path = Path(path).resolve()
            
            if not file_path.exists():
                return f"Error: File not found: {path}"
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
            
            return content
        except UnicodeDecodeError:
            return f"Error: Cannot read binary file: {path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    async def write_file(self, path: str, content: str) -> str:
        """Write content to a file."""
        try:
            file_path = Path(path).resolve()

            # Safety check - block writes to system directories
            protected_dirs = ["/etc", "/boot", "/sys", "/proc", "/dev", "/usr/bin", "/usr/sbin", "/bin", "/sbin"]
            for protected in protected_dirs:
                if str(file_path).startswith(protected):
                    return f"🚫 BLOCKED: Cannot write to system directory {protected}. This requires manual intervention."

            # Request permission
            operation = "write_file"
            details = f"Write to {path} ({len(content)} chars)"

            if not await self.request_permission(operation, details):
                return "Permission denied"

            # Create parent directories
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Decode escaped characters (handle LLMs that escape newlines)
            # Use encode/decode to convert literal \n to actual newlines
            try:
                content = content.encode().decode('unicode_escape')
            except Exception:
                # If decoding fails, use content as-is
                pass

            # Write file
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(content)

            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"
    
    async def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing old_text with new_text."""
        try:
            # Decode escaped characters in old_text and new_text
            try:
                old_text = old_text.encode().decode('unicode_escape')
            except Exception:
                pass

            try:
                new_text = new_text.encode().decode('unicode_escape')
            except Exception:
                pass

            # Read current content
            content = await self.read_file(path)

            if content.startswith("Error:"):
                return content

            # Check if old_text exists
            if old_text not in content:
                return f"Error: Text not found in file: {old_text[:100]}..."

            # Find position of old_text for VSCode range
            start_pos = content.find(old_text)
            lines_before = content[:start_pos].count('\n')
            char_in_line = start_pos - content[:start_pos].rfind('\n') - 1 if '\n' in content[:start_pos] else start_pos

            end_pos = start_pos + len(old_text)
            lines_in_old = old_text.count('\n')
            if '\n' in old_text:
                last_line_start = old_text.rfind('\n') + 1
                end_char = len(old_text) - last_line_start
            else:
                end_char = char_in_line + len(old_text)

            # If in VSCode mode, emit edit message instead of writing file
            if self.vscode_protocol:
                self.vscode_protocol.send_edit(
                    file_path=path,
                    edits=[{
                        "range": {
                            "start": {"line": lines_before, "character": max(0, char_in_line)},
                            "end": {"line": lines_before + lines_in_old, "character": end_char}
                        },
                        "newText": new_text
                    }]
                )
                return f"Successfully edited {path}"

            # Check for IDE bridge - propose diff with decorations
            bridge = get_bridge()
            if bridge.is_connected():
                # First apply the edit to the file
                new_content = content.replace(old_text, new_text, 1)
                file_path = Path(path).resolve()
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(new_content)

                # Then send proposeDiff to show decorations
                await bridge.propose_diff(
                    file_path=str(file_path),
                    edits=[{
                        "range": {
                            "start": {"line": lines_before, "character": max(0, char_in_line)},
                            "end": {"line": lines_before + lines_in_old, "character": end_char}
                        },
                        "oldText": old_text,
                        "newText": new_text
                    }],
                    description=f"Edit {Path(path).name}"
                )
                return f"Successfully edited {path} (hover over green highlight to see changes, click Undo to revert)"

            # Normal mode: write file
            new_content = content.replace(old_text, new_text, 1)

            # Request permission
            operation = "edit_file"
            details = f"Edit {path}: replace {len(old_text)} chars with {len(new_text)} chars"

            if not await self.request_permission(operation, details):
                return "Permission denied"

            # Write back - but skip the unicode_escape decode since we already did it above
            file_path = Path(path).resolve()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(new_content)

            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"
    
    async def execute_bash(self, command: str, timeout: int = 30) -> str:
        """Execute a bash command and return output."""
        try:
            # Safety check for dangerous commands
            dangerous_patterns = [
                "rm -rf /",
                "rm -rf /*",
                "rm -rf ~",
                "rm -rf $HOME",
                "> /dev/sda",
                "mkfs.",
                "dd if=",
                ":(){ :|:& };:",  # fork bomb
                "chmod -R 777 /",
                "/etc/passwd",
                "/etc/shadow",
                "curl | bash",
                "wget | sh",
            ]

            cmd_lower = command.lower().replace(" ", "")
            for pattern in dangerous_patterns:
                pattern_check = pattern.lower().replace(" ", "")
                if pattern_check in cmd_lower:
                    return f"🚫 BLOCKED: Command contains potentially dangerous pattern '{pattern}'. If you need to run this, please do it manually."

            # Request permission
            operation = "execute_bash"
            details = f"Run command: {command}"

            if not await self.request_permission(operation, details):
                return "Permission denied"

            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"Error: Command timed out after {timeout} seconds"
            
            output = stdout.decode('utf-8', errors='replace')
            error = stderr.decode('utf-8', errors='replace')
            
            result = []
            if output:
                result.append(f"Output:\n{output}")
            if error:
                result.append(f"Error:\n{error}")
            if process.returncode != 0:
                result.append(f"Exit code: {process.returncode}")
            
            return "\n".join(result) if result else "Command completed successfully"
        except Exception as e:
            return f"Error executing command: {str(e)}"
    
    async def list_directory(self, path: str = ".") -> str:
        """List contents of a directory."""
        try:
            dir_path = Path(path).resolve()
            
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"
            
            items = []
            for item in sorted(dir_path.iterdir()):
                if item.is_dir():
                    items.append(f"📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    items.append(f"📄 {item.name} ({size} bytes)")
            
            return "\n".join(items) if items else "Empty directory"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
    
    def get_tool_definitions(self) -> list[dict]:
        """Get OpenAI function definitions for tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file to read"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file to write"
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to write to the file"
                            }
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Edit a file by replacing text",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the file to edit"
                            },
                            "old_text": {
                                "type": "string",
                                "description": "Text to find and replace"
                            },
                            "new_text": {
                                "type": "string",
                                "description": "Text to replace with"
                            }
                        },
                        "required": ["path", "old_text", "new_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The bash command to execute"
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds (default: 30)",
                                "default": 30
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List contents of a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to the directory (default: current directory)",
                                "default": "."
                            }
                        }
                    }
                }
            }
        ]
    
    async def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by name."""
        if tool_name == "read_file":
            return await self.read_file(**arguments)
        elif tool_name == "write_file":
            return await self.write_file(**arguments)
        elif tool_name == "edit_file":
            return await self.edit_file(**arguments)
        elif tool_name == "execute_bash":
            return await self.execute_bash(**arguments)
        elif tool_name == "list_directory":
            return await self.list_directory(**arguments)
        else:
            return f"Error: Unknown tool: {tool_name}"

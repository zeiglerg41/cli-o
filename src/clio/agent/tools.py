"""Tools for the AI agent."""
import asyncio
import subprocess
import json
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any
import aiofiles
import httpx
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
        # Track pending edits for batching highlights
        self.pending_highlights = {}  # file_path -> list of edit ranges
    
    async def request_permission(self, operation: str, details: str) -> bool:
        """Request permission for an operation."""
        if self.permission_callback:
            return await self.permission_callback(operation, details)
        return True  # Auto-approve if no callback

    def clear_highlights(self, file_path: str = None) -> None:
        """Clear pending highlights for a file (or all files if None)."""
        if file_path:
            self.pending_highlights.pop(str(Path(file_path).resolve()), None)
        else:
            self.pending_highlights.clear()
    
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
                file_path_str = str(file_path)
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                    await f.write(new_content)

                # Wait a moment for the file watcher to detect the change
                import asyncio
                await asyncio.sleep(0.1)

                # Calculate line numbers based on NEW content (after previous edits)
                newline_count = new_text.count('\n')

                # Calculate end line and character
                if '\n' in new_text:
                    # Multi-line: end line is start + number of newlines
                    # End character is the position after the last newline
                    last_line_start = new_text.rfind('\n') + 1
                    end_char_new = len(new_text) - last_line_start
                    end_line = lines_before + newline_count
                else:
                    # Single line: end is on the same line
                    end_char_new = char_in_line + len(new_text)
                    end_line = lines_before

                # Add this edit to pending highlights
                current_edit = {
                    "range": {
                        "start": {"line": lines_before, "character": max(0, char_in_line)},
                        "end": {"line": end_line, "character": end_char_new}
                    },
                    "oldText": old_text,
                    "newText": new_text
                }

                if file_path_str not in self.pending_highlights:
                    self.pending_highlights[file_path_str] = []
                self.pending_highlights[file_path_str].append(current_edit)

                # Send proposeDiff with ALL accumulated edits for this file
                await bridge.propose_diff(
                    file_path=file_path_str,
                    edits=self.pending_highlights[file_path_str],
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

    async def grep_files(self, pattern: str, path: str = ".", file_pattern: str = "*") -> str:
        """Search for a pattern in files using grep.

        Args:
            pattern: The regex pattern to search for
            path: Directory to search in (default: current directory)
            file_pattern: File pattern to match (e.g., "*.py", "*.js")
        """
        try:
            # Use ripgrep if available, otherwise fall back to grep
            cmd = f"rg --no-heading --line-number --color never '{pattern}' '{path}' --glob '{file_pattern}' 2>/dev/null || grep -rn '{pattern}' {path} --include='{file_pattern}' 2>/dev/null"
            result = await self.execute_bash(cmd, timeout=10)

            if "Error:" in result or not result.strip():
                return f"No matches found for pattern '{pattern}'"

            return result
        except Exception as e:
            return f"Error searching files: {str(e)}"

    async def find_files(self, name_pattern: str = "*", path: str = ".", file_type: str = "f") -> str:
        """Find files matching a pattern.

        Args:
            name_pattern: File name pattern (e.g., "*.py", "auth*")
            path: Directory to search in (default: current directory)
            file_type: Type of file (f=file, d=directory, default: f)
        """
        try:
            cmd = f"find '{path}' -type {file_type} -name '{name_pattern}' 2>/dev/null | head -100"
            result = await self.execute_bash(cmd, timeout=10)

            if "Error:" in result or not result.strip():
                return f"No files found matching pattern '{name_pattern}'"

            return result
        except Exception as e:
            return f"Error finding files: {str(e)}"

    async def web_search(self, query: str, num_results: int = 5) -> str:
        """Search the web and return links and titles.

        Args:
            query: The search query
            num_results: Number of results to return (default: 5, max: 10)
        """
        try:
            num_results = min(num_results, 10)  # Cap at 10

            # Use DuckDuckGo HTML search (no API key needed)
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CLIO/1.0)"}
                )

                if response.status_code != 200:
                    return f"Error: Search failed with status {response.status_code}"

                html = response.text

                # Simple parsing of DuckDuckGo results
                results = []
                import re
                from urllib.parse import urlparse, parse_qs

                # Find result links and titles
                pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
                matches = re.findall(pattern, html, re.DOTALL)

                for url, title in matches[:num_results]:
                    # Clean up title (remove HTML tags)
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    # Decode HTML entities
                    import html as html_lib
                    title = html_lib.unescape(title)
                    url = html_lib.unescape(url)

                    # Extract actual URL from DuckDuckGo redirect
                    if 'duckduckgo.com/l/' in url:
                        try:
                            # Parse the redirect URL to extract the uddg parameter
                            parsed = urlparse(url)
                            params = parse_qs(parsed.query)
                            if 'uddg' in params:
                                url = params['uddg'][0]
                        except:
                            pass  # If extraction fails, use original URL

                    # Ensure URL has protocol
                    if url.startswith('//'):
                        url = 'https:' + url
                    elif not url.startswith(('http://', 'https://')):
                        url = 'https://' + url

                    results.append(f"[{title}]({url})")

                if not results:
                    return f"No search results found for: {query}"

                return "\n".join([f"{i+1}. {r}" for i, r in enumerate(results)])

        except Exception as e:
            return f"Error searching web: {str(e)}"

    async def web_fetch(self, url: str, question: str = "") -> str:
        """Fetch content from a URL and optionally answer a question about it.

        Args:
            url: The URL to fetch
            question: Optional question to answer about the page content
        """
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CLIO/1.0)"}
                )

                # Report HTTP status like Claude Code
                status_messages = {
                    200: "200 OK",
                    301: "301 Moved Permanently",
                    302: "302 Found",
                    404: "404 Not Found",
                    403: "403 Forbidden",
                    500: "500 Internal Server Error",
                    503: "503 Service Unavailable"
                }
                status_msg = status_messages.get(response.status_code, f"{response.status_code}")

                if response.status_code != 200:
                    return f"HTTP {status_msg}\n\nFailed to fetch URL: {url}"

                content_type = response.headers.get("content-type", "")

                if "text/html" in content_type:
                    # Parse HTML to text
                    html = response.text

                    # Simple HTML to text conversion
                    import re
                    # Remove script and style tags
                    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    # Remove HTML tags
                    text = re.sub(r'<[^>]+>', ' ', text)
                    # Decode HTML entities
                    import html as html_lib
                    text = html_lib.unescape(text)
                    # Clean up whitespace
                    text = re.sub(r'\s+', ' ', text).strip()

                    # Truncate to 100KB
                    max_length = 100_000
                    if len(text) > max_length:
                        text = text[:max_length] + "\n\n[Content truncated - exceeded 100KB]"

                    # RAG-style structured format with strict grounding instructions
                    result = f"""HTTP {status_msg}

=== RETRIEVED SOURCE: {url} ===
{text}
=== END SOURCE ===

CRITICAL GROUNDING RULES FOR THIS RESPONSE:
- You MUST use ONLY the information in the source above
- Every claim MUST include (Source: {url})
- Quote directly when possible: "According to {url}, '[exact quote]'"
- If information is NOT in the source, respond: "I couldn't find this information in the source"
- NEVER add information from your training data or make assumptions"""

                    if question:
                        result += f"\n\nQuestion to answer using ONLY the source above: {question}"

                    return result

                elif "application/json" in content_type:
                    # Return JSON formatted
                    try:
                        data = response.json()
                        return f"""HTTP {status_msg}

=== RETRIEVED SOURCE: {url} ===
{json.dumps(data, indent=2)}
=== END SOURCE ===

CRITICAL GROUNDING RULES:
- Use ONLY the JSON data above
- Cite as: (Source: {url})
- If data is missing, say "I couldn't find this in the source\""""
                    except:
                        return f"HTTP {status_msg}\n\nContent from {url}:\n\n{response.text}"

                else:
                    # Plain text or other
                    text = response.text[:100_000]
                    return f"""HTTP {status_msg}

=== RETRIEVED SOURCE: {url} ===
{text}
=== END SOURCE ===

CRITICAL GROUNDING RULES:
- Use ONLY the content above
- Cite as: (Source: {url})"""

        except Exception as e:
            return f"Error fetching URL: {str(e)}"
    
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
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_files",
                    "description": "Search for a pattern in files. Use this to find code containing specific text, functions, classes, or keywords.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "The regex pattern to search for (e.g., 'def authenticate', 'class User', 'import requests')"
                            },
                            "path": {
                                "type": "string",
                                "description": "Directory to search in (default: current directory)",
                                "default": "."
                            },
                            "file_pattern": {
                                "type": "string",
                                "description": "File pattern to match (e.g., '*.py', '*.js', '*.rs')",
                                "default": "*"
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "find_files",
                    "description": "Find files by name pattern. Use this to locate files when you don't know their exact path.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_pattern": {
                                "type": "string",
                                "description": "File name pattern (e.g., '*.py', 'auth*', 'test_*.js')",
                                "default": "*"
                            },
                            "path": {
                                "type": "string",
                                "description": "Directory to search in (default: current directory)",
                                "default": "."
                            },
                            "file_type": {
                                "type": "string",
                                "description": "Type of file (f=file, d=directory)",
                                "default": "f"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information. Returns links and titles of search results. Use this when you need current information, documentation, or answers not in the codebase.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query (e.g., 'Python async best practices', 'React hooks tutorial')"
                            },
                            "num_results": {
                                "type": "integer",
                                "description": "Number of results to return (default: 5, max: 10)",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch and read content from a URL. Use this to read documentation, articles, or specific pages found via web_search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to fetch"
                            },
                            "question": {
                                "type": "string",
                                "description": "Optional question to answer about the page content",
                                "default": ""
                            }
                        },
                        "required": ["url"]
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
        elif tool_name == "grep_files":
            return await self.grep_files(**arguments)
        elif tool_name == "find_files":
            return await self.find_files(**arguments)
        elif tool_name == "web_search":
            return await self.web_search(**arguments)
        elif tool_name == "web_fetch":
            return await self.web_fetch(**arguments)
        else:
            return f"Error: Unknown tool: {tool_name}"

"""Tools for the AI agent."""
import asyncio
import re
import subprocess
import json
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any
import aiofiles
import httpx
from ..ide_bridge import get_bridge
from .command_safety import is_readonly_command, is_blocked


def _resolve_path(path: str) -> Path:
    """Resolve a model/user-supplied path robustly.

    Strips stray surrounding whitespace and expands a leading ``~`` (which
    ``Path.resolve()`` alone does NOT do) before resolving. A relative path or
    "." resolves against the current working directory, where clio was launched.
    """
    return Path(str(path).strip()).expanduser().resolve()


class Tools:
    """Collection of tools for the agent."""

    def __init__(
        self,
        permission_callback: Optional[Callable[[str, str, Optional[dict]], Awaitable[bool]]] = None,
        vscode_protocol: Optional[Any] = None
    ):
        """Initialize tools."""
        self.permission_callback = permission_callback
        self.vscode_protocol = vscode_protocol
        # Track pending edits for batching highlights
        self.pending_highlights = {}  # file_path -> list of edit ranges
        # Batching state
        self.in_batch = False
        self.batch_edits = {}  # file_path -> list of edits to send at end of batch
        # Task checklist maintained by the model via update_plan
        self.current_plan: Optional[dict] = None
    
    async def request_permission(self, operation: str, details: str, diff_info: dict = None) -> bool:
        """Request permission for an operation."""
        if self.permission_callback:
            return await self.permission_callback(operation, details, diff_info)
        return True  # Auto-approve if no callback

    def begin_batch(self) -> None:
        """Start batching edit operations."""
        self.in_batch = True
        self.batch_edits.clear()

    async def end_batch(self) -> None:
        """End batching and send all accumulated edits."""
        self.in_batch = False

        # Send all batched edits per file
        bridge = get_bridge()
        if bridge.is_connected():
            for file_path, edits in self.batch_edits.items():
                if edits:
                    # Clear old decorations first
                    await bridge.clear_diff(file_path)

                    # Send all edits for this file
                    await bridge.propose_diff(
                        file_path=file_path,
                        edits=edits,
                        description=f"Edit {Path(file_path).name}"
                    )

        # Clear batch state
        self.batch_edits.clear()

    def clear_highlights(self, file_path: str = None) -> None:
        """Clear pending highlights for a file (or all files if None)."""
        if file_path:
            self.pending_highlights.pop(str(Path(file_path).resolve()), None)
        else:
            self.pending_highlights.clear()
    
    async def read_file(self, path: str) -> str:
        """Read a file and return its contents."""
        try:
            file_path = _resolve_path(path)
            
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
            file_path = _resolve_path(path)

            # Safety check - block writes to system directories
            protected_dirs = ["/etc", "/boot", "/sys", "/proc", "/dev", "/usr/bin", "/usr/sbin", "/bin", "/sbin"]
            for protected in protected_dirs:
                if str(file_path).startswith(protected):
                    return f"BLOCKED: Cannot write to system directory {protected}. This requires manual intervention."

            # Request permission. Pass the existing content (if any) and the new
            # content so the UI can show a diff preview of what will change.
            existing = ""
            if file_path.exists():
                try:
                    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                        existing = await f.read()
                except Exception:
                    existing = ""
            operation = "write_file"
            verb = "Overwrite" if existing else "Create"
            details = f"{verb} {path} ({len(content)} chars)"
            diff_info = {"path": str(file_path), "old": existing, "new": content}

            if not await self.request_permission(operation, details, diff_info):
                return "Permission denied"

            # Create parent directories
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file with explicit UTF-8 encoding to preserve emojis and Unicode
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(content)

            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"
    
    async def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        """Edit a file by replacing old_text with new_text."""
        try:
            # Read current content (already uses UTF-8 encoding)
            content = await self.read_file(path)

            if content.startswith("Error:"):
                return content

            # Check if old_text exists
            if old_text not in content:
                return f"Error: Text not found in file: {old_text[:100]}..."

            # Request permission BEFORE making any changes (works for both IDE and normal mode)
            operation = "edit_file"
            details = f"Edit {path}: replace {len(old_text)} chars with {len(new_text)} chars"
            diff_info = {"old": old_text, "new": new_text}

            if not await self.request_permission(operation, details, diff_info):
                return "Permission denied"

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
                file_path = _resolve_path(path)
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

                # Create edit object
                current_edit = {
                    "range": {
                        "start": {"line": lines_before, "character": max(0, char_in_line)},
                        "end": {"line": end_line, "character": end_char_new}
                    },
                    "oldText": old_text,
                    "newText": new_text
                }

                # Handle batching vs immediate send
                if self.in_batch:
                    # Accumulate edit for batch send
                    if file_path_str not in self.batch_edits:
                        self.batch_edits[file_path_str] = []
                    self.batch_edits[file_path_str].append(current_edit)
                    return f"Successfully edited {path} (batched)"
                else:
                    # Immediate send (old behavior for single edits)
                    # CRITICAL: Clear old pending highlights for this file before adding new one
                    # This prevents accumulating edits from previous operations
                    self.pending_highlights[file_path_str] = []
                    self.pending_highlights[file_path_str].append(current_edit)

                    # Clear old decorations in VSCode before proposing new diff
                    await bridge.clear_diff(file_path_str)

                    # Send proposeDiff with this single edit
                    await bridge.propose_diff(
                        file_path=file_path_str,
                        edits=self.pending_highlights[file_path_str],
                        description=f"Edit {Path(path).name}"
                    )
                    return f"Successfully edited {path} (hover over green highlight to see changes, click Undo to revert)"

            # Normal mode: write file
            new_content = content.replace(old_text, new_text, 1)

            # Write back - but skip the unicode_escape decode since we already did it above
            file_path = _resolve_path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(new_content)

            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"
    
    async def execute_bash(self, command: str, timeout: int = 30) -> str:
        """Execute a bash command and return output."""
        try:
            # Refuse catastrophic commands outright.
            blocked = is_blocked(command)
            if blocked:
                return f"BLOCKED: Command contains potentially dangerous pattern '{blocked}'. If you need to run this, please do it manually."

            # Request permission -- UNLESS the command is a known read-only one.
            # Local/open-weight models can't be fully trusted to pick safe
            # commands, so we use a conservative allowlist: auto-run only commands
            # whose every segment is read-only AND that contain no chaining,
            # redirects, command substitution, or sudo. Everything else is gated.
            operation = "execute_bash"
            details = f"Run command: {command}"

            if not is_readonly_command(command):
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
            dir_path = _resolve_path(path)

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
            # ripgrep if available, else grep. --smart-case = case-insensitive unless
            # the pattern contains uppercase, so lowercase terms match any case while
            # an explicit "FooBar" stays precise. Skip node_modules/.git noise.
            cmd = (
                f"rg --no-heading --line-number --color never --smart-case "
                f"--glob '!node_modules' --glob '!.git' --glob '!.claude' '{pattern}' '{path}' "
                f"--glob '{file_pattern}' 2>/dev/null "
                f"|| grep -rni '{pattern}' {path} --include='{file_pattern}' "
                f"--exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.claude 2>/dev/null"
            )
            result = await self.execute_bash(cmd, timeout=10)

            if "Error:" in result or not result.strip():
                return (f"No matches for '{pattern}' (searched case-smart). Try a shorter "
                        f"pattern, remove the file filter, or broaden the path.")

            return result
        except Exception as e:
            return f"Error searching files: {str(e)}"

    async def find_files(self, name_pattern: str = "*", path: str = ".", file_type: str = "f") -> str:
        """Find files by name (case-insensitive substring match by default).

        Args:
            name_pattern: Name or partial name. A bare term like "header" matches
                "Header.jsx" (case-insensitive substring); globs ("*.py") also work.
            path: Directory to search in (default: current directory)
            file_type: f=file, d=directory (default: f)
        """
        try:
            pat = (name_pattern or "*").strip()
            # Forgiving match: a bare term (no glob chars) becomes a case-insensitive
            # substring, so "header" finds "Header.jsx" instead of returning nothing.
            if not any(ch in pat for ch in "*?["):
                pat = f"*{pat}*"
            prune = r"\( -name node_modules -o -name .git -o -name .next -o -name .claude \) -prune"
            cmd = (
                f"find '{path}' {prune} -o -type {file_type} -iname '{pat}' -print "
                f"2>/dev/null | head -100"
            )
            result = await self.execute_bash(cmd, timeout=10)

            if "Error:" in result or not result.strip():
                return (f"No files found matching '{name_pattern}' "
                        f"(searched case-insensitively as '{pat}'). Try a shorter term, "
                        f"or list_directory to orient.")

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
    
    PLAN_STATUS_ICONS = {"pending": "○", "in_progress": "→", "completed": "✔"}

    def render_plan(self) -> str:
        """Render the current plan as a checklist, or '' if none."""
        if not self.current_plan:
            return ""
        lines = []
        for item in self.current_plan["plan"]:
            icon = self.PLAN_STATUS_ICONS.get(item["status"], "○")
            lines.append(f"{icon} {item['step']}")
        return "\n".join(lines)

    async def update_plan(self, plan: list, explanation: str = "") -> str:
        """Update the task plan/checklist (schema follows Codex CLI's update_plan)."""
        valid_statuses = set(self.PLAN_STATUS_ICONS)
        if not isinstance(plan, list) or not plan:
            return "Error: 'plan' must be a non-empty list of {step, status} items"
        in_progress = 0
        for item in plan:
            if not isinstance(item, dict) or not item.get("step"):
                return "Error: each plan item needs a non-empty 'step' string"
            status = item.get("status", "pending")
            if status not in valid_statuses:
                return f"Error: invalid status '{status}' (use pending, in_progress, or completed)"
            item["status"] = status
            in_progress += status == "in_progress"
        if in_progress > 1:
            return "Error: at most one step can be in_progress at a time"
        self.current_plan = {"explanation": explanation, "plan": plan}
        return f"Plan updated:\n{self.render_plan()}"

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
                    "description": "Search file contents for a regex pattern. Case-insensitive unless your pattern contains uppercase (smart-case), so lowercase terms match any casing. Searches recursively and skips node_modules/.git. If you get no matches, broaden it: shorten the pattern, drop the file_pattern filter, or search a parent directory before concluding the code isn't there.",
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
                    "description": "Find files by name when you don't know the exact path. Matching is case-insensitive substring by default: pass a short partial term like 'header' (it finds 'Header.jsx'), 'map', or 'config' — you do NOT need exact names, casing, or wildcards. Skips node_modules/.git. If empty, try a shorter term or list_directory to orient; don't assume a file is absent after one narrow guess.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_pattern": {
                                "type": "string",
                                "description": "Name or partial name, e.g. 'header' (matches Header.jsx), 'map', or a glob like '*.py'. Bare terms match case-insensitively as substrings.",
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
            },
            {
                "type": "function",
                "function": {
                    "name": "update_plan",
                    "description": (
                        "Updates the task plan/checklist. Provide an optional explanation and "
                        "the full list of plan items, each with a step and status. "
                        "At most one step can be in_progress at a time. "
                        "Use this at the start of multi-step tasks and update statuses as you work."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "explanation": {
                                "type": "string",
                                "description": "Optional explanation for this plan update"
                            },
                            "plan": {
                                "type": "array",
                                "description": "The complete list of steps",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step": {
                                            "type": "string",
                                            "description": "Task step text"
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed"],
                                            "description": "Step status"
                                        }
                                    },
                                    "required": ["step", "status"]
                                }
                            }
                        },
                        "required": ["plan"]
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
        elif tool_name == "update_plan":
            return await self.update_plan(**arguments)
        else:
            return f"Error: Unknown tool: {tool_name}"

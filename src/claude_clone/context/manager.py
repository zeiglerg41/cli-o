"""Context manager for @file and @folder mentions."""
import asyncio
import os
from pathlib import Path
from typing import Dict, Set, Optional
import aiofiles
import tiktoken


class ContextManager:
    """Manages file and folder context."""

    def __init__(self, token_limit: int = 100000, working_dir: Optional[str] = None):
        """Initialize context manager."""
        self.files: Dict[str, str] = {}  # path -> content
        self.token_limit = token_limit
        self.encoding = tiktoken.get_encoding("cl100k_base")
        # Store the working directory when context manager is created
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
    
    async def add_file(self, path: str) -> str:
        """Add file to context."""
        # Try multiple resolution strategies
        file_path = Path(path)

        # Strategy 1: Try as absolute path
        if file_path.is_absolute() and file_path.exists():
            file_path = file_path.resolve()
        # Strategy 2: Try relative to stored working directory
        elif (self.working_dir / path).exists():
            file_path = (self.working_dir / path).resolve()
        # Strategy 3: Try relative to current working directory
        elif (Path.cwd() / path).exists():
            file_path = (Path.cwd() / path).resolve()
        # Strategy 4: Try as-is (might be relative to process cwd)
        elif file_path.exists():
            file_path = file_path.resolve()
        else:
            # Give helpful error with all paths tried
            return f"❌ File not found: {path}\nTried:\n  - {self.working_dir / path}\n  - {Path.cwd() / path}\n  - {file_path.absolute()}"
        
        if not file_path.is_file():
            return f"❌ Not a file: {path}"
        
        # Read file
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
        except UnicodeDecodeError:
            return f"❌ Cannot read binary file: {path}"
        except Exception as e:
            return f"❌ Error reading file: {e}"
        
        # Check tokens
        tokens = self.count_tokens(content)
        total_tokens = self.get_total_tokens() + tokens
        
        if total_tokens > self.token_limit:
            return f"❌ Adding file would exceed token limit ({total_tokens} > {self.token_limit})"
        
        # Add to context
        str_path = str(file_path)
        self.files[str_path] = content
        
        return f"✓ Added {path} ({tokens} tokens)"
    
    async def add_folder(self, path: str, pattern: str = "**/*") -> str:
        """Add folder to context."""
        folder_path = Path(path).resolve()
        
        if not folder_path.exists():
            return f"❌ Folder not found: {path}"
        
        if not folder_path.is_dir():
            return f"❌ Not a folder: {path}"
        
        # Find all files
        files = list(folder_path.glob(pattern))
        added = 0
        errors = []
        
        for file_path in files:
            if file_path.is_file():
                result = await self.add_file(str(file_path))
                if result.startswith("✓"):
                    added += 1
                else:
                    errors.append(result)
        
        if errors:
            return f"✓ Added {added} files from {path}\n" + "\n".join(errors[:5])
        
        return f"✓ Added {added} files from {path}"
    
    def remove_file(self, path: str) -> str:
        """Remove file from context."""
        file_path = str(Path(path).resolve())
        
        if file_path in self.files:
            del self.files[file_path]
            return f"✓ Removed {path}"
        
        return f"❌ File not in context: {path}"
    
    def list_files(self) -> list[str]:
        """List all files in context."""
        return list(self.files.keys())
    
    def get_file_content(self, path: str) -> Optional[str]:
        """Get file content."""
        file_path = str(Path(path).resolve())
        return self.files.get(file_path)
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))
    
    def get_total_tokens(self) -> int:
        """Get total tokens in context."""
        return sum(self.count_tokens(content) for content in self.files.values())
    
    def clear(self) -> None:
        """Clear all context."""
        self.files.clear()
    
    def format_context(self) -> str:
        """Format context for inclusion in prompt."""
        if not self.files:
            return ""
        
        parts = []
        for path, content in self.files.items():
            parts.append(f"=== {path} ===\n{content}\n")
        
        return "\n".join(parts)

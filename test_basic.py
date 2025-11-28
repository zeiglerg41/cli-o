#!/usr/bin/env python3
"""Basic test to verify imports and core functionality."""
import sys
import asyncio

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from claude_clone.config.manager import ConfigManager
        from claude_clone.config.schema import Config, ProviderConfig
        from claude_clone.providers import create_provider
        from claude_clone.context.manager import ContextManager
        from claude_clone.agent.tools import Tools
        from claude_clone.agent.core import Agent
        from claude_clone.commands.router import CommandRouter
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_config():
    """Test configuration system."""
    print("\nTesting configuration...")
    
    try:
        from claude_clone.config.manager import ConfigManager
        
        config_manager = ConfigManager()
        config = config_manager.load()
        
        assert "ollama-local" in config.providers
        assert config.defaults.provider == "ollama-local"
        assert config.defaults.model == "llama3.1:8b"
        
        print(f"✓ Config loaded: {config.defaults.provider}/{config.defaults.model}")
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False


def test_context_manager():
    """Test context manager."""
    print("\nTesting context manager...")
    
    try:
        from claude_clone.context.manager import ContextManager
        
        cm = ContextManager()
        
        # Test token counting
        tokens = cm.count_tokens("Hello, world!")
        assert tokens > 0
        
        print(f"✓ Context manager working (counted {tokens} tokens)")
        return True
    except Exception as e:
        print(f"✗ Context manager test failed: {e}")
        return False


def test_tools():
    """Test tools."""
    print("\nTesting tools...")
    
    try:
        from claude_clone.agent.tools import Tools
        
        tools = Tools()
        tool_defs = tools.get_tool_definitions()
        
        assert len(tool_defs) > 0
        assert any(t["function"]["name"] == "read_file" for t in tool_defs)
        
        print(f"✓ Tools initialized ({len(tool_defs)} tools available)")
        return True
    except Exception as e:
        print(f"✗ Tools test failed: {e}")
        return False


def test_command_router():
    """Test command router."""
    print("\nTesting command router...")
    
    try:
        from claude_clone.commands.router import CommandRouter
        
        router = CommandRouter()
        
        # Test parsing
        cmd, args, original = router.parse("/help")
        assert cmd == "/help"
        assert args == ""
        
        cmd, args, original = router.parse("/add file.txt")
        assert cmd == "/add"
        assert args == "file.txt"
        
        cmd, args, original = router.parse("regular message")
        assert cmd is None
        
        # Test @mentions
        mentions = router.extract_mentions("Fix @file.py and @folder/test.py")
        assert "file.py" in mentions
        assert "folder/test.py" in mentions
        
        print(f"✓ Command router working")
        return True
    except Exception as e:
        print(f"✗ Command router test failed: {e}")
        return False


async def test_file_operations():
    """Test file operations."""
    print("\nTesting file operations...")
    
    try:
        from claude_clone.agent.tools import Tools
        import tempfile
        import os
        
        tools = Tools()
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            temp_path = f.name
            f.write("Original content")
        
        try:
            # Test read
            content = await tools.read_file(temp_path)
            assert content == "Original content"
            
            # Test write
            result = await tools.write_file(temp_path, "New content")
            assert "Successfully" in result
            
            # Verify write
            content = await tools.read_file(temp_path)
            assert content == "New content"
            
            print(f"✓ File operations working")
            return True
        finally:
            os.unlink(temp_path)
            
    except Exception as e:
        print(f"✗ File operations test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Claude Clone - Basic Functionality Tests")
    print("=" * 60)
    
    results = []
    
    results.append(test_imports())
    results.append(test_config())
    results.append(test_context_manager())
    results.append(test_tools())
    results.append(test_command_router())
    results.append(asyncio.run(test_file_operations()))
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

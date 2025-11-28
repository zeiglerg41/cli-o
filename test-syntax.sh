#!/bin/bash
# Quick syntax check for claude-clone

echo "🔍 Testing Python syntax..."

# Test all modified Python files
FILES="src/claude_clone/agent/core.py src/claude_clone/agent/tools.py src/claude_clone/ui/app.py src/claude_clone/providers/openai_compatible.py"

for file in $FILES; do
    python3 -m py_compile "$file" 2>&1
    if [ $? -eq 0 ]; then
        echo "  ✓ $file"
    else
        echo "  ❌ $file - SYNTAX ERROR!"
        exit 1
    fi
done

echo ""
echo "✓✓✓ All syntax checks passed! Safe to run claude-clone ✓✓✓"

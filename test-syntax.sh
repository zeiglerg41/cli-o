#!/bin/bash
# Quick syntax check for CLIO

echo "🔍 Testing Python syntax..."

# Test all modified Python files
FILES="src/clio/agent/core.py src/clio/agent/tools.py src/clio/ui/app.py src/clio/providers/openai_compatible.py"

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
echo "✓✓✓ All syntax checks passed! Safe to run clio ✓✓✓"

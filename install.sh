#!/bin/bash
# Installation script for claude-clone

set -e

echo "🚀 Installing Claude Clone..."

# Check Python version
if ! command -v python3.11 &> /dev/null; then
    echo "❌ Python 3.11+ is required"
    echo "Please install Python 3.11 or higher"
    exit 1
fi

echo "✓ Python 3.11+ found"

# Install in development mode
echo "📦 Installing dependencies..."
pip install -e .

echo "✓ Installation complete!"
echo ""
echo "Run 'claude-clone' to start the application"
echo "Run 'claude-clone setup' to configure providers"
echo ""
echo "For Docker deployment:"
echo "  1. Run './mimic' to start in Docker"
echo "  2. Or use 'docker-compose up' for persistent container"

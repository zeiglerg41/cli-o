#!/bin/bash
# Installation script for CLIO

set -e

echo "🚀 Installing CLIO - Command Line Interactive Operator..."

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
echo "Run 'clio' to start the application"
echo "Run 'clio setup' to configure providers"
echo ""
echo "For Docker deployment:"
echo "  1. Run './mimic' to start in Docker"
echo "  2. Or use 'docker-compose up' for persistent container"

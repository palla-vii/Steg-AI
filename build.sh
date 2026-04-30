#!/bin/bash
set -e

# Install dependencies
pip install -r requirements.txt

# Create necessary directories
mkdir -p uploads results static

echo "Build complete!"
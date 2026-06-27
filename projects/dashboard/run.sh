#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "Installing dependencies..."
pip3 install -r requirements.txt -q
echo ""
echo "Starting Dream Big PM Dashboard..."
echo "Open http://localhost:8000 in your browser"
echo ""
python3 -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

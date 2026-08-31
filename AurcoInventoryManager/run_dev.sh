#!/usr/bin/env bash
# Run AURCO Inventory Manager from source (Linux/macOS dev testing)
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv; .venv/bin/pip install -r requirements.txt; }
exec .venv/bin/python main.py

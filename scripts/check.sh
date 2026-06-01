#!/usr/bin/env bash
# Run all enforcement gates. A red at any gate blocks merge (the laws, executable).
set -e
ruff check .
lint-imports
pytest tests/ -q -p no:cacheprovider
echo "All gates green."

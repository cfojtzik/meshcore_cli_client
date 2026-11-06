#!/usr/bin/env bash
set -e

# Directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if .venv exists
if [ -d "$DIR/.venv" ]; then
    PYTHON_EXEC="$DIR/.venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$DIR:$PYTHONPATH"

# Execute
exec "$PYTHON_EXEC" "$DIR/src/main.py" "$@"

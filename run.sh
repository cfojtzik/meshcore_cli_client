#!/usr/bin/env bash
set -e

# Directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$DIR/.venv"
PYTHON_EXEC="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$DIR/requirements.txt"
INSTALLED_REQUIREMENTS="$VENV_DIR/.requirements-installed.txt"

# Create an isolated environment instead of depending on system packages.
if [ ! -x "$PYTHON_EXEC" ]; then
    echo "Erstelle virtuelle Python-Umgebung in $VENV_DIR …"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        cat >&2 <<'EOF'
Fehler: Die virtuelle Umgebung konnte nicht erstellt werden.
Unter antiX/Debian werden dafür üblicherweise diese Pakete benötigt:
  sudo apt update
  sudo apt install python3-venv python3-pip
Anschließend ./run.sh erneut ausführen.
EOF
        exit 1
    fi
fi

if ! "$PYTHON_EXEC" -m pip --version >/dev/null 2>&1; then
    cat >&2 <<'EOF'
Fehler: pip fehlt in der virtuellen Python-Umgebung.
Unter antiX/Debian bitte python3-venv und python3-pip installieren,
danach das unvollständige .venv-Verzeichnis entfernen und ./run.sh erneut ausführen.
EOF
    exit 1
fi

# Install on first start, after requirements changes, or if imports are broken.
if [ ! -f "$INSTALLED_REQUIREMENTS" ] \
    || ! cmp -s "$REQUIREMENTS_FILE" "$INSTALLED_REQUIREMENTS" \
    || ! "$PYTHON_EXEC" -c 'import serial, meshcore_cli' >/dev/null 2>&1; then
    echo "Installiere Python-Abhängigkeiten …"
    if ! "$PYTHON_EXEC" -m pip install --disable-pip-version-check -r "$REQUIREMENTS_FILE"; then
        cat >&2 <<'EOF'
Fehler: Die Python-Abhängigkeiten konnten nicht installiert werden.
Bitte Internetverbindung und die oben ausgegebene pip-Fehlermeldung prüfen.
EOF
        exit 1
    fi
    cp "$REQUIREMENTS_FILE" "$INSTALLED_REQUIREMENTS"
fi

# Ensure PYTHONPATH includes project root
export PYTHONPATH="$DIR:$PYTHONPATH"

# Execute
exec "$PYTHON_EXEC" "$DIR/src/main.py" "$@"

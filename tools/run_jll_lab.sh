#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/Scripts/python.exe"
CONFIG="${JLL_CONFIG_PATH:-$ROOT/config/lab.json}"
IDENTITY="${JLL_IDENTITY_PATH:-$ROOT/config/users.lab.json}"

native_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  elif command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

if [[ ! -f "$PYTHON" ]]; then
  printf 'Chybí .venv. V Git Bash spusťte:\n' >&2
  printf '  py -3.11 -m venv .venv\n' >&2
  printf '  ./.venv/Scripts/python.exe -m pip install -e ".[test]"\n' >&2
  exit 2
fi

if ! "$PYTHON" -c "import PySide6, psycopg, psycopg_pool, argon2, keyring, jll"; then
  printf 'Chybí závislosti. Spusťte:\n' >&2
  printf '  ./.venv/Scripts/python.exe -m pip install -e ".[test]"\n' >&2
  exit 3
fi

if [[ -f "$CONFIG" ]]; then
  "$PYTHON" -m jll.gui.probe "$(native_path "$CONFIG")"
else
  printf 'LAB config chybí; aplikace otevře fail-closed Setup Wizard.\n'
fi

if [[ "${1:-}" == "--probe-only" ]]; then
  exit 0
fi

cd "$ROOT"
exec "$PYTHON" -m jll \
  --config "$(native_path "$CONFIG")" \
  --identity-store "$(native_path "$IDENTITY")"

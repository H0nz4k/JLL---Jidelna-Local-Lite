#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/Scripts/python.exe"
CONFIG="${JLL_CONFIG_PATH:-$ROOT/config/lab.json}"
HOST="${JLL_LAB_HOST:-127.0.0.1}"
PORT="${JLL_LAB_PORT:-5433}"
USER_NAME="${JLL_LAB_USER:-postgres}"
ADMIN_DB="${JLL_LAB_ADMIN_DATABASE:-postgres}"
TEMPLATE="${JLL_LAB_TEMPLATE:-}"

native_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  elif command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

# Konkrétní instalace není v repozitáři, proto se hodnoty berou z lokální
# konfigurace; `jll_demo_lab` je jen neutrální fallback.
config_value() {
  [[ -f "$CONFIG" ]] || return 1
  "$PYTHON" -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' \
    "$(native_path "$CONFIG")" "$1" | tr -d '\r'
}

[[ "$HOST" == "localhost" || "$HOST" == "127.0.0.1" || "$HOST" == "::1" ]] ||
  { printf 'LAB test runner odmítá non-local host.\n' >&2; exit 2; }
[[ -f "$PYTHON" ]] ||
  { printf 'Chybí .venv; spusťte ./tools/run_jll_lab.sh pro instrukce.\n' >&2; exit 2; }

if [[ -z "$TEMPLATE" ]]; then
  TEMPLATE="$(config_value database || true)"
fi
TEMPLATE="${TEMPLATE:-jll_demo_lab}"
[[ "$TEMPLATE" =~ ^jll_[A-Za-z0-9_]+$ ]] ||
  { printf 'LAB template musí začínat jll_.\n' >&2; exit 2; }

EXPECTED="${JLL_LAB_SYSTEM_IDENTIFIER:-}"
if [[ -z "$EXPECTED" ]]; then
  EXPECTED="$(config_value expected_system_identifier || true)"
fi
[[ "$EXPECTED" =~ ^[0-9]+$ ]] ||
  { printf 'Chybí ověřený JLL_LAB_SYSTEM_IDENTIFIER.\n' >&2; exit 2; }

"$PYTHON" -m jll.lab_cli \
  --host "$HOST" \
  --port "$PORT" \
  --user "$USER_NAME" \
  --admin-database "$ADMIN_DB" \
  --expected-system-identifier "$EXPECTED" \
  --required-database "$TEMPLATE"

export JLL_LAB_ADMIN_DSN="host=$HOST port=$PORT user=$USER_NAME dbname=$ADMIN_DB"
export JLL_LAB_TEMPLATE="$TEMPLATE"
export JLL_LAB_SYSTEM_IDENTIFIER="$EXPECTED"

cd "$ROOT"
exec "$PYTHON" -m pytest "$@"

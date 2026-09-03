#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/Scripts/python.exe"
CONFIG="${JLL_CONFIG_PATH:-$ROOT/config/lab.json}"
HOST="${JLL_LAB_HOST:-127.0.0.1}"
PORT="${JLL_LAB_PORT:-5433}"
USER_NAME="${JLL_LAB_USER:-postgres}"
ADMIN_DB="${JLL_LAB_ADMIN_DATABASE:-postgres}"
DATABASE="${JLL_LAB_DATABASE:-}"
DUMP_PATH="${JLL_DEMO_DUMP:-$ROOT/zdroje/demo.sql}"
EXPECTED="${JLL_LAB_SYSTEM_IDENTIFIER:-}"

# Název konkrétní LAB databáze nepatří do repozitáře; bere se z lokální
# konfigurace, `jll_demo_lab` je jen neutrální fallback.
if [[ -z "$DATABASE" && -f "$CONFIG" && -f "$PYTHON" ]]; then
  NATIVE_CONFIG="$CONFIG"
  if command -v cygpath >/dev/null 2>&1; then
    NATIVE_CONFIG="$(cygpath -w "$CONFIG")"
  fi
  DATABASE="$("$PYTHON" -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["database"])' \
    "$NATIVE_CONFIG" | tr -d '\r' || true)"
fi
DATABASE="${DATABASE:-jll_demo_lab}"

[[ "${JLL_CONFIRM_FRESH_RESTORE:-}" == "YES" ]] || {
  printf 'Destruktivní restore vyžaduje JLL_CONFIRM_FRESH_RESTORE=YES.\n' >&2
  exit 2
}
[[ "$HOST" == "localhost" || "$HOST" == "127.0.0.1" || "$HOST" == "::1" ]] ||
  { printf 'LAB restore odmítá non-local host.\n' >&2; exit 2; }
[[ "$DATABASE" =~ ^jll_[A-Za-z0-9_]+$ ]] ||
  { printf 'LAB databáze musí začínat jll_.\n' >&2; exit 2; }
[[ "$EXPECTED" =~ ^[0-9]+$ ]] ||
  { printf 'Chybí ověřený JLL_LAB_SYSTEM_IDENTIFIER.\n' >&2; exit 2; }
[[ -f "$DUMP_PATH" ]] ||
  { printf 'Dump nebyl nalezen: %s\n' "$DUMP_PATH" >&2; exit 2; }

IDENTITY="$(psql -X -w -h "$HOST" -p "$PORT" -U "$USER_NAME" -d "$ADMIN_DB" -Atc \
  "SELECT host(inet_server_addr()) || '|' || inet_server_port() || '|' ||
   (SELECT system_identifier::text FROM pg_control_system());" | tr -d '\r')"
IFS='|' read -r ACTUAL_HOST ACTUAL_PORT ACTUAL_ID <<<"$IDENTITY"
[[ "$ACTUAL_HOST" == "127.0.0.1" || "$ACTUAL_HOST" == "::1" ]] &&
  [[ "$ACTUAL_PORT" == "$PORT" ]] &&
  [[ "$ACTUAL_ID" == "$EXPECTED" ]] ||
  { printf 'Server-side LAB guard neprošel.\n' >&2; exit 3; }

printf 'Fresh restore pouze databáze %s na lokálním clusteru.\n' "$DATABASE"
psql -X -w -h "$HOST" -p "$PORT" -U "$USER_NAME" -d "$ADMIN_DB" \
  -v ON_ERROR_STOP=1 -v database_name="$DATABASE" -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE datname = :'database_name' AND pid <> pg_backend_pid();"
dropdb --if-exists -w -h "$HOST" -p "$PORT" -U "$USER_NAME" "$DATABASE"
createdb -w -h "$HOST" -p "$PORT" -U "$USER_NAME" "$DATABASE"

NATIVE_DUMP="$DUMP_PATH"
if command -v cygpath >/dev/null 2>&1; then
  NATIVE_DUMP="$(cygpath -w "$DUMP_PATH")"
fi
pg_restore --exit-on-error --no-owner --no-privileges -w \
  -h "$HOST" -p "$PORT" -U "$USER_NAME" -d "$DATABASE" "$NATIVE_DUMP"

psql -X -w -h "$HOST" -p "$PORT" -U "$USER_NAME" -d "$DATABASE" \
  -v ON_ERROR_STOP=1 <<'SQL'
DO $jll$
BEGIN
  IF to_regprocedure(
    'public.objednavka_plus(integer,integer,integer,character,integer,text)'
  ) IS NULL THEN
    RAISE EXCEPTION 'Chybí public.objednavka_plus.';
  END IF;
  IF to_regprocedure(
    'public.objednavka_minus(integer,integer,integer,character,integer,text)'
  ) IS NULL THEN
    RAISE EXCEPTION 'Chybí public.objednavka_minus.';
  END IF;
  IF to_regprocedure(
    'public.insert_udalost(text,text,text,text,text,integer,text,integer,text)'
  ) IS NULL THEN
    RAISE EXCEPTION 'Chybí public.insert_udalost.';
  END IF;
END
$jll$;
SQL
printf 'LAB restore dokončen: %s\n' "$DATABASE"

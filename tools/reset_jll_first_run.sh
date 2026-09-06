#!/usr/bin/env bash
# Reset lokálního JLL first-run stavu. NIKDY nemaže DB ani public.uzivatel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/Scripts/python.exe"
CONFIG="${JLL_CONFIG_PATH:-$ROOT/config/lab.json}"
IDENTITY="${JLL_IDENTITY_PATH:-$ROOT/config/users.lab.json}"
SECRETS_DIR="$ROOT/config/secrets"
BACKUP_DIR="$ROOT/config/backups"
DRY_RUN=0
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: ./tools/reset_jll_first_run.sh [--dry-run] [--yes]

Resetuje pouze lokální JLL first-run stav:
  - config/lab.json (+ timestamp backup)
  - config/users.lab.json (+ timestamp backup)
  - SUP secret (keyring + config/secrets/sup.*.hash)
  - DB password keyring entry (instance:user)

Nemaže PostgreSQL, public.uzivatel, strávníky, objednávky, čipy, stanice, udalosti.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Neznámý argument: %s\n' "$1" >&2; usage; exit 2 ;;
  esac
done

printf 'JLL first-run reset\n'
printf 'Root: %s\n' "$ROOT"
printf 'Plánované cíle:\n'
[[ -f "$CONFIG" ]] && printf '  - %s\n' "$CONFIG" || printf '  - %s (chybí)\n' "$CONFIG"
[[ -f "$IDENTITY" ]] && printf '  - %s\n' "$IDENTITY" || printf '  - %s (chybí)\n' "$IDENTITY"
printf '  - %s/sup.*.hash\n' "$SECRETS_DIR"
printf '  - keyring JidelnaLocalLite (SUP + DB heslo)\n'
printf 'Nemaže: PostgreSQL / public.uzivatel / provozní data\n'

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'DRY-RUN: nic nebylo změněno.\n'
  exit 0
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  printf 'Opravdu resetovat first-run stav? [y/N] '
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) printf 'Zrušeno.\n'; exit 1 ;;
  esac
fi

if [[ ! -f "$PYTHON" ]]; then
  printf 'Chybí .venv python: %s\n' "$PYTHON" >&2
  exit 2
fi

CONFIG_W="$(cygpath -w "$CONFIG" 2>/dev/null || printf '%s' "$CONFIG")"
IDENTITY_W="$(cygpath -w "$IDENTITY" 2>/dev/null || printf '%s' "$IDENTITY")"
SECRETS_W="$(cygpath -w "$SECRETS_DIR" 2>/dev/null || printf '%s' "$SECRETS_DIR")"
BACKUP_W="$(cygpath -w "$BACKUP_DIR" 2>/dev/null || printf '%s' "$BACKUP_DIR")"

"$PYTHON" - "$CONFIG_W" "$IDENTITY_W" "$SECRETS_W" "$BACKUP_W" <<'PY'
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

config_path = Path(sys.argv[1])
identity_path = Path(sys.argv[2])
secrets_dir = Path(sys.argv[3])
backup_dir = Path(sys.argv[4])
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir.mkdir(parents=True, exist_ok=True)

instance = ""
user = ""
if config_path.is_file():
    data = json.loads(config_path.read_text(encoding="utf-8"))
    instance = str(data.get("instance_id") or "")
    user = str(data.get("user") or "")
    target = backup_dir / f"{config_path.name}.{stamp}.bak"
    shutil.copy2(config_path, target)
    config_path.unlink()
    print(f"Backup+remove: {config_path} -> {target}")

if identity_path.is_file():
    target = backup_dir / f"{identity_path.name}.{stamp}.bak"
    shutil.copy2(identity_path, target)
    identity_path.unlink()
    print(f"Backup+remove: {identity_path} -> {target}")

if secrets_dir.is_dir():
    for path in secrets_dir.glob("sup.*.hash"):
        target = backup_dir / f"{path.name}.{stamp}.bak"
        shutil.copy2(path, target)
        path.unlink()
        print(f"Backup+remove: {path} -> {target}")

try:
    import keyring
except Exception as exc:
    print(f"keyring unavailable: {exc}")
else:
    service = "JidelnaLocalLite"
    usernames = []
    if instance:
        usernames.append(f"jll-sup:{instance}")
    if instance and user:
        usernames.append(f"{instance}:{user}")
    for username in usernames:
        try:
            keyring.delete_password(service, username)
            print(f"keyring deleted: {username}")
        except Exception:
            pass

print("Reset dokončen.")
PY

printf 'Spusťte: ./tools/run_jll_flet_lab.sh\n'

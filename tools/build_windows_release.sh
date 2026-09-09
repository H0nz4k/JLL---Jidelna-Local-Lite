#!/usr/bin/env bash
# Build Windows production candidate for JidelnaLocalLite (PyInstaller onedir + optional Inno Setup).
# Prefer Git Bash on Windows. May invoke pyinstaller.exe / ISCC.exe / signtool.exe.
# Does NOT claim a signed release. Does NOT upload binaries to VirusTotal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PRODUCT_NAME="JidelnaLocalLite"
RELEASE_VERSION="${JLL_RELEASE_VERSION:-0.6.0}"
SPEC="$ROOT/packaging/windows/JidelnaLocalLite.spec"
ISS="$ROOT/packaging/windows/JidelnaLocalLite.iss"
RELEASE_DIR="$ROOT/dist/release/${RELEASE_VERSION}"
ONEDIR_NAME="$PRODUCT_NAME"
VENV_DIR="${JLL_RELEASE_VENV:-$ROOT/.venv-release}"
CLEAN_VENV="${JLL_CLEAN_VENV:-1}"
SKIP_INNO="${JLL_SKIP_INNO:-0}"
SIGN_CERT="${JLL_SIGN_CERT:-}"
TIMESTAMP_URL="${JLL_TIMESTAMP_URL:-http://timestamp.digicert.com}"

native_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1"
  elif command -v wslpath >/dev/null 2>&1; then
    wslpath -w "$1"
  else
    printf '%s\n' "$1"
  fi
}

find_python() {
  if [[ -n "${JLL_RELEASE_PYTHON:-}" ]]; then
    printf '%s\n' "$JLL_RELEASE_PYTHON"
    return 0
  fi
  if command -v py >/dev/null 2>&1; then
    if py -3.12 -c "import sys" >/dev/null 2>&1; then
      printf '%s\n' "py -3.12"
      return 0
    fi
    if py -3.11 -c "import sys" >/dev/null 2>&1; then
      printf '%s\n' "py -3.11"
      return 0
    fi
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  return 1
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    "$VENV_PYTHON" -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path(r'''$file''').read_bytes()).hexdigest())"
  fi
}

find_iscc() {
  if command -v ISCC >/dev/null 2>&1; then
    command -v ISCC
    return 0
  fi
  if command -v ISCC.exe >/dev/null 2>&1; then
    command -v ISCC.exe
    return 0
  fi
  local candidate
  for candidate in \
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "/c/Program Files/Inno Setup 6/ISCC.exe" \
    "C:/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "C:/Program Files/Inno Setup 6/ISCC.exe" \
    "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" \
    "/c/Users/$USER/AppData/Local/Programs/Inno Setup 6/ISCC.exe"
  do
    if [[ -x "$candidate" || -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

find_signtool() {
  if command -v signtool >/dev/null 2>&1; then
    command -v signtool
    return 0
  fi
  if command -v signtool.exe >/dev/null 2>&1; then
    command -v signtool.exe
    return 0
  fi
  return 1
}

PYTHON_CMD="$(find_python)" || {
  printf 'ERROR: Python 3.11+ not found. Set JLL_RELEASE_PYTHON.\n' >&2
  exit 2
}

printf '==> JidelnaLocalLite Windows release scaffolding build\n'
printf 'Root: %s\n' "$ROOT"
printf 'Release version label: %s (scaffolding; package version may still be 0.5.x)\n' "$RELEASE_VERSION"
printf 'Python launcher: %s\n' "$PYTHON_CMD"

if [[ "$CLEAN_VENV" == "1" && -d "$VENV_DIR" ]]; then
  printf '==> Removing previous release venv: %s\n' "$VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  printf '==> Creating clean release venv: %s\n' "$VENV_DIR"
  # shellcheck disable=SC2086
  $PYTHON_CMD -m venv "$VENV_DIR"
fi

if [[ -f "$VENV_DIR/Scripts/python.exe" ]]; then
  VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
  PYINSTALLER="$VENV_DIR/Scripts/pyinstaller.exe"
elif [[ -f "$VENV_DIR/bin/python" ]]; then
  VENV_PYTHON="$VENV_DIR/bin/python"
  PYINSTALLER="$VENV_DIR/bin/pyinstaller"
else
  printf 'ERROR: release venv python missing under %s\n' "$VENV_DIR" >&2
  exit 3
fi

printf '==> Upgrading pip / installing package extras\n'
"$VENV_PYTHON" -m pip install --upgrade pip wheel setuptools
# Prefer production extra when defined; fall back to pdf (reportlab).
if "$VENV_PYTHON" -c "import tomllib, pathlib; p=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); raise SystemExit(0 if 'production' in p.get('project',{}).get('optional-dependencies',{}) else 1)"; then
  EXTRA="production"
else
  EXTRA="pdf"
fi
printf 'Installing editable package with extra: [%s]\n' "$EXTRA"
"$VENV_PYTHON" -m pip install -e ".[${EXTRA}]"
"$VENV_PYTHON" -m pip install "pyinstaller>=6.3,<8"

if [[ ! -f "$SPEC" ]]; then
  printf 'ERROR: missing PyInstaller spec: %s\n' "$SPEC" >&2
  exit 4
fi

printf '==> PyInstaller onedir\n'
rm -rf "$ROOT/build/$ONEDIR_NAME" "$ROOT/dist/$ONEDIR_NAME"
"$PYINSTALLER" --noconfirm --clean --distpath "$ROOT/dist" --workpath "$ROOT/build" "$(native_path "$SPEC")"

ONEDIR="$ROOT/dist/$ONEDIR_NAME"
EXE="$ONEDIR/${PRODUCT_NAME}.exe"
if [[ ! -f "$EXE" ]]; then
  printf 'ERROR: expected onedir exe missing: %s\n' "$EXE" >&2
  exit 5
fi

mkdir -p "$RELEASE_DIR"
# Stage onedir next to release metadata (copy for a self-contained folder).
STAGE_ONEDIR="$RELEASE_DIR/$ONEDIR_NAME"
rm -rf "$STAGE_ONEDIR"
cp -a "$ONEDIR" "$STAGE_ONEDIR"

SIGNATURE_STATUS="UNSIGNED"
SIGNTOOL_PATH=""
verify_signed() {
  local target="$1"
  "$SIGNTOOL_PATH" verify //pa //all //v "$(native_path "$target")"
}

# Sign EXACT onedir EXE payload BEFORE Inno packs it.
if [[ -n "$SIGN_CERT" ]]; then
  if SIGNTOOL_PATH="$(find_signtool)"; then
    printf '==> Signing onedir EXE payload before installer\n'
    if "$SIGNTOOL_PATH" sign //fd SHA256 //td SHA256 //tr "$TIMESTAMP_URL" //sha1 "$SIGN_CERT" "$(native_path "$STAGE_ONEDIR/${PRODUCT_NAME}.exe")"; then
      if verify_signed "$STAGE_ONEDIR/${PRODUCT_NAME}.exe"; then
        # Keep dist onedir in sync with signed staged payload.
        cp -f "$STAGE_ONEDIR/${PRODUCT_NAME}.exe" "$EXE"
        SIGNATURE_STATUS="SIGNED_EXE"
      else
        printf 'WARNING: EXE signature verify failed — artefacts remain UNSIGNED.\n' >&2
        SIGNATURE_STATUS="UNSIGNED"
      fi
    else
      printf 'WARNING: signtool failed on EXE — artefacts remain UNSIGNED.\n' >&2
    fi
  else
    printf 'WARNING: SIGN_CERT set but signtool.exe not found — UNSIGNED.\n' >&2
  fi
else
  printf '==> No JLL_SIGN_CERT — artefacts marked UNSIGNED (candidate only).\n'
fi

INSTALLER=""
ISCC_PATH=""
ISCC_VERSION="not-run"
if [[ "$SKIP_INNO" != "1" ]]; then
  if ISCC_PATH="$(find_iscc)"; then
    printf '==> Inno Setup via %s (packs already-signed EXE when available)\n' "$ISCC_PATH"
    "$ISCC_PATH" "$(native_path "$ISS")"
    INSTALLER="$RELEASE_DIR/${PRODUCT_NAME}-${RELEASE_VERSION}-Setup.exe"
    if [[ ! -f "$INSTALLER" ]]; then
      printf 'WARNING: ISCC finished but installer not found at %s\n' "$INSTALLER" >&2
      INSTALLER=""
    else
      ISCC_VERSION="$("$ISCC_PATH" 2>&1 | head -n 1 || true)"
      if [[ "$SIGNATURE_STATUS" == "SIGNED_EXE" && -n "$SIGNTOOL_PATH" ]]; then
        printf '==> Signing installer\n'
        if "$SIGNTOOL_PATH" sign //fd SHA256 //td SHA256 //tr "$TIMESTAMP_URL" //sha1 "$SIGN_CERT" "$(native_path "$INSTALLER")" \
          && verify_signed "$INSTALLER"; then
          SIGNATURE_STATUS="SIGNED"
        else
          printf 'WARNING: installer sign/verify failed — keep UNSIGNED claim.\n' >&2
          SIGNATURE_STATUS="UNSIGNED"
        fi
      fi
    fi
  else
    printf 'WARNING: ISCC not found — skipping installer. Install Inno Setup 6 or set PATH.\n' >&2
    ISCC_VERSION="missing"
  fi
else
  ISCC_VERSION="skipped"
fi

if [[ "$SIGNATURE_STATUS" == "SIGNED_EXE" ]]; then
  # EXE signed, installer missing/skipped — not a full signed release claim.
  SIGNATURE_STATUS="UNSIGNED"
fi

GIT_SHA="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
GIT_DESC="$(git describe --always --dirty 2>/dev/null || printf 'unknown')"
BUILD_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PY_VERSION="$("$VENV_PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PYSIDE_VERSION="$("$VENV_PYTHON" -c 'import PySide6; print(PySide6.__version__)')"
PKG_VERSION="$("$VENV_PYTHON" -c 'from jll.version import application_version; print(application_version())')"
PYI_VERSION="$("$VENV_PYTHON" -c 'import PyInstaller; print(PyInstaller.__version__)')"
REPORTLAB_VERSION="$("$VENV_PYTHON" -c 'import importlib.metadata as m; print(m.version("reportlab"))' 2>/dev/null || printf 'missing')"
ARCH="$("$VENV_PYTHON" -c 'import platform; print(platform.machine())')"

EXE_SHA="$(sha256_file "$STAGE_ONEDIR/${PRODUCT_NAME}.exe")"
INSTALLER_SHA="n/a"
if [[ -n "$INSTALLER" && -f "$INSTALLER" ]]; then
  INSTALLER_SHA="$(sha256_file "$INSTALLER")"
fi

BUILD_INFO="$RELEASE_DIR/BUILD_INFO.json"
INSTALLER_BASENAME=""
if [[ -n "$INSTALLER" && -f "$INSTALLER" ]]; then
  INSTALLER_BASENAME="$(basename "$INSTALLER")"
fi
export JLL_BI_PRODUCT_NAME="$PRODUCT_NAME"
export JLL_BI_RELEASE_VERSION="$RELEASE_VERSION"
export JLL_BI_PKG_VERSION="$PKG_VERSION"
export JLL_BI_GIT_SHA="$GIT_SHA"
export JLL_BI_GIT_DESC="$GIT_DESC"
export JLL_BI_BUILD_UTC="$BUILD_UTC"
export JLL_BI_PY_VERSION="$PY_VERSION"
export JLL_BI_PYSIDE_VERSION="$PYSIDE_VERSION"
export JLL_BI_REPORTLAB_VERSION="$REPORTLAB_VERSION"
export JLL_BI_PYI_VERSION="$PYI_VERSION"
export JLL_BI_ISCC_VERSION="$ISCC_VERSION"
export JLL_BI_ARCH="$ARCH"
export JLL_BI_SIGNATURE_STATUS="$SIGNATURE_STATUS"
export JLL_BI_EXE_SHA="$EXE_SHA"
export JLL_BI_INSTALLER_BASENAME="$INSTALLER_BASENAME"
export JLL_BI_INSTALLER_SHA="$INSTALLER_SHA"
export JLL_BI_BUILD_INFO="$BUILD_INFO"
"$VENV_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

installer_name = os.environ.get("JLL_BI_INSTALLER_BASENAME") or None
installer_sha = os.environ.get("JLL_BI_INSTALLER_SHA")
if not installer_name or installer_sha in (None, "", "n/a"):
    installer_name = None
    installer_sha = None

payload = {
    "product_name": os.environ["JLL_BI_PRODUCT_NAME"],
    "release_label": os.environ["JLL_BI_RELEASE_VERSION"],
    "package_version": os.environ["JLL_BI_PKG_VERSION"],
    "git_commit": os.environ["JLL_BI_GIT_SHA"],
    "git_describe": os.environ["JLL_BI_GIT_DESC"],
    "build_utc": os.environ["JLL_BI_BUILD_UTC"],
    "python_version": os.environ["JLL_BI_PY_VERSION"],
    "pyside6_version": os.environ["JLL_BI_PYSIDE_VERSION"],
    "reportlab_version": os.environ["JLL_BI_REPORTLAB_VERSION"],
    "pyinstaller_version": os.environ["JLL_BI_PYI_VERSION"],
    "inno_setup": os.environ["JLL_BI_ISCC_VERSION"],
    "architecture": os.environ["JLL_BI_ARCH"],
    "signature_status": os.environ["JLL_BI_SIGNATURE_STATUS"],
    "signed_release_claim": False,
    "smartscreen_risk": (
        "residual — unsigned or new publisher binaries may still "
        "trigger SmartScreen/AV warnings"
    ),
    "onedir_exe": "JidelnaLocalLite/JidelnaLocalLite.exe",
    "onedir_exe_sha256": os.environ["JLL_BI_EXE_SHA"],
    "installer": installer_name,
    "installer_sha256": installer_sha,
    "notes": [
        "Scaffolding candidate for 0.6.0 Windows production profile.",
        "Do not treat UNSIGNED artefacts as a signed release.",
        "No automatic DB migration is performed by the installer.",
    ],
}
Path(os.environ["JLL_BI_BUILD_INFO"]).write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

SUMS="$RELEASE_DIR/SHA256SUMS.txt"
{
  printf '# SHA256SUMS for %s release label %s\n' "$PRODUCT_NAME" "$RELEASE_VERSION"
  printf '# signature_status=%s\n' "$SIGNATURE_STATUS"
  printf '%s  %s/%s.exe\n' "$EXE_SHA" "$ONEDIR_NAME" "$PRODUCT_NAME"
  if [[ "$INSTALLER_SHA" != "n/a" ]]; then
    printf '%s  %s\n' "$INSTALLER_SHA" "$(basename "$INSTALLER")"
  else
    printf '# installer: not built (ISCC missing or skipped)\n'
  fi
} > "$SUMS"

printf '\n==> Done\n'
printf 'Release dir: %s\n' "$RELEASE_DIR"
printf 'Signature:   %s\n' "$SIGNATURE_STATUS"
printf 'BUILD_INFO:  %s\n' "$BUILD_INFO"
printf 'SHA256SUMS:  %s\n' "$SUMS"
if [[ "$SIGNATURE_STATUS" != "SIGNED" ]]; then
  printf '\n*** UNSIGNED CANDIDATE — not a signed production release ***\n'
fi

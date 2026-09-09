# RELEASE_VALIDATION — JidelnaLocalLite 0.6.0

**signature_status:** `UNSIGNED`  
**signed_release_claim:** `false`  
**overall production signed release:** `BLOCKED` (chybí Authenticode credential + ISCC)

## Gates

| Gate | Výsledek | Důkaz |
| --- | --- | --- |
| 0.5.8 multi-writer hardening | PASS (partial coverage MW-05/06/07) | unit + LAB integration oracles |
| produkční config ≠ jen vypnutý LAB | PASS | `lab_guard.assert_configured_production` / `assert_runtime_identity` |
| System ID pin | PASS (kód + unit) | `assert_production_identity` / `assert_runtime_identity` |
| scope | PASS (nezměněno oproti 0.5.8) | existující scope služby |
| production write matrix explicitní | PASS | `docs/PRODUCTION_WRITE_READINESS_0.5.8.md` |
| unsafe writes fail-closed | PASS | gates + deposit>0 / category_change |
| standalone PySide6 EXE | PASS | `JidelnaLocalLite.exe --version` → `0.6.0` |
| installer vytvořen | FAIL / BLOCKED | `ISCC` missing |
| clean first run | BLOCKED | vyžaduje installer/instalaci do Program Files |
| upgrade/restart smoke | BLOCKED | bez installeru |
| PDF/reader/core smoke | PARTIAL | reportlab v `_internal`; GUI PDF/reader smoke neběžel end-to-end |
| secrets scan | PASS (manual) | žádné PFX/PEM/hesla v packaging vstupech |
| SHA256 | PASS | `SHA256SUMS.txt` |
| signing VALID nebo UNSIGNED labelled | PASS (UNSIGNED labelled) | `BUILD_INFO.json` |

## EXE smoke (OVĚŘENO)

```text
dist/release/0.6.0/JidelnaLocalLite/JidelnaLocalLite.exe --version → 0.6.0 (exit 0)
dist/.../JidelnaLocalLite.exe --help → argparse help (exit 0)
```

## Local Defender

```text
MpCmdRun -Scan -ScanType 3 -File ...\JidelnaLocalLite.exe → no threats
```

## Installer

```text
ISCC.exe: not found on build machine
JidelnaLocalLite-0.6.0-Setup.exe: not built
```

## Signing

```text
signtool.exe: not found / JLL_SIGN_CERT unset
status: UNSIGNED candidate only
```

## Residual risk (must remain visible)

JLL nemůže zabránit neparticipujícímu externímu writeru, který si před JLL lockem načetl stale měsíční obraz, aby jej po JLL COMMITu zapsal. JLL používá stale-input prevention, krátkou lock/re-read transakci, post-commit/settle verification a safe refresh místo automatického boje o poslední zápis.

## Jediný další lidský krok k signed installer candidate

1. Nainstalovat Inno Setup 6 (`ISCC.exe`).
2. Poskytnout Authenticode certifikát dostupný přes Windows certificate store / `signtool` (thumbprint do `JLL_SIGN_CERT`) — **neposílat private key do chatu/repa**.
3. Spustit `./tools/build_windows_release.sh` a ověřit `signtool verify /pa /all /v`.

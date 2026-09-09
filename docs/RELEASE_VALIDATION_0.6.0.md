# RELEASE_VALIDATION — JidelnaLocalLite 0.6.0 (Flet target)

**signature_status:** UNSIGNED
**UI target:** Flet (`python -m jll` → `jll.flet_ui`)
**PySide6:** reference/legacy only

## Gates

| Gate | Výsledek |
| --- | --- |
| Intent safety (ADD↛DELETE) | PASS |
| Atomic DinerDay+version snapshot | PASS (code + integration test) |
| Flet marker poll + settle | PASS (implemented) |
| MW-05/06/07 dedicated | PASS (oracles added) |
| Production first-run wizard | PASS (LAB\|PRODUCTION mode) |
| Production write policy backend | PASS |
| Production write policy Flet GUI | PASS |
| Production identity VED/SUP | PARTIAL (VED+SUP first-run OK; create-user blocked) |
| Packaged Flet EXE | follow-up build |
| Installer / Authenticode | BLOCKED (ISCC/cert) |

## Residual risk

JLL nemůže zabránit neparticipujícímu externímu writeru, který si před JLL
lockem načetl stale měsíční obraz, aby jej po JLL COMMITu zapsal. JLL proto
používá intent preservation, stale-state prevention, lock/re-read,
post-commit/settle detection a safe refresh bez retry war.

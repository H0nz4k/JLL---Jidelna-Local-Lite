# RELEASE_VALIDATION — JLL 0.6.0 (Flet target)

**product_name:** JLL  
**product_version:** 0.6.0  
**file_version:** 0.6.0.0  
**company_name:** Altisima  
**signature_status:** UNSIGNED  
**signature_policy:** UNSIGNED_BY_DESIGN  
**authenticode_required:** false  
**UI target:** Flet (`python -m jll` → `jll.flet_ui`)  
**PySide6:** reference/legacy only

## Gates

| Gate | Výsledek |
| --- | --- |
| Intent safety (ADD↛DELETE) | PASS |
| Atomic DinerDay+version snapshot | PASS |
| Flet marker poll + settle | PASS |
| MW-05/06/07 dedicated | PASS |
| Production first-run wizard | PASS |
| Production write policy backend | PASS |
| Production write policy Flet GUI | PASS |
| Windows VersionInfo (EXE) | REQUIRED |
| Windows VersionInfo (Setup) | REQUIRED |
| Authenticode | NOT REQUIRED |
| Packaged Flet EXE | follow release build |
| Installer | UNSIGNED BY DESIGN |

## Signing policy

Authenticode není požadavek pro JLL 0.6.0. Absence digitálního podpisu
není release blocker. Release musí zůstat transparentně označený jako
`UNSIGNED` / `UNSIGNED_BY_DESIGN`. Self-signed certifikát se nepřidává.

## Residual risk

JLL nemůže zabránit neparticipujícímu externímu writeru, který si před JLL
lockem načetl stale měsíční obraz, aby jej po JLL COMMITu zapsal. JLL proto
používá intent preservation, stale-state prevention, lock/re-read,
post-commit/settle detection a safe refresh bez retry war.

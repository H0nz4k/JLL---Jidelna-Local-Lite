# JLL chip write contract 0.3.0

## Stavový stroj (PROVEN z Pomoc.pas / Data.pas)

| Kód | Význam |
| --- | --- |
| `P` | Přidělen (`CipPridelen`) |
| `V` | Volný (`CipVolny`) |
| `B` | Blokovaný (`CipBlokovan`) |
| `Z` | Ztracený (`CipZtracen`) |

## Detail čipu (read)

- Permission: `chips.view` pouze  
- **Není** vázán na `CHIP_WRITE_GATES["assign"]`  
- Zobrazí aktuální `cipy` + scoped `histcipu` (pokud dostupná)

## Write matice

| Operace | Before | After | Evidence / poznámka |
| --- | --- | --- | --- |
| assign | PARTIAL | **PROVEN** | `NajdiCip(P)` + hist + `stravnik.cip`; finance `VyberzaCip` jen při INI `CenaZaPrvniCip≠0` → mimo 0.3.0 |
| return | BLOCKED | **BLOCKED** | DB `NajdiCip(V)` doložen, ale legacy volá `VratzaCip` (platba) → 0.4.0 |
| block | BLOCKED | **PROVEN** | BitBtn13 / `NajdiCip(B)`: `P→B` + hist, owner zůstává |
| lost | BLOCKED | **PROVEN** | BitBtn14: `→Z` + hist + clear `stravnik.cip` |
| unblock | BLOCKED | **PROVEN** | `NajdiCip(B)` když už `B` → `P` + hist |
| transfer | BLOCKED | **BLOCKED** | žádná samostatná legacy akce; tichý transfer zakázán |

## Architektura

```text
Chip read/detail/history → Permission.CHIPS_VIEW
ChipCommandService       → permission + CHIP_WRITE_GATES + LAB/scope/audit
```

## Tests

Real DB: assign / duplicate / block / unblock / lost + history permission
v `tests/integration/test_diner_chip_0_3_0_postgres.py`.

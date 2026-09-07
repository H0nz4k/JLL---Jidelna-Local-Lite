# JLL chip write contract 0.3.0 (+ 0.3.1 deposit safety)

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

| Operace | Gate | Runtime | Evidence |
| --- | --- | --- | --- |
| assign | **PROVEN** | `CenaZaPrvniCip=0` OK; `>0` fail-closed před write | `NajdiCip(P)` + hist + `stravnik.cip` |
| return | **PROVEN** | jen `deposit=0`; `>0` fail-closed | `NajdiCip(V)` nefinanční větev |
| block | **PROVEN** | — | BitBtn13 / `NajdiCip(B)` |
| lost | **PROVEN** | — | BitBtn14 |
| unblock | **PROVEN** | — | `B→P` + hist |
| transfer | **BLOCKED** | — | žádná samostatná legacy akce |

Autoritativní záloha: `public.parametry` sekce `BACKUP` / `CenaZaPrvniCip`
(viz `docs/JLL_CHIP_FINANCIAL_CONFIG_0.3.1.md`). **Ne INI.**

## Architektura

```text
Chip read/detail/history → Permission.CHIPS_VIEW
ChipCommandService       → permission + CHIP_WRITE_GATES + deposit gate + LAB/scope/audit
```

## Tests

- `tests/integration/test_diner_chip_0_3_0_postgres.py`
- `tests/integration/test_chip_deposit_0_3_1_postgres.py`

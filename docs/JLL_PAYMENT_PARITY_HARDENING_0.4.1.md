# JLL payment parity hardening 0.4.1

## Co bylo v 0.4.0 neparitní

1. **Chip deposit/refund > 0** používal nehotovostní `typplatby` (ImplicitTypPlatby
   nebo banku `4`), zatímco legacy `VyberzaCip` / `VratzaCip` nastavuje
   `Edit1.Text := '1'` (hotově).
2. **Banka není náhrada hotovosti** — mění účetní a pokladní význam operace.
3. Python **`float(Decimal)`** před `zapisplatbu` zbytečně ztrácel přesnost
   (DB parametr je `double precision`, ale JLL nesmí castovat dřív).

## Co 0.4.1 opravila

| Oprava | Stav |
| --- | --- |
| Decimal bez `float()` | PROVEN |
| deposit>0 fail-closed (cash contract nekompletní) | PROVEN fail-closed |
| Dokumentace cash chip contract | PROVEN characterization |
| Manual non-cash payment | beze změny scope, + Decimal tests |

## Rozhodnutí deposit > 0

**VARIANTA B** — cash chip workflow zůstává **BLOCKED**.

Důvod: po `ZapisPlatbu` legacy zapisuje `uctenky_kasy`, inkrementuje
`CisloPrijmovehoDokladu` a volitelně tiskne doklad. Bez tohoto DB stavu
nelze tvrdit paritu s hotovostní zálohou.

Viz `docs/JLL_CASH_CHIP_CONTRACT_0.4.1.md`.

## Gates (0.4.1)

```text
manual_payment          PROVEN
cash_payment            BLOCKED
chip_deposit            BLOCKED
chip_deposit_refund     BLOCKED
refund                  BLOCKED
homebanking_link        BLOCKED
```

Chip assign/return při `CenaZaPrvniCip=0` zůstává PROVEN (nefinanční path).

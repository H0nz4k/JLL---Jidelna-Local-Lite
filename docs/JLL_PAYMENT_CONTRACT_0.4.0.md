# JLL payment contract 0.4.0

## Autorita

1. LAB DB funkce `public.zapisplatbu` → `insert_penden` (+ podmíněný `platbatm`/`platbabm`)
2. Legacy `DataModule1.ZapisPlatbu` / `Platba.pas`
3. JLL `PaymentService` (žádný přímý `INSERT INTO penden` z UI)

## Typy `penden.typ` (LAB)

| Typ | Význam |
| --- | --- |
| `R` | rozpis |
| `P` | platba |
| `C` | záloha / vratka za čip |
| `O` | poplatek (v LAB nevyužito) |

## Sign convention

Delphi `ZapisPlatbu(cena)` ukládá do DB `pcastka := -cena`.

JLL volá DB funkci přímo s **finální** částkou do `penden.castka`:

- ruční platba: `+amount`
- záloha čipu: `+CenaZaPrvniCip`
- vratka čipu: `-CenaZaPrvniCip`

## Write gates

| Gate | Status |
| --- | --- |
| `manual_payment` | PROVEN (jedna služba, nehotovost; Decimal bez Python float) |
| `cash_payment` | BLOCKED (`uctenky_kasy` / doklad) |
| `refund` | BLOCKED |
| `chip_deposit` | BLOCKED (legacy hotovost; viz 0.4.1) |
| `chip_deposit_refund` | BLOCKED |
| `homebanking_link` | BLOCKED |

Aktualizace parity: `docs/JLL_PAYMENT_PARITY_HARDENING_0.4.1.md`,
`docs/JLL_CASH_CHIP_CONTRACT_0.4.1.md`.

## Ruční platba

- oprávnění `payments.post`
- `typplatby ≠ 1`
- explicitní jedna `typstravy` (bez `NastavPriority` split)
- měsíc ∈ {TentoMesic, TentoMesic+1}
- datum = DB `CURRENT_DATE`
- audit `insert_udalost` typ `B` (jako `GenerujUdalost_Penden`)

## Čip

Viz `docs/JLL_CHIP_PAYMENT_ATOMICITY_0.4.0.md` a aktualizaci
`docs/JLL_CASH_CHIP_CONTRACT_0.4.1.md` (deposit>0 = BLOCKED do cash PROVEN).

# Multi-writer coexistence (JLL 0.5.8)

## Residual risk (neskrývat)

JLL **nemůže zabránit** neparticipujícímu externímu writeru (JidelnaSQL /
e‑jídelníček), který si před JLL lockem načetl stale měsíční obraz, aby jej
po JLL COMMITu zapsal. Proto JLL používá:

| Vrstva | Garantuje |
| --- | --- |
| **PREVENTION** | odmítnutí zápisu ze zastaralého UI snapshotu |
| **DETECTION** | post-commit + settle rozpoznání cizího přepsání |
| **SAFE RECOVERY** | refresh autoritativního DB stavu, **žádný retry war** |

```text
PREVENTION GUARANTEE  ≠  „cizí writer nikdy nezapíše stale měsíc“
DETECTION + SAFE RECOVERY  =  dosažitelná bezpečnost bez úpravy JidelnaSQL/efood
```

## Forenzní důkazy (ověřeno / REFERENCE)

- Efood sync watermark `updated_dt` / `seq` na `public.prihlas` — change
  tracking, ne CAS token (efood `jobExportPrihlas*`, provozní BEFORE trigger
  nastavuje `updated_dt` + `seq`).
- Efood / `uloz_prihlasku_s_dotaci` může držet **celý měsíční** `data_ordered`.
- Legacy `objednavka_plus/minus` skládá měsíční stav před UPDATE.
- Globální `vyloucenos` A→BCD ≠ nutnost řádku D (parity fix 0.5.4, nesmí
  regresovat).

## Write-surface audit (0.5.8)

| Surface | Lock / expected | Multi-writer readiness |
| --- | --- | --- |
| **orders.change** | month advisory + `prihlas FOR UPDATE` + nový `OrderVersionToken` | **PARTIAL→detection PROVEN**; prevention cizího stale month **nemožná** bez změny writeru |
| diner create/edit | advisory / `stravnik FOR UPDATE` + `expected_updated_dt` | PARTIAL (LAB PROVEN gates ≠ multi-writer prod) |
| chips | `stravnik`/`cipy FOR UPDATE` | PARTIAL |
| payments.manual | `stravnik FOR UPDATE` + `zapisplatbu` | PARTIAL |
| serving.record_pickup | bez mutual exclusion | PARTIAL / risk |
| admin identity/config | JSON / `uzivatel` | mimo DB order coexistence |

## Model

```text
OrderSnapshot / OrderVersionToken  = UI + (seq?, updated_dt?, material fingerprint)
→ pre-lock fail-fast + under-lock re-read
→ legacy-compatible write (objednavka_*)
→ PostCommitProbe + settle (~400 ms, QTimer)
→ live marker poll (~2000 ms) jen pro otevřeného strávníka/měsíc
```

Implementace: `src/jll/orders/concurrency.py`, `OrderService`,
`OrderApplicationService`, PySide6 `MainWindow` poll/settle.

Error kódy: `ORDER_STALE_STATE`, `ORDER_EXTERNAL_CHANGE` (nezneužívat
`ORDER_ROW_MISSING`).

## Mixed-writer XFAIL (zachovány)

Tři strict XFAIL v `tests/integration/test_orders_postgres.py` zůstávají:
dokazují **nemožnost PREVENTION** vůči legacy writeru. Nové PASS oracles
(MW-01+) dokazují DETECTION + SAFE RECOVERY.

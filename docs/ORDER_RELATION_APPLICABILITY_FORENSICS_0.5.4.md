# Order relation applicability – forensics 0.5.4

> Prompt file targeted `0.5.3`, but canonical app version `0.5.3` was already
> released for diner/HOME UX polish (`ac22cc7`). This fix ships as **0.5.4**.

## Legacy evidence

| Claim | Status | Evidence |
| --- | --- | --- |
| `typstrav.vyloucenos/spolecnes` are global relation strings | **PROVEN** | `zdroje/typstrav.csv`; LAB `typstrav` A→BCD, B→ACD, C→ABD, D→ABC |
| Monthly `prihlas` rows are created from usual diner meal types (`stravobv`), not from every global relation code | **PROVEN** | JidelnaSQL `prihlas.pas` `DoplnRozpis`: iterates `TStravObv` and calls `nastavprihlasdleobvykle` only for those `typstravy` |
| Stored proc `aplikujspolusvyloucenos` applies relations on existing monthly rows | **PROVEN** | JidelnaSQL `Data.pas` (`StoredProcspolusvyloucenos`) |
| Exact Delphi predicate “skip relation code when category has no sazba” | **NOT PROVEN** in Pascal text search; inferred from data+UI parity |

## DB / JLL applicability source

**Authoritative write/read contract for “is meal type usable for period category on date”:**

```sql
SELECT typstravy
FROM public.sazby
WHERE kategorie = :period_category
  AND typstravy = ANY(:candidates)
  AND platnostod <= :target
  AND COALESCE(platnostdo, :target) >= :target
```

| Claim | Status | Evidence |
| --- | --- | --- |
| JLL diner UI already filters meal types by `sazby` for period category | **PROVEN** | `OrderReadService._load_meals` → `_load_menu_capabilities`; comment: “Jen typy stravy, pro které má kategorie platnou sazbu” |
| Period category prefers unique `prihlas.kategorie`, else `stravnik.kategorie` | **PROVEN** | same `_load_meals` block |
| Scope privacy remains `stravnik.kategorie` | **PROVEN** | existing order/read scope docs + `lock_diner` |

`stravobv` is **per diner** (`kodstravnika`), not per category — useful for month generation, **not** the JLL UI applicability filter.

## Balcar 3638 evidence (LAB `jll_scio_lab`, 2026-09-09)

| Fact | Status |
| --- | --- |
| `stravnik`: evidcislo 3638, kategorie `3JARO` | **PROVEN** |
| `prihlas` 09/2026: `Svačina`, `Oběd-A`, `Oběd-B`, `Oběd-C` only | **PROVEN** |
| `sazby` for `3JARO` on 2026-09-09: A/B/C + Svačina; **no Oběd-D** | **PROVEN** |
| Global A.`vyloucenos` = `BCD` | **PROVEN** |

Corrected effective exclusive group for ordering A:

```text
global: A,B,C,D
applicable via sazby(3JARO): A,B,C
effective: A,B,C
```

## Current JLL failure

`OrderService._load_relations` loads **all** global related `typstrav` codes, then
`lock_order_rows` requires a monthly row for each. Missing `Oběd-D` →
`ORDER_ROW_MISSING` even though D is non-applicable for the period category.

## Why skipping non-applicable D is safe

- UI never offers D for Balcar (read path uses `sazby`).
- No monthly D row is expected when category has no D sazba.
- Fail-closed remains for **applicable** related types with missing `prihlas`.
- No auto-insert of `prihlas`; `typstrav` relation strings unchanged.

## When `ORDER_ROW_MISSING` remains

1. Target meal type monthly row missing.
2. Related meal type **has** active `sazby` for period category/date, but monthly row missing.

## Period-category semantics

Applicability uses **order-period category** (`prihlas.kategorie` when unique for
the month; otherwise current `stravnik.kategorie`), not a blind always-current
scope category. Scope enforcement for privacy stays on `stravnik.kategorie`.

## Concurrency impact

Still locks: advisory month lock, optional strict config lock, diner row, then
**target + effective applicable related** monthly rows only.

## SQL roundtrip impact

+1 set-based query: distinct period categories for the month (cheap), and
+1 set-based `sazby` filter for candidate related typstravy (same shape as read
`_load_menu_capabilities`). No per-code N+1.

## Labels summary

- **PROVEN**: global relations; Balcar missing D; sazby filter in read path; LAB sazby/prihlas evidence.
- **INFERENCE**: Delphi internally skips the same way (data/UI parity); exact Pascal predicate not quoted.
- **NOT PROVEN**: alternative applicability tables beyond `sazby` for this LAB.

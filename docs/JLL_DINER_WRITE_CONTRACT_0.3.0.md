# JLL diner write contract 0.3.0

DINER CREATE: **PROVEN** (JLL-only LAB)  
DINER EDIT PERSONAL: **PROVEN**  
DINER CATEGORY CHANGE: **PARTIAL** (fail-closed)

## Create

### Before

`DINER_WRITE_GATES["create"] = PARTIAL` — žádný write service.

### Legacy evidence

- Allocator: `public.pridel_cislo_stravnika(1)` (`Data.pas` / DDL).
- Insert defaults: `TStravnikAfterInsert` → finance 0, `stav='A'`.
- Required: `evidcislo`, `jmeno`, `kategorie`, `zpusobplatby`.
- Po uložení: `doplnobvyklestravnikakategor` AM+BM, podmíněně
  `nastavprihlasdleobvykle` (`DoplnRozpis`).
- PIN: `GetPIN` (`Pomoc.pas`).

### JLL path

`DinerService.create` v jedné transakci:

1. LAB guard + `diners.create` + scope kategorie  
2. `pg_advisory_xact_lock` + `pridel_cislo_stravnika`  
3. INSERT `stravnik` + legacy PIN  
4. `doplnobvyklestravnikakategor` pro AM a BM  
5. podmíněný `nastavprihlasdleobvykle`  
6. `insert_udalost` (`Nový strávník`) — rollback při fail  

Retry při `UniqueViolation` (allocator race).

### Mixed writer

Advisory lock je **jen JLL**. Legacy souběžný create může stále kolidovat
na PK; dokumentováno, gate platí pro JLL-only LAB režim.

### After

`create = PROVEN`

### Tests

`tests/integration/test_diner_chip_0_3_0_postgres.py` — happy path, scope,
permission, LAB guard, concurrency, audit-fail rollback.

## Edit personal

### Before

`edit_personal = BLOCKED`

### Whitelist

`jmeno`, `trida`, `ulice`, `psc`, `mesto`, `poznamka`, `poznamkaam`,
`poznamkabm`, `email`, `vzkaz`, `stredisko`, `datumnarozeni`

### Forbidden

`evidcislo`, `kategorie`, finance, `cip`, `pin`, `stav`, `deleted`,
`zpusobplatby`, bankovní údaje…

### Concurrency

`SELECT … FOR UPDATE` + `expected_updated_dt` vs `stravnik.updated_dt`.

### After

`edit_personal = PROVEN`

## Category change

Legacy `DBEdit3Exit` + AM/BM dialogy + `doplnobvyklestravnikakategor`
návratové kódy nejsou kompletně portované.

**Gate: PARTIAL** — neblokuje personal edit.

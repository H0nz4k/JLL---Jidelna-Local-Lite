# JLL chip payment atomicity 0.4.0

## Invariant

```text
čip + finanční záloha/vratka = jedna DB transakce
```

Pořadí v JLL:

1. LAB guard + lock strávníka
2. `load_chip_financial_config` (`CenaZaPrvniCip`)
3. pokud deposit > 0: `payments.post` + `zapisplatbu` typ `C`, `mesic=0`
4. chip assign/return (cipy / histcipu / stravnik.cip)
5. chip audit `insert_udalost`
6. COMMIT

Finance fail → žádný chip write. Chip fail po finance → rollback včetně `penden`.

## Konfigurace

```text
public.parametry BACKUP.CenaZaPrvniCip
```

`deposit=0` → čistě nefinanční path (0.3.1).

## Způsob platby pro čip

Legacy UI defaultuje hotovost (`Edit1=1`) včetně dokladu/EET.

JLL **nepoužívá hotovost**:

1. `ImplicitTypPlatby` z BACKUP, pokud ≠ `1`
2. jinak banka `4`

`cash_payment` zůstává BLOCKED.

## Poznámky

- `TextZalohazaCip` / `TextVracenozaCip` z BACKUP
- účet default `STRAV`
- typ služby = defaultní strava (`Oběd` nebo první `typsluzby=strava`)
- `GenerujUdalost_Penden` legacy jen pro typ `P`; u `C` stačí chip audit

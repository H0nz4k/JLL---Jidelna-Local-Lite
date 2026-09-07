# JLL chip payment atomicity 0.4.0

> **0.4.1 update:** deposit/refund > 0 je opět **FAIL-CLOSED**.
> 0.4.0 nehotovostní „atomická“ cesta nebyla legacy-paritní (hotovost +
> `uctenky_kasy`). Viz `docs/JLL_CASH_CHIP_CONTRACT_0.4.1.md`.

## Invariant (cíl po cash PROVEN)

```text
čip + hotovostní záloha/vratka + pokladní doklad = jedna DB transakce
```

## Runtime 0.4.1

| Záloha | Chování |
| --- | --- |
| `0` | nefinanční assign/return PROVEN |
| `>0` | fail-closed před finance i chip write |

## Proč ne banka

Legacy `VyberzaCip` / `VratzaCip` nastavuje `typplatby=1` (hotově).
JLL nesmí přemapovat hotovost na banku jen proto, že cash contract chybí.

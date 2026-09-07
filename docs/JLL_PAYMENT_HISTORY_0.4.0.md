# JLL payment history 0.4.0

## Filtr karty strávníka „Platby“

```sql
typ IN ('P', 'C')
ORDER BY datum DESC, cas DESC NULLS LAST, id DESC
LIMIT / OFFSET
```

Rozpisy (`R`) se v historii plateb nezobrazují. LAB nemá typ `Z`.

## Oprávnění

- `payments.view` — načtení historie / detailu
- bez oprávnění se historie ve Flet UI vůbec nenačítá

## Detail

Snapshot z `penden` (kategorie/třída v době zápisu), ne aktuální `stravnik`.

Homebanking vazba se nezobrazuje (`PAYMENT_WRITE_GATES["homebanking_link"] = BLOCKED`).

## Výkon

Filter/order/limit na serveru; stránkování default 20 / max 100.
Produktový index na `penden(evidcislo, typ, …)` se v 0.4.0 nevytváří.

# JLL chip financial config 0.3.1

## Autoritativní zdroj

```text
public.parametry
sekce    = BACKUP
parametr = CenaZaPrvniCip
hodnota  = text (Decimal, např. "0" / "100")
```

`Backup.CenaZaPrvniCip` v legacy INI je runtime cache načtená z parametrů;
**JLL source of truth je výhradně `public.parametry`.**

Související parametr (charakterizován, nepoužit v business 0.3.1):

```text
CenaZaDalsiCip  (BACKUP) — evidence PARTIAL, žádný aktivní assign/return kontrakt
```

## Runtime chování

| Záloha | assign | return |
| --- | --- | --- |
| `0` | PROVEN DB path, bez finance | PROVEN nefinanční NajdiCip(V) |
| `>0` | FAIL-CLOSED před chip write | FAIL-CLOSED před chip write |
| missing / invalid / negative | FAIL-CLOSED | FAIL-CLOSED |

Contract status `CHIP_WRITE_GATES["assign"|"return"] = PROVEN` popisuje
nefinanční DB kontrakt. Runtime dostupnost závisí na záloze.

## 0.4.0

PaymentService musí atomicky spojit čip + `VyberzaCip` / `VratzaCip`
(záloha / vratka) do jedné business operace.

# IKonverze čipů a přidání `00` na konec

Tento dokument popisuje, jak funguje převod čipu pomocí funkce **IKonverze**,
co znamená volba **Pridat00** a proč se výsledná hodnota následně doplňuje
zleva na **16 znaků**.

Implementace v JLL: `jll.chip_code_transform` + přepínače v
Administrace → Čtečka (`reader_ikonverze`, `reader_pridat00` v `lab.json`).

---

## 1. IKonverze

Podle logiky používané v **JídelnaSQL / `Prilozcip.pas`** probíhá IKonverze takto:

1. vezme se relevantní 10znaková HEX část čipu,
2. zahodí se první byte,
3. v každém HEX znaku se obrátí pořadí jeho 4 bitů,
4. výsledná HEX hodnota se převede na DEC.

### Příklad

Původní hodnota čipu:

```text
0000004900327C3D
```

Relevantní část:

```text
49 00 32 7C 3D
```

### Krok A – odstranění prvního bytu

První byte `49` se zahodí → zůstane `00327C3D`.

### Krok B – obrácení bitů v každém HEX znaku

| Původní HEX | Bity | Obrácené bity | Výsledný HEX |
|---|---|---|---|
| 0 | 0000 | 0000 | 0 |
| 1 | 0001 | 1000 | 8 |
| 2 | 0010 | 0100 | 4 |
| 3 | 0011 | 1100 | C |
| 4 | 0100 | 0010 | 2 |
| 5 | 0101 | 1010 | A |
| 6 | 0110 | 0110 | 6 |
| 7 | 0111 | 1110 | E |
| 8 | 1000 | 0001 | 1 |
| 9 | 1001 | 1001 | 9 |
| A | 1010 | 0101 | 5 |
| B | 1011 | 1101 | D |
| C | 1100 | 0011 | 3 |
| D | 1101 | 1011 | B |
| E | 1110 | 0111 | 7 |
| F | 1111 | 1111 | F |

`00327C3D` → `00C4E3CB` → DEC **`12903371`**.

---

## 2. Pridat00

Vezme hotový výsledek IKonverze a připojí literál `00`:

```text
12903371 → 1290337100
```

---

## 3. Doplnění na 16 znaků

DB `public.cipy.cislo` je `varchar(16)` — doplnění zleva nulami:

```text
1290337100 → 0000001290337100
```

Kompletní řetězec:

```text
0000004900327C3D
  → IKonverze → 12903371
  → Pridat00  → 1290337100
  → pad 16    → 0000001290337100
```

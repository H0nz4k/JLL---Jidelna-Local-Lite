# JLL – povolená čísla menu (`public.sazby`)

## 1. Účel

Objednávka v JLL není „jedna strava = jedno menu“. Objednávka je vždy
kombinace:

```text
typ stravy (typstravy)
+
číslo menu (1..N)
```

Tento dokument fixuje, odkud se `N` bere. Počet menu není a nesmí být
hard-coded v PySide6 GUI.

## 2. Zdroj pravdy

```text
public.sazby.pocetmenu
```

Sloupec je `smallint` a určuje, kolik čísel menu je povoleno.

Primární klíč tabulky je:

```text
PRIMARY KEY (kategorie, typstravy, platnostod)
```

Z toho vyplývá, že capability je závislá současně na:

- kategorii strávníka (`sazby.kategorie` ↔ `stravnik.kategorie`),
- typu stravy (`sazby.typstravy` ↔ `typstrav.typstravy`),
- dni (`platnostod` ≤ den ≤ `platnostdo`).

Ověřeno v LAB (`jll_demo_lab`) k 2026-09-03:

```text
sazby řádků celkem:                 793
pocetmenu rozsah:                   1..2
pocetmenu NULL:                     0
platnostdo NULL:                    0
překrývající se platnosti:          0
```

## 3. Souvislost čísel 1..N

Čísla menu jsou souvislý rozsah `1..pocetmenu`, ne libovolná množina.

Důkazy:

1. `public.getceniknamesic(rok, mesic)` generuje ceník cyklem
   `FOR j IN 1..mpocetmenu`, tedy vytváří právě `1..pocetmenu`.
2. Kontrola dat v `public.cenik` (`slozka=0`) nenašla žádnou kombinaci
   `rok, mesic, den, kod_stravy, kategorie`, kde by `count(DISTINCT menu)`
   nebyl rovný `max(menu)`; tedy žádné mezery.
3. `public.typstrj.oznaceni` obsahuje pouze označení `1`..`9`.

Horní hranice je 9, protože `public.prihlas` ukládá stav dne do jednoho
znaku (`d01`..`d31`). Vyšší `pocetmenu` proto JLL odmítne jako neplatnou
konfiguraci, nikoli jako částečně použitelný stav.

## 4. Kontraktní status

```text
zdroj počtu menu (sazby.pocetmenu):        PROVEN
vazba na typstravy:                        PROVEN
závislost na kategorii a dni:              PROVEN
souvislost 1..N:                           PROVEN
horní hranice 9 (prihlas jeden znak):      PROVEN
chování při překryvu platností:            fail-closed (nedoložené jako povolené)
```

Jde o read kontrakt. Tato fáze neotevírá žádný chip ani diner write gate
z FÁZE 3A.

## 5. API

Business SQL nepatří do GUI. Capability model poskytuje read vrstva:

```python
OrderReadService.get_allowed_menu_numbers(category, target)
    -> tuple[MenuCapability, ...]

MenuCapability(meal_type: str, allowed_menus: tuple[int, ...])
```

Interně používá `OrderReadService._load_menu_capabilities`, který provede
jeden dávkový dotaz pro všechny zobrazené typy stravy (žádné N+1).

Karta strávníka dostává stejný model uvnitř `MealDay`:

```python
MealDay.allowed_menus: tuple[int, ...]
MealDay.allowed_menu_count: int   # derived
```

Volání `get_allowed_menu_numbers` vyžaduje `diners.view` + `orders.view` a
kategorie musí být v `allowed_categories`; jinak vrací
`OUT_OF_SCOPE_OR_INACTIVE`.

## 6. Vztah povoleného menu, jídelníčku a ceny

Tři různé věci:

1. **Povolené číslo menu** – `public.sazby.pocetmenu`. Autoritativní pro to,
   co lze vůbec objednat.
2. **Text jídla** – `public.jidelnicek` + `menustravy` + `typstrj`.
   Nezveřejněný jídelníček povolené číslo menu neskrývá; řádek se zobrazí
   jako „Jídelníček není zveřejněn“.
3. **Cena** – `public.getcenamenuden(...)`. Kandidát bez platné ceny
   (`ok = false`) se nenabídne vůbec.

Pořadí je tedy: sazby určí kandidáty, cena je potvrdí, jídelníček je jen
popíše.

## 7. Fail-closed pravidla

- Dvě platné sazby pro stejnou kombinaci `kategorie + typstravy + den`
  → `RELATION_CONFIG_INVALID`.
- `pocetmenu` mimo `0..9` → `RELATION_CONFIG_INVALID`.
- `pocetmenu` `NULL` nebo `0` → žádné povolené menu, ne implicitní `1`.
- Chybějící řádek v `sazby` → žádné povolené menu.
- Záporná cena → `PRICE_INVALID`.

## 8. exkluzivní A–D vs. číslo menu

`Oběd-A`, `Oběd-B`, `Oběd-C`, `Oběd-D` jsou samostatné `typstravy`, ne
čísla menu. Jejich vzájemné vyloučení řeší backend kontrakt
(`typstrav.vyloucenos`) a `OrderService`. Číslo menu je nezávislá souřadnice
uvnitř konkrétního typu stravy.

UI proto vždy zobrazuje typ stravy a číslo menu odděleně.

## 9. Ověření

```text
tests/unit/test_menu_capabilities.py
  - souvislý rozsah z pocetmenu
  - chybějící řádek = žádné menu
  - NULL/0 není implicitní 1
  - dotaz je scoped na kategorii, typy stravy a den
  - prázdný seznam typů se vůbec neptá DB
  - překryv sazeb fail-closed
  - pocetmenu > 9 fail-closed

tests/integration/test_read_service_postgres.py
  - povolená menu se rovnají public.sazby pro reálnou kategorii a den
  - kategorie s pocetmenu = 2 vrací (1, 2)
  - žádná nabídnutá volba nepřekročí pocetmenu
  - kategorie mimo scope končí OUT_OF_SCOPE_OR_INACTIVE
```

V LAB datech má více než jedno menu kategorie `ZAM` a `ZAP`
(`Oběd-A..Oběd-D`, platnost 2023-11-01..2023-12-31). Kategorie `SZU` má
`pocetmenu = 2`, ale její typy stravy mají `pouzivatpcbox = false`, takže je
JLL vůbec nezobrazuje.

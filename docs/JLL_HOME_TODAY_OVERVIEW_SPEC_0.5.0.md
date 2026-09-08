# JLL 0.5.0 – HOME / Dnešní objednávky

Stav: **SPEC pro implementaci**  
Verze: `0.5.0`  
Base: `ui/0.4.4-typography-system`

## Purpose

HOME je výchozí stav obrazovky **Strávníci**, když není otevřen žádný
strávník. Odpovídá jen na:

> Dnes se vaří toto a objednáno je toho tolik.

Není to nová top-level záložka. Po otevření strávníka HOME nahradí karta.

## Obsah

- lidský název **pracoviště** (stanice),
- **serverové** dnešní datum + kontext „dnes se vaří“ / „dnes se nevaří“,
- seznam dnešních **objednaných porcí** podle `typstravy` × `menu`,
- název jídla z jídelníčku (pokud je),
- jeden KPI: **Celkem N porcí**.

## Explicitně zakázaný obsah

- DB / System ID / COM / ELATEC detail,
- diagnostika,
- stav výdeje, vydáno, zbývá,
- grafy, dlaždice, technická KPI,
- akční tlačítka (objednat / vydat / platba / edit).

## Data contract

Autorita porcí = stejná definice jako sestavy:

- `public.prihlas.dNN ∈ {'1'..'9'}` = objednané menu,
- JOIN `stravnik` s `s.kategorie = ANY(allowed_categories)`,
- `COALESCE(s.deleted,false)=false`,
- den = PostgreSQL `clock_timestamp()` v business TZ (**ne** `date.today()`),
- název jídla = LEFT JOIN jídelníček (česky, `cislojidelnicku=1`); chybějící
  název **nezahazuje** řádek (`menu_published=False`).

Permission: `DINERS_VIEW` (HOME je součást Strávníků). Scope = `SessionPolicy.scope()`.

SQL roundtrips pro `load_home_today_overview()`: **1 transakce / 2 statements**
(orders+meals summary; varnedny flag + optional next cooking day).

## Scope

Server-side only přes `allowed_categories`. Žádný klientský filtr kategorií.

## Workplace source

| Pojem | Zdroj |
|---|---|
| Organizace / provozovna | `LabConfig.site_name` (seed z `NameSubject`) |
| Pracoviště / stanice | `LabConfig.instance_id` (= `public.stanice.nazev`) |
| HOME title | humanizované `instance_id` (např. `JAROV` → `Jarov`) |
| Shell subtitle | `site_name · instance_id` bez data |

Datum zůstává na HOME (ne v shell subtitle), aby se neduplikovalo.
Účetní období `AM …` zůstává dostupné v diagnostice / business calendar,
na HOME se nepromítá.

## Varný den

Autoritativní `public.varnedny` (`dNN='A'`). Víkend sám o sobě neznamená
nevaření. Bonus: `next_cooking_day` přes existující read path.

## Multi-menu

`typstravy != menu`. Více menu u jednoho typu = samostatné řádky, menu
numericky 1,2,3. Typy řazeny podle `typstrav.poradi` (fallback název).

## Unpublished menu

Porce se zobrazí; podtitulek „Jídelníček není zveřejněn“ / chybějící název.

## Refresh

- vstup na HOME / návrat z karty / relevantní order change,
- periodicky ~60 s **jen když je HOME viditelná**,
- chyba → text + „Zkusit znovu“.

## ESC

1. dialog → zavři dialog  
2. diner detail → HOME (+ privacy reset)  
3. search/highlight → clear → HOME  
4. už HOME → no-op  

## Idle privacy

`DINER_IDLE_HOME_SECONDS = 60` na read-only diner detail → HOME.

Suppressed při: modal, create/edit, payment, chip dialog, write in flight,
jiná top-level route.

## Dirty / modal suppression

Idle nikdy nezahazuje rozpracovanou práci. Activity resetuje timer
(keyboard, click, search, RFID, dialog, dokončená akce).

## Header decision

```text
JidelnaLocalLite v0.5.0
Scio Kuchyně · Jarov
```

Datum a varný kontext patří HOME.

# JLL ↔ JídelnaSQL Parity Audit — 0.2.1

Forenzní srovnání business logiky a safety gate. Legacy source:
`C:\Work\projects\JidelnaSQL` (read-only). JLL branch:
`fix/0.2.1-jidelnasql-parity-safety`.

| Oblast | Legacy důkaz | Před | Po | Stav |
|---|---|---|---|---|
| periodická kategorie | `prihlas.pas` / `uloz_prihlasku*` používá `prihlas.kategorie`; reporty `p.kategorie` | JLL ceny/reporty z `stravnik.kategorie` | `OrderRow.kategorie`; ceny/limit z periodické kat.; reporty join na `p.kategorie`; scope stále `s.kategorie` | PROVEN |
| serving write | `zapis_odber` / `zapisodebral` v LAB DB | permission + category, bez LAB identity / gate | `SERVING_WRITE_GATES`, LAB identity, `stav='A'`, `deleted=false`, volitelný `evidcislo` | PROVEN |
| unsubscribe | `objednavka_minus` nekontroluje `zverejneny` | `MENU_DELETE` vyžadoval `exact_menu_available` | DELETE bez zveřejnění; ADD/CHANGE stále vyžadují | PROVEN |
| legacy users | `uzivatelform.pas` `test_new_user_id`; `user_role` | INSERT bez `id`, bez rolí | `test_new_user_id(0)` + INSERT `id` + klon `user_role` z VED; `heslo=''` | PROVEN |
| operator/audit semantics | JLL design (bez PIN UX) | docs říkaly „bypass jen VED“ | provozní Flet session = zvolený operátor; bypass = celá BusinessSession; SUP = strong reauth | PROVEN |
| deadline bypass | požadavek kitchen manager | kód True pro všechny, docs VED-only | kód beze změny chování; docs/komentáře sjednoceny | PROVEN |
| category setup | `public.kategor` master | `DISTINCT stravnik.kategorie` | setup z `public.kategor` | PROVEN |

## Serving

DB funkce: `public.zapis_odber(id)` → načte `prihlas`, nastaví znak dne v
`odebral` na `O` přes `zapisodebral` (INSERT/UPDATE), volitelně UPDATE `burza`.
`zapisodebral` vždy vrací `true`. Používá `current_date` (den v měsíci).

```text
successful DB write: PASS (odebral[day]='O', return True)
duplicate: PASS (druhý call True, stav zůstane O — idempotentní)
concurrency: PASS (2× True, finální jedno O; bez DB mutual exclusion)
rollback: PASS (vnější transaction + raise → odebral beze změny)
gate final status: PROVEN
```

Testy: `test_serving_record_pickup_real_db_write`,
`test_serving_duplicate_pickup_contract`,
`test_serving_concurrent_two_stations`,
`test_serving_zapis_odber_rollback`.

## Legacy users

```text
VED role IDs: z LAB (např. [3, 5] — ověřeno testem proti DB)
new user role IDs: shodné s VED
DB parity: PASS (id≠VED, heslo='', is_admin=false, disabled=false,
  prava/prava1/typ + user_role)
rollback: PASS (uživatel i user_role zmizí)
status: PROVEN
```

Test: `test_legacy_user_role_clone_matches_ved`.

## Periodická kategorie

LAB scénář evidcislo=29:

```text
stravnik category: 3 (B)
prihlas category: 1 (A)
price A: 78.00
price B: 88.00
actual write price: 78.00 (prihlas.cena po MENU_ADD)
financial delta: abs(kredit) == 78.00 ≠ 88.00
stravnik category unchanged: YES
prihlas category unchanged: YES (zůstává 1)
audit: udalosti typ='P' >= 1
status: PROVEN
```

Test: `test_period_category_order_write_uses_prihlas_price`.

## Otevřené otázky (záměrně fail-closed)

1. **Privacy scope:** zda má být `allowed_categories` posuzován i podle
   `prihlas.kategorie`. Bez důkazu zůstává scope na `stravnik.kategorie`.
2. **`uzivatel_id_seq` vs `test_new_user_id`:** sequence `new_user_id()` může
   být pozadu za `MAX(id)`; JLL proto kopíruje Delphi `test_new_user_id`.
3. **Periodická `prihlas.trida`:** legacy snapshot existuje; JLL reporty třídu
   z přihlášky zatím nepoužívají.
4. **Serving concurrency:** DB neposkytuje exclusive lock — obě stanice
   dostanou `true`; značka je idempotentní. Aplikační „jedna stanice vydala“
   signalizace není v DB.

## Visual UI

```text
Visual UI changes: NONE (mimo nezbytné wiring `evidcislo` u record_pickup)
```

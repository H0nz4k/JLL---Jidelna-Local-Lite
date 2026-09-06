# JLL ↔ JídelnaSQL Parity Audit — 0.2.1

Forenzní srovnání business logiky a safety gate. Legacy source:
`C:\Work\projects\JidelnaSQL` (read-only). JLL branch:
`fix/0.2.1-jidelnasql-parity-safety`.

| Oblast | Legacy důkaz | Před | Po | Stav |
|---|---|---|---|---|
| periodická kategorie | `prihlas.pas` / `uloz_prihlasku*` používá `prihlas.kategorie`; reporty `p.kategorie` | JLL ceny/reporty z `stravnik.kategorie` | `OrderRow.kategorie`; ceny/limit z periodické kat.; reporty join na `p.kategorie`; scope stále `s.kategorie` | PROVEN |
| serving write | `zapis_odber` v `main.dfm` bez scope; JLL musí být přísnější | permission + category, bez LAB identity / gate | `SERVING_WRITE_GATES`, LAB identity, `stav='A'`, `deleted=false`, volitelný `evidcislo` | PROVEN |
| unsubscribe | `objednavka_minus` nekontroluje `zverejneny` | `MENU_DELETE` vyžadoval `exact_menu_available` | DELETE bez zveřejnění; ADD/CHANGE stále vyžadují | PROVEN |
| legacy users | `uzivatelform.pas` `test_new_user_id`; `user_role` | INSERT bez `id`, bez rolí | `test_new_user_id(0)` + INSERT `id` + klon `user_role` z VED; `heslo=''` | PROVEN |
| operator/audit semantics | JLL design (bez PIN UX) | docs říkaly „bypass jen VED“ | provozní Flet session = zvolený operátor; bypass = celá BusinessSession; SUP = strong reauth | PROVEN |
| deadline bypass | požadavek kitchen manager | kód True pro všechny, docs VED-only | kód beze změny chování; docs/komentáře sjednoceny | PROVEN |
| category setup | `public.kategor` master | `DISTINCT stravnik.kategorie` | setup z `public.kategor` | PROVEN |

## Otevřené otázky (záměrně fail-closed)

1. **Privacy scope:** zda má být `allowed_categories` posuzován i podle
   `prihlas.kategorie`. Bez důkazu zůstává scope na `stravnik.kategorie`.
2. **`uzivatel_id_seq` vs `test_new_user_id`:** sequence `new_user_id()` může
   být pozadu za `MAX(id)`; JLL proto kopíruje Delphi `test_new_user_id`.
3. **Periodická `prihlas.trida`:** legacy snapshot existuje; JLL reporty třídu
   z přihlášky zatím nepoužívají.

## Visual UI

```text
Visual UI changes: NONE (mimo nezbytné wiring `evidcislo` u record_pickup)
```

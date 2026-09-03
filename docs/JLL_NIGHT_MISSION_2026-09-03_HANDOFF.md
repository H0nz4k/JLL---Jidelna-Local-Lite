# JLL noční mise 2026-09-03 – ranní handoff

NOČNÍ MISE: **PARTIAL**

Výsledek je výrazně rozšířený a ověřený LAB klient. Otevřené části jsou
fail-closed kvůli chybějícímu autoritativnímu business kontraktu nebo
fyzickému hardware, nikoli kvůli nedokončenému známému bezpečnému kroku.

## REGRESSION BASELINE

- stav: PASS
- původní baseline: 99 PASS + 3 strict XFAIL
- Git hranice: `git rev-parse --show-toplevel` vrací `C:/Work/projects`;
  projekt proto nebyl commitován do nadřazeného guard repozitáře
- LAB guard: PASS na `127.0.0.1:5433/jll_demo_lab`

## ČTEČKA

- abstraction: `ChipReader`
- fake reader: implementován
- real adapter: `SerialLineChipReader`, pouze explicitní port
- protokol: konfigurovatelný baud/CR/LF, výchozí doložený profil 19200/CR,
  ASCII a `zfill(16)`
- timeout/cancel/reconnect/debounce: implementováno, bounded
- hardware verified: NE; nebyl připojen fyzický reader
- diagnostika: Admin záložka, `admin.reader`, PIN reauth, maskované načtení
- testy: PASS

## ČIPOVÝ KONTRAKT

- stav: PARTIAL
- `P`: přidělen – PROVEN
- `B`: blokován pro read – PROVEN; write BLOCKED
- `Z`: ztracen – PROVEN; write BLOCKED
- `V`: význam BLOCKED
- assign: datový přechod na `P` doložen, bezpečný JLL write BLOCKED
- return/block/lost: BLOCKED
- transfer/delete: reference existuje, historizace a audit nejsou doložené
- více `P`: DB dovoluje a reálná data obsahují
- audit: pouze timestamp/sync trigger; business audit BLOCKED
- hlavní blockery: lifecycle, `histcipu`, audit, mixed-writer concurrency

## ČIPOVÝ MODUL

- read: scoped seznam čipů na kartě strávníka
- search: opraven chybný filtr `A` na doložený `P`; case-insensitive kód
- write: fail-closed, neimplementován
- scope: permission + nejprve scope-safe strávník
- permissions: `chips.*`, `admin.reader`
- ActorContext/audit: pro write připravený model, write gate nepovolen
- GUI: read-only čipy, write tlačítka viditelná dle policy, vždy disabled
- testy: unit + PostgreSQL integration PASS

## STRÁVNÍK CREATE/EDIT

- create contract: PARTIAL
- edit contract: BLOCKED
- LAB service: write neimplementován
- GUI: existující read-only karta; create/edit tlačítka permission-aware,
  ale fail-closed disabled
- blockery: race `MAX(evidcislo)+1`, dva různé create kontrakty, nejasné
  defaulty/návaznosti, category-change orchestrace, audit a concurrency

## STAV VÝDEJE

- stav: implementovaný read-only LAB full-day preview; kontrakt PARTIAL
- data: typ/menu, objednáno, vydáno, zbývá
- scope: `pickup_status.view` + `allowed_categories`
- výkon: jeden dávkový dotaz, žádné N+1
- omezení: není potvrzeno, zda autoritativní agregace má být celý den nebo
  pouze aktivní výdejní okno/relace
- testy: PostgreSQL integration + async GUI PASS

## SESTAVY

- stav: implementovaný read-only foundation
- data: souhrn přihlášek a seznam strávníků
- scope: `reports.view` + `allowed_categories`
- export/PDF/print: neimplementováno; pouze preview
- testy: PostgreSQL integration + async GUI PASS

## SECURITY / PRODUKCE

- nové nálezy: lokální DB nevynucuje chip lifecycle, jeden aktivní čip ani
  bezpečný diner allocator
- mixed-writer blocker: stále FAIL, tři strict XFAIL zůstaly beze změny
- server-side scope návrh: per-site role, security-definer API/view/RLS
  varianty, revokovaný direct DML a centrální identity/policy/audit
- production write/deploy: neproveden

## TESTY

- unit: 70 PASS
- integration: 39 PASS + 3 strict XFAIL
- celkem: 109 PASS + 3 strict XFAIL
- GUI: PASS
- compileall: PASS
- Git Bash `./tools/run_lab_tests.sh`: PASS
- Git Bash `./tools/run_jll_lab.sh --probe-only`: PASS
- dočasné `jll_test_*` DB po testu: 0
- IDE lints: 0

## ZMĚNĚNÉ SOUBORY

- `pyproject.toml`
- `src/jll/chip_reader.py`
- `src/jll/policy.py`
- `src/jll/config.py`
- `src/jll/admin_service.py`
- `src/jll/read_models.py`
- `src/jll/read_service.py`
- `src/jll/gui/app.py`
- `src/jll/gui/admin_dialog.py`
- `src/jll/gui/main_window.py`
- `src/jll/gui/read_overview_dialog.py`
- `tests/unit/test_chip_reader.py`
- `tests/unit/test_identity_session.py`
- `tests/unit/test_gui_application.py`
- `tests/unit/test_read_overview_dialog.py`
- `tests/integration/test_read_service_postgres.py`
- dokumenty uvedené níže

## NOVÉ DOKUMENTY

- `docs/JLL_CHIP_CONTRACT.md`
- `docs/JLL_CHIP_MODULE.md`
- `docs/JLL_DINER_WRITE_CONTRACT.md`
- `docs/JLL_PICKUP_STATUS.md`
- `docs/JLL_REPORTS.md`
- `docs/JLL_PRODUCTION_SECURITY_DESIGN.md`
- tento handoff

Aktualizovány byly také `docs/JLL_GUI_LAB.md` a
`docs/JLL_SETUP_IDENTITY_PERMISSIONS_ADMIN.md`.

## CO JE PŘIPRAVENO K RUČNÍMU TESTU

1. V Git Bash spustit `./tools/run_jll_lab.sh`.
2. Přihlásit se a vybrat scope-safe strávníka.
3. Ověřit sekci **IDENTIFIKAČNÍ ČIPY**.
4. Otevřít **Stav výdeje** a změnit datum.
5. Otevřít **Sestavy** a oba preview taby.
6. V Adminu otevřít **Čtečka**. Bez `reader_port` musí být fail-closed.
7. Až po fyzickém ověření portu doplnit reader config a provést
   desetisekundový test čtení.

## CO ZŮSTÁVÁ

- P1: dodat autoritativní chip lifecycle/historizační/auditní kontrakt
- P1: dodat bezpečný diner allocator a produkční legacy create/edit workflow
- P1: vyřešit společný mixed-writer serverový protokol
- P2: rozhodnout full-day vs. active-window agregaci stavu výdeje
- P2: fyzický HIL test konkrétního serial readeru
- P3: scope-safe export/PDF a `reports.print`

## RIZIKA A BEZPEČNÝ STAV

Fyzický hardware nebyl použit. Produkce nebyla kontaktována. Zdrojový dump
nebyl změněn. Trvalá LAB DB byla pouze čtena; write integrační testy běžely
v izolovaných dočasných DB a všechny byly odstraněny. Neověřené chip/diner
writes zůstávají bez service implementace a v GUI disabled.

Jediný přesný další krok: získat autoritativní DEMO dokumentaci nebo zdroj
produkčního klienta, který zapisuje `B/V/Z`, `histcipu` a editaci kategorie,
včetně auditních a concurrency pravidel.

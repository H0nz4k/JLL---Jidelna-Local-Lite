# Changelog

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/)
a projekt používá [Semantic Versioning](https://semver.org/lang/cs/).
Dokud je JLL LAB/pre-production, zůstává řada `0.x.y`.

## [Unreleased]

## [0.1.0] – 2026-09-03

První Git baseline LAB aplikace. Verze shrnuje stav po fázích 0A–3C.

### Added

- Nativní Windows klient v PySide6 s responsivním layoutem (splittery,
  rozměry z `QFontMetrics`, podpora 1366×768 až 1920×1080).
- First-run Setup Wizard, login proti lokálnímu identity store s argon2
  hashem PINu, `SessionManager` a auditní `ActorContext`.
- Administrace s opětovným ověřením PINem a auditovanými operacemi.
- Scope-safe seznam a vyhledávání strávníků podle jména, evidenčního čísla
  a aktivního přiděleného čipu.
- Karta strávníka s read-only identitou, kreditem a čipovými řádky.
- Měsíční přehled přihlášek; obsahem buňky je číslo objednaného menu,
  `*` označuje nevarný den podle `varnedny`.
- Denní jídelníček s cenami, klikacím celým řádkem a klávesami `1..9`.
- Capability model povolených čísel menu z `public.sazby.pocetmenu`
  (`OrderReadService.get_allowed_menu_numbers`).
- Objednávkový backend `OrderService` s `menu_add`, `menu_change`,
  `menu_delete`, exkluzivitou exkluzivní variant `Oběd-A..D`, finanční sekvencí,
  deadline kontrolou, advisory locky a auditem.
- `ChipReader` abstrakce s fake a sériovým adapterem a explicitním portem.
- Read-only preview stavu výdeje a sestav.
- LAB guard nad prostředím, hostem, názvem databáze a
  `pg_control_system().system_identifier`.
- Git Bash utility `tools/run_jll_lab.sh`, `tools/run_lab_tests.sh`,
  `tools/restore_demo_lab.sh` a sekundární `.ps1` obaly.
- Testová sada unit, GUI a integračních testů proti jednorázové kopii LAB
  databáze, včetně tří trvalých `strict xfail` mixed-writer oracles.
- Strojový registr write gates (`src/jll/write_gates.py`) pro operace
  bez doloženého kontraktu.
- Technická dokumentace v `docs/` včetně write, chip a diner kontraktů.

### Changed

- Vzhled je centralizovaný v `src/jll/gui/theme.py`: čtyři typografické
  role, sémantické barvy, spacing a jediný QSS blok. Widgety nemají
  vlastní `setStyleSheet` ani velikosti fontu.
- Objednaný řádek jídelníčku má světle zelené pozadí celé plochy, tučný
  téměř černý text a `✓ OBJEDNÁNO`.
- Skupina jednoho typu stravy neopakuje svůj název.
- Canonical verze má jediný zdroj v `pyproject.toml`; runtime ji čte
  `jll.version.application_version()` a auditní `client_version` používá
  stejnou hodnotu.

### Fixed

- Název jídla se skládá jen z neprázdných částí, takže nevzniká prázdný
  text typu `•  •`; menu bez textu se hlásí jako nezveřejněné.
- Měsíční grid zobrazí celý měsíc bez vodorovného posuvu i pro 28, 29, 30
  a 31 dní a při font scalingu.
- Levý seznam nemá vodorovný posuv a nekrátí sloupec s evidenčním číslem.

### Security

- Produkční připojení i produkční write jsou blokované.
- Čipové zápisy a create/edit strávníka jsou fail-closed, protože jejich
  write kontrakty nejsou doložené.
- Klik do řádku ani klávesa nikdy neodhlásí jídlo; `menu_delete` vyžaduje
  explicitní tlačítko a potvrzení.
- Doložený JLL↔legacy mixed-writer concurrency blocker zůstává otevřený a
  je hlídaný třemi `strict xfail` testy.
- Veřejný repozitář neobsahuje LAB dump, `zdroje/`, logy, screenshoty,
  konkrétní instalační config ani identity s PIN hashi.
- Identifikátory konkrétní instalace jsou anonymizované na `DEMO`,
  `DEMO-LAB01` a `jll_demo_lab`; `expected_system_identifier` je
  v dokumentaci i testech pouze syntetická hodnota. Skutečné jméno
  databáze si `tools/` načtou z lokálního `config/lab.json`.

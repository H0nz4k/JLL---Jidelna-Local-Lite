# Changelog

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/)
a projekt používá [Semantic Versioning](https://semver.org/lang/cs/).
Dokud je JLL LAB/pre-production, zůstává řada `0.x.y`.

## [Unreleased]

## [0.4.1] – 2026-09-07

Payment parity hardening:

- odstraněn `float(Decimal)` z `zapisplatbu` cesty;
- chip deposit/refund > 0 opět fail-closed (legacy je hotovost + `uctenky_kasy`);
- banka není náhrada hotovosti;
- charakterizace cash chip contractu.

### Added

- `docs/JLL_PAYMENT_PARITY_HARDENING_0.4.1.md`
- `docs/JLL_CASH_CHIP_CONTRACT_0.4.1.md`
- Decimal exactness integrační testy

### Changed

- Canonical verze `0.4.1`.
- `PAYMENT_WRITE_GATES["chip_deposit"|"chip_deposit_refund"]` → BLOCKED.

## [0.4.0] – 2026-09-07

Platby + peněžní deník + atomická záloha/vratka za čip:

- historie plateb (`penden` typ `P`+`C`) na kartě strávníka;
- detail platby ze snapshotu deníku;
- oprávnění `payments.view` / `payments.post`;
- ruční zaúčtování přes `public.zapisplatbu` (jedna služba, bez hotovosti);
- atomický chip assign/return při `CenaZaPrvniCip > 0`;
- hotovost / refund / homebanking vazba zůstávají BLOCKED.

### Added

- `PaymentHistoryService`, `PaymentService`, Flet sekce Platby.
- `docs/JLL_PAYMENT_CONTRACT_0.4.0.md`,
  `docs/JLL_PAYMENT_HISTORY_0.4.0.md`,
  `docs/JLL_CHIP_PAYMENT_ATOMICITY_0.4.0.md`.

### Changed

- Canonical verze `0.4.0`.
- Chip deposit>0 už není fail-closed (vyžaduje `payments.post`).

## [0.3.1] – 2026-09-07

Chip deposit safety hardening:

- `CenaZaPrvniCip` z `public.parametry` (BACKUP);
- assign/return fail-closed při záloze > 0 před chip write;
- return PROVEN pro deposit=0;
- audit diner/chip používá DB `CURRENT_DATE`;
- skutečný create rollback po insertech + závislé řádky.

### Added

- `ChipFinancialConfig` / `docs/JLL_CHIP_FINANCIAL_CONFIG_0.3.1.md`.
- Integrační testy deposit/return/server-time/rollback.

### Changed

- Canonical verze `0.3.1`.
- `CHIP_WRITE_GATES["return"]` → PROVEN (runtime deposit gate).

## [0.3.0] – 2026-09-07

Dokončení správy strávníků a čipů (bez redesignu UI):

- create strávníka přes `pridel_cislo_stravnika` + obvyklé služby;
- personal edit s whitelistem a `updated_dt` concurrency;
- Detail čipu read-only přes `chips.view` (ne přes assign gate);
- chip assign / block / lost / unblock PROVEN; return/transfer BLOCKED;
- category change zůstává PARTIAL.

### Added

- `DinerService`, `ChipCommandService`, Flet dialogy Nový/Upravit/Detail čipu.
- `docs/JLL_DINER_WRITE_CONTRACT_0.3.0.md`, `docs/JLL_CHIP_WRITE_CONTRACT_0.3.0.md`.
- Integrační testy create/edit/chip lifecycle.

### Changed

- Canonical verze `0.3.0`.
- Write gates: diner create/edit a chip assign/block/lost/unblock → PROVEN.
- Stav čipu `V` = Volný.

## [0.2.1] – 2026-09-07

Flet UX patch + JídelnaSQL logic parity/safety:

- velikost textu bez zoomu okna, sloupec „dnes“, kompaktní Administrace,
  skrytí typů stravy bez sazby kategorie;
- periodická `prihlas.kategorie` pro ceny/reporty;
- serving write LAB gates;
- odhlášení bez nutnosti zveřejněného původního menu;
- legacy user `id` + VED role clone;
- setup kategorie z `public.kategor`.

### Added

- `SERVING_WRITE_GATES` + LAB identity guard ve `ServingService`.
- `docs/JLL_JIDELNASQL_PARITY_AUDIT_0.2.1.md`.
- Parity unit/integration testy (periodická kategorie, unsubscribe,
  serving, legacy users, setup kategor).
- Final hardening: reálný `zapis_odber` write/duplicate/concurrency/rollback,
  DB `user_role` clone parity, order-write cena z `prihlas.kategorie`.

### Changed

- Canonical verze `0.2.1`.
- Administrace → Vzhled: „Velikost textu“ škáluje `role_size` / `scaled`
  (ne `ft.Scale` celého okna).
- Administrace: sekce Info sloučí Databáze + Stanice + Audit; kompaktnější
  navigace a řádky.
- Kalendář strávníka: silné zvýraznění sloupce jen při zobrazení
  skutečného serverového dneška.
- Order/read path: business ceny a report grouping z `prihlas.kategorie`;
  privacy scope zůstává na `stravnik.kategorie`.
- `MENU_DELETE` nevyžaduje aktuální zveřejnění původního menu.
- `create_user_from_template` alokuje `uzivatel.id` (`test_new_user_id`)
  a klonuje `user_role` z VED.
- Setup probe načítá kategorie z `public.kategor`.
- Dokumentace: deadline bypass = provozní Flet `BusinessSession`, ne jen
  string `VED`; operator ≠ strong-auth identity.

### Fixed

- Typy stravy bez platné sazby pro kategorii strávníka se v měsíční mřížce
  a jídelníčku nezobrazují (např. Oběd-D u `3JARO`).
- Divergence preflight ceny (`stravnik`) vs DB core (`prihlas`) při
  změně kategorie strávníka.

## [0.2.0] – 2026-09-07

Flet desktop UX pro vedoucí kuchyně: layout, sestavy, výdej, SUP modal,
serverové „dnes“ a bypass deadline přihlášek.

### Added

- Horní navigační lišta ve Flet shellu (místo levého railu).
- Kontinuální poslech čtečky na obrazovce Strávníci; placeholder
  `čtečka nepřipojena` při nakonfigurovaném a nepřipojeném portu.
- Klávesová navigace ve výsledcích hledání (↑/↓, Enter).
- Sestavy: záložky Souhrn kategorií / Normy / Jmenný seznam, filtr dne,
  Náhled (modal) a Export PDF.
- Stav výdeje: karetní layout s velkými počty zbývajících porcí.
- `SessionPolicy.bypass_order_deadlines` pro Flet `BusinessSession`
  (termíny přihlášek/odhlášek neblokují vedoucí).
- Ruční odběr a serving service ve Flet kartě strávníka.

### Changed

- Canonical verze `0.2.0`.
- Business kalendář: `today` ze serveru (`clock_timestamp`); z parametry
  jen `TentoMesic` / `TentoRok` (AM). `denobjednavky` se nepoužívá.
- Otevření strávníka vždy skočí na serverové dnešek.
- Hlavička: `JidelnaLocalLite v…` + provozovna a datumy na druhém řádku.
- Administrace: nejdřív modal SUP přes šedé pozadí, teprve potom obsah.
- Kompaktnější karta strávníka, jídelníček s cenami, výraznější okraje
  bloků, grid všech dnů měsíce.

### Fixed

- Odhlášení/přihlášení po uplynutí studentského termínu ve Flet VED session.

## [0.1.0] – 2026-09-03

První Git baseline LAB aplikace (fáze 0A–3C) plus Flet/VED/SUP foundation,
setup 3E a noční mise (čtečka, sestavy, karta strávníka). Canonical verze
řady `0.1.x` před UX releasem `0.2.0`.

### Added

- Flet desktop UI jako cílová prezentační vrstva (`src/jll/flet_ui/`,
  `tools/run_jll_flet_lab.sh`); PySide6 zůstává referenční fallback.
- Business session bez PINu: default VED, přepínač DB uživatelů,
  SUP admin secret (`sup_secret.py`, `legacy_users.py`, `business_session.py`).
- Setup wizard ve Fletu (DB → provozovna/stanice → kategorie → SUP heslo).
- `tools/reset_jll_first_run.sh` pro bezpečný reset lokálního first-run stavu.
- Dokumentace `docs/JLL_FLET_ARCHITECTURE.md`.
- Katalog českých oprávnění (`permission_catalog.py`).
- Setup načítá provozovnu z `public.parametry` (`BACKUP` / `NameSubject`) a
  stanice z `public.stanice`.
- Administrace → Čtečka, identifikace čipu, detailní karta strávníka,
  denní sestavy a PDF export (extra `pdf`).

### Changed

- Setup Wizard: české tlačítka, kompaktnější kroky, lidský souhrn.
- `Instance ID` → `Stanice` v běžném UI.

### Fixed

- Setup Finish `'str' object has no attribute 'value'`.
- Povolení tlačítek Identifikovat čip / Karta strávníka po LAB guardu.

### Security

- Identifikace čipu nepoužívá unscoped `public.nacti_cip`.
- Karta strávníka nečte PIN, rodné číslo ani kontaktní údaje.
- Vytvořené PDF je vyloučené z verzování.

## [0.1.0-baseline] – 2026-09-03

Původní shrnutí baseline po fázích 0A–3C (historický záznam).

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

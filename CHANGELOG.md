# Changelog

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/)
a projekt používá [Semantic Versioning](https://semver.org/lang/cs/).
Dokud je JLL LAB/pre-production, zůstává řada `0.x.y`.

## [Unreleased]

## [0.5.8] – 2026-09-09

Safe multi-writer coexistence (orders):

- `OrderVersionToken` / material fingerprint + optional `seq`/`updated_dt`
- Pre-write stale reject (`ORDER_STALE_STATE`) + under-lock re-read
- Post-commit / settle probe (`ORDER_EXTERNAL_CHANGE`) bez retry war
- Live marker poll otevřené objednávkové karty (~2 s)
- Docs: `docs/MULTI_WRITER_COEXISTENCE_0.5.8.md`,
  `docs/PRODUCTION_WRITE_READINESS_0.5.8.md`
- Historické 3 mixed-writer strict XFAIL zůstávají (PREVENTION nemožná)

### Changed

- Canonical verze `0.5.8`.

## [0.5.7] – 2026-09-09

Čtečka – IKonverze / Pridat00:

- Administrace → Čtečka: přepínače **IKonverze** a **Přidat 00 na konec**.
- Pokud je alespoň jeden zapnutý, vstup ze čtečky se upraví (HEX→DEC /
  připojení `00`) a doplní zleva na 16 znaků (DB `cipy.cislo`).
- Transformace je centralizovaná v `jll.chip_code_transform` (ne v
  repository / OrderService).
- Spec: `docs/JLL_CHIP_IKONVERZE_PRIDAT00.md`.

### Changed

- Canonical verze `0.5.7`.

## [0.5.6] – 2026-09-09

Administrace → Info layout polish:

- Sekce **Počáteční nastavení** je hned pod Databáze/Stanice, aby reset
  nesjížděl dolů s rostoucím changelogem.
- Changelog je tlačítko **Zobrazit changelog** a náhled se otevírá v modalu
  (až 20 verzí), ne inline v Info stránce.

### Changed

- Canonical verze `0.5.6`.

## [0.5.5] – 2026-09-09

Installation reset / first-run restart:

- Administrace → Info: **Obnovit počáteční nastavení** po novém ověření SUP.
- Před resetem vznikne lokální recovery záloha (`config/reset-backups/...`).
- Reset nemaže ani neupravuje databázová data a následně používá
  **stejný** průvodce jako první spuštění (`SetupScreen`).
- Spec: `docs/JLL_INSTALLATION_RESET_SPEC_0.5.5.md`
  (prompt cíl 0.5.4 remapped, protože 0.5.4 je order-relation fix).

### Changed

- Canonical verze `0.5.5`.

## [0.5.4] – 2026-09-09

Order relation applicability fix:

- Opraveno objednávání u kategorií, které nepoužívají všechny globálně
  vzájemně vylučující typy stravy. JLL nyní vyžaduje měsíční řádky pouze
  pro typy skutečně platné pro danou period category (`sazby`); chybějící
  řádek relevantního typu nadále failuje bezpečně.
- Stejný filtr platí pro `vyloucenos` i `spolecnes`.
- Forenzní důkaz: `docs/ORDER_RELATION_APPLICABILITY_FORENSICS_0.5.4.md`
  (prompt cíl 0.5.3 byl přesunut na 0.5.4, protože 0.5.3 už vyšlo jako UX polish).

### Changed

- Canonical verze `0.5.4`.

## [0.5.3] – 2026-09-09

UX polish karty strávníka a HOME:

- Karta strávníka: jméno+kredit vlevo / meta vpravo; všechna akční tlačítka
  (Upravit, Detail čipu, Platby, Ruční odběr) na jednom řádku se stejnou výškou;
  **Platby** jen při `payments.view` (dialog); **Zaúčtovat platbu** jen při `payments.post`;
  zahuštěný dialog Detail čipu.
- Kladný kredit: částka + Kč zeleně (`credit_positive`, rodina barvy objednané stravy).
- Idle návrat na HOME: timer se resetuje při kliku/scrollu/přepnutí dne/měsíce/dialogu
  (ne jen při klávesnici) — při práci se HOME neobjeví.
- Flet okno se otevírá maximalizované.
- Jídelníček: den s žlutým odběrem už neroztahuje řádek; bez textu „odebráno“ (stačí žlutá);
  **Odhlásit** uvnitř zeleného řádku.
- Mřížka přihlášek: stejná šířka dnů (už se neroztahuje podle „S“ / „*“);
  detail panel stretch + `expand=1` + stejná šířka rámečku u všech buněk.
- Hlavička strávníka: „Bez čipu“ bere i aktivní čip z `public.cipy`, ne jen legacy `stravnik.cip`.
- HOME: provozovna · stanice vlevo, datum vpravo (tučně černě);
  počty porcí tučně; **Celkem** vlevo / **N porcí** vpravo.
- Seznam strávníků: při prázdném hledání je modrý fokus ve vyhledávání (ne na 1. jméně);
  šipka dolů přesune fokus na první řádek, šipka nahoru zpět do hledání.

### Changed

- Canonical verze `0.5.3`.

## [0.5.2] – 2026-09-08

Editable four-style typography:

- přesně 4 role (PRIMARY/BODY/ACTION/META) s absolutní size + bold;
- Administrace → Vzhled: editor velikosti/tučnosti, Obnovit/Uložit;
- unsaved draft nevytváří extra font signatures (žádný `preview_style`);
- sample = aktivní role, text „Po uložení“ popisuje draft;
- persistence `typography` v `lab.json` (backward compatible);
- odstraněn aktivní TextScale multiplier (100/115/130/150 % UI);
- ACTION bold = W700 (žádné W500/W600); HOME „Dnešní objednávky“ sentence case.

### Added

- `docs/JLL_TYPOGRAPHY_EDITABLE_0.5.2.md`
- `jll.typography_settings`

### Changed

- Canonical verze `0.5.2`.

## [0.5.1] – 2026-09-08

Dokončení admin a provozních UX úkolů kolem 0.5.0:

- Administrace → Kategorie: přidání/odebrání z `public.kategor` včetně názvů;
- přepínání uživatelů jen po SUP ověření;
- Admin Info: podpis HanzG, průběžné hodiny vývoje, náhled CHANGELOGu;
- admin auto-logout po 3 min nečinnosti → Strávníci/HOME;
- HOME UI polish (layout, rám, `přidat strávníka`, titul okna `JLL`).

### Changed

- Canonical verze `0.5.1`.

## [0.5.0] – 2026-09-08

HOME / Dnešní objednávky na obrazovce Strávníci:

- empty state nahrazen read-only přehledem dnešních objednaných porcí;
- serverové datum + `varnedny`, multi-menu, total porcí, scope `allowed_categories`;
- ESC a 60 s idle návrat na HOME s privacy reset (bez zahození dirty/modal);
- search vždy search (stav čtečky už nepřepisuje placeholder);
- shell subtitle: provozovna · pracoviště (datum je na HOME).

### Added

- `docs/JLL_HOME_TODAY_OVERVIEW_SPEC_0.5.0.md`
- `OrderReadService.load_home_today_overview`
- `IdleHomeController` + unit testy HOME/idle

### Changed

- Canonical verze `0.5.0`.

## [0.4.4] – 2026-09-08

Typography hardening – skutečně jen 4 textové role napříč celým Flet UI:

- centrální `role_style` / `role_weight` / `text` / `button_style`;
- font family Segoe UI;
- AST guard proti ad-hoc size/weight;
- výchozí zoom zůstává 130 %.

### Added

- `docs/JLL_TYPOGRAPHY_SYSTEM_0.4.4.md`
- `tests/unit/test_ui_typography_contract.py`

### Changed

- Canonical verze `0.4.4`.

## [0.4.3] – 2026-09-08

Desktop UI/UX polish (content-driven widths):

- kompaktní 3řádkový header karty strávníka (jméno+kredit, meta+čip, hlavní akce);
- chip lifecycle přesunut do modalu Detail čipu;
- Administrace: content-driven šířky, aktivní nav, kompaktní Uživatelé/Oprávnění;
- Vzhled: procenta bez interních názvů textových rolí;
- ruční odběr bez filtru výdejního okna (explicitní provozní požadavek).

### Added

- `docs/JLL_UI_POLISH_SPEC_0.4.3.md`
- structural tests `tests/unit/test_ui_layout_0_4_3.py`
- `ServingService.meals_ready_manual` / `stravy_k_manualni_odber`

### Changed

- Canonical verze `0.4.3`.
- Stav výdeje / Sestavy: užší content panel (bez full-width stretch).

## [0.4.2] – 2026-09-08

Automatická detekce ELATEC RFID čtečky:

- `reader_mode=auto_elatec` (default nových instalací);
- matching podle `manufacturer` / HIL VID:PID `09D8:0420`;
- hotplug a změna COM bez přenastavení;
- Flet Administrace → Čtečka: AUTO/MANUAL;
- legacy config s `reader_port` zůstává `manual`.

### Added

- `reader_discovery.py`, `AutoElatecChipReader`
- `docs/JLL_ELATEC_AUTO_DETECTION_0.4.2.md`

### Changed

- Canonical verze `0.4.2`.

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

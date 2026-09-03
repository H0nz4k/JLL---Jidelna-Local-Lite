# JLL – JidelnaLocalLite

Lokální nativní Windows správcovský klient pro jídelnu nad centrální
PostgreSQL databází. JLL je psaný v Pythonu s PySide6 (Qt Widgets) a je
určený pro běžnou denní práci hospodářky nebo vedoucí jídelny.

```text
LAB REŽIM: POVOLEN
PRODUKČNÍ WRITE: ZAKÁZÁN
```

## Záměr projektu

Hospodářka potřebuje jeden rychlý nástroj, ve kterém najde strávníka,
zkontroluje jeho stav a bezpečně provede přihlášku, změnu menu nebo
odhlášku. Výchozí workflow je:

```text
login
→ seznam strávníků
→ karta strávníka
→ přihlášky / odhlášky / informace / čipy / sestavy
```

Objednávkové zápisy nikdy neskládá GUI. Uživatelský záměr se předává jako
jediný atomický příkaz do `OrderService`, který drží finanční sekvenci,
deadline, exkluzivitu variant a audit.

## Co JLL není

- **Není náhrada `RucniOdberStrav`.** Ten je provozní nástroj pro rychlý
  výdej u terminálu; JLL je správcovský klient.
- Není webová aplikace ani kiosek.
- Není produkčně nasaditelný nástroj. Produkční write je blokovaný, viz
  [Známá omezení](#známá-omezení-a-produkční-blockery).
- Není installer; distribuce a auto-update neexistují.

## Aktuální stav

Verze `0.1.0`, LAB baseline. Aplikace se spouští pouze proti lokální
testovací databázi, jejíž identitu ověřuje LAB guard. Backend, GUI,
identity, oprávnění a objednávkový write jsou implementované a otestované;
část write kontraktů je záměrně uzavřená (write gates).

## Hlavní funkce

### Strávníci

- Scope-safe seznam a vyhledávání podle jména, evidenčního čísla a
  aktivního přiděleného čipu; jméno je diakritika-insensitive a tokenized
  AND.
- Karta strávníka s read-only identitou, kategorií, třídou, evidenčním
  číslem a kreditem.

### Přihlášky a odhlášky

- Měsíční přehled všech typů stravy; obsahem buňky je číslo objednaného
  menu, `*` znamená, že se podle `varnedny` nevaří.
- Denní jídelníček s cenou; celý řádek je klikací hit-area.
- Klik do řádku mapuje pouze bezpečný záměr `menu_add` nebo `menu_change`;
  `menu_delete` má vždy vlastní tlačítko s potvrzením.
- Počet povolených menu vychází z `public.sazby.pocetmenu`, ne z GUI.
- exkluzivní varianty `Oběd-A..D` jsou vzájemně výlučné a změna varianty je
  jediný call do `OrderService`.
- Klávesy `1..9` přihlásí nebo změní menu aktivního typu stravy.

### Čipy

- Read-only přehled čipových řádků včetně doloženého popisu stavu.
- `ChipReader` abstrakce s fake i sériovým adapterem a explicitním portem.
- Čipové zápisy jsou fail-closed.

### Stav výdeje

Read-only preview objednáno / vydáno / zbývá pro vybraný den ve stejném
scope jako ostatní čtení.

### Sestavy

Read-only preview přihlášek a seznamu strávníků.

### Setup / Login / Admin

- First-run Setup Wizard vytvoří LAB konfiguraci a prvního admina.
- Login proti lokálnímu identity store s argon2 hashem PINu.
- Administrace vyžaduje opětovné ověření PINem a auditované operace.

## Bezpečnostní model

### allowed_categories

Viditelný rozsah je konfigurovaná množina kategorií. Vynucuje ji service
vrstva v SQL, ne GUI. Vyhledávání čipu ani detail nikdy nevrátí identitu
mimo scope.

### permissions

`SessionPolicy` odděluje rozsah a oprávnění (`diners.view`, `chips.view`,
`orders.view`, `orders.change`, `pickup_status.view`, `reports.view`,
`admin.users`, `admin.reader`). Policy se načítá znovu při každém
aplikačním volání; GUI podle ní pouze deaktivuje akce.

### ActorContext / audit

Každý zápis nese konkrétního aktéra ve tvaru `<instance_id>:<short_code>`,
session id a `client_version` z canonical verze projektu. Actor nikdy není
pouze `JLL`.

### LAB guard

Před každou session se ověřuje, že `environment` je `lab`, host je
loopback, název databáze začíná `jll_`, skutečný název odpovídá konfiguraci
a `pg_control_system().system_identifier` odpovídá schválenému clusteru.
Při selhání zůstane aplikace blokovaná.

## Architektura

```text
Setup Wizard / Login
    ↓
SessionManager + ActorContext
    ↓
PySide6 MainWindow
    ↓
OrderApplicationService
    ↓
OrderReadService / OrderService
    ↓
repository vrstva
    ↓
PostgreSQL
```

DB požadavky běží mimo GUI thread přes `QThreadPool`; vyhledávání má
debounce a generační kontrolu proti přepsání novějšího výsledku. Vzhled je
centralizovaný v `src/jll/gui/theme.py` (čtyři typografické role a
sémantické barvy).

## Spuštění v Git Bash

Primární shell je Git Bash / MINGW64.

```bash
py -3.11 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[test]"
cp config/lab.example.json config/lab.json
./tools/run_jll_lab.sh
```

`config/lab.json` a `config/users.lab.json` nejsou v repozitáři; konkrétní
instalaci vytvoří Setup Wizard nebo vlastní kopie příkladového configu.

Pouze preflight bez otevření GUI:

```bash
./tools/run_jll_lab.sh --probe-only
```

Destruktivní restore LAB databáze z dumpu je guardovaný; vyžaduje explicitní
potvrzení, loopback host, název databáze `jll_*`, ověřený
`system_identifier` a lokální dump, který není součástí repozitáře:

```bash
JLL_CONFIRM_FRESH_RESTORE=YES \
JLL_LAB_SYSTEM_IDENTIFIER=<ověřený identifikátor clusteru> \
JLL_DEMO_DUMP=/cesta/k/dumpu.sql \
./tools/restore_demo_lab.sh
```

`.ps1` varianty v `tools/` jsou pouze sekundární kompatibilní obal.

## Testy

```bash
python -m compileall -q src tests
./tools/run_lab_tests.sh
```

Integrační testy si vytvoří jednorázovou kopii lokální LAB databáze a po
běhu ji odstraní. Tři testy jsou trvalé `strict xfail` oracles pro
doložený JLL↔legacy mixed-writer blocker; nesmí začít procházet bez
revize kontraktu.

## Struktura projektu

```text
src/jll/          aplikační a service vrstva
src/jll/orders/   objednávkový backend, audit a preflight
src/jll/gui/      PySide6 GUI, theme a workery
tests/unit/       unit a GUI testy
tests/integration/ testy proti jednorázové LAB databázi
tools/            Git Bash utility (launcher, testy, restore)
docs/             technická dokumentace a kontrakty
config/           příkladový LAB config bez secrets
```

Lokální referenční materiál a LAB dump (`zdroje/`) nejsou součástí
repozitáře. Interní zadání jednotlivých fází také ne, protože obsahují
ukázky reálných LAB dat.

Identifikátory konkrétní instalace jsou v repozitáři anonymizované na
neutrální `DEMO`, `DEMO-LAB01` a `jll_demo_lab`. Dokumentace i testy proto
používají zástupná jména; technická logika, měřené hodnoty a testovací
význam zůstávají nezměněné. Skutečné jméno databáze si `tools/` načtou
z lokálního `config/lab.json`, případně z `JLL_LAB_TEMPLATE`
a `JLL_LAB_DATABASE`.

## Známá omezení a produkční blockery

```text
PRODUKČNÍ WRITE NENÍ POVOLEN.
```

- JLL↔legacy mixed-writer concurrency je doložený blocker; legacy writer
  nesdílí advisory/revalidation protokol a používá zastaralý měsíční stav.
- Chip write kontrakt není PROVEN, čipové zápisy jsou fail-closed.
- Diner create/edit write kontrakt není PROVEN.
- Server-side enforcement `allowed_categories` v produkci není uzavřený.
- Centrální produkční users/permissions/audit nejsou uzavřené.
- Sériová čtečka není fyzicky HIL ověřená.
- Stav výdeje a sestavy jsou pouze read-only preview.
- Změna DB, instance a scope v administraci je read-only.
- Scaling 125 % a 150 % je ověřený automatickým testem přes velikost
  fontu, ne skutečným přepnutím Windows DPI.

## Roadmapa

```text
P1
- fyzické HIL ověření čtečky
- autoritativní chip write kontrakt
- autoritativní diner create/edit kontrakt

P2
- produkční server-side scope
- centrální identity a audit
- installer a update mechanismus

P3
- další sestavy
- další provozní workflow
```

Termíny nejsou stanovené.

## Verzování

Canonical verze je `[project].version` v `pyproject.toml`; runtime ji čte
`jll.version.application_version()` z metadat balíčku. Auditní
`client_version` používá stejnou hodnotu.

```text
PATCH  bugfix, bezpečnostní oprava, malá UX oprava
MINOR  nová funkční oblast nebo významná schopnost
MAJOR  až stabilní produkční kompatibilita nebo breaking change
```

Dokud je JLL LAB/pre-production, zůstává řada `0.x.y`.

Každá dokončená fáze: testy → CHANGELOG → případný version bump → commit →
push. Release navíc annotated tag `vMAJOR.MINOR.PATCH`. Podrobněji v
[CONTRIBUTING.md](CONTRIBUTING.md).

## Stav projektu

```text
LAB baseline 0.1.0
aktivní vývoj
produkční nasazení blokované
```

Historie změn je v [CHANGELOG.md](CHANGELOG.md), technická dokumentace
v [docs/README.md](docs/README.md).

Licence zatím nebyla stanovena.

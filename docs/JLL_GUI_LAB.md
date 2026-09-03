# JLL – PySide6 LAB GUI

## 1. Stav a účel

První nativní Windows GUI je funkční vertikální řez správcovského klienta
JidelnaLocalLite. Je určeno výhradně pro lokální LAB databázi.

```text
LAB GUI: POVOLENO
PRODUKČNÍ WRITE: ZAKÁZÁNO
```

Výchozí obrazovka je omezený seznam strávníků. Po výběru se otevře karta
strávníka s read-only identitou, kreditem, čipem (jen s `chips.view`),
měsíčním přehledem přihlášek a jídelníčkem vybraného dne.

Před hlavním oknem proběhne first-run Setup Wizard nebo přihlášení konkrétního
JLL uživatele. Hlavní pracovní plocha má seznam vlevo a kartu vpravo;
podrobnosti layoutu jsou v sekci 7.

## 2. Architektura

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
repository vrstvy
    ↓
PostgreSQL
```

GUI neobsahuje business SQL, finanční logiku ani sekvenci
`objednavka_minus` + `objednavka_plus`. Změnu exkluzivní varianty A→B/C/D předá
jako jediný záměr cílového typu do `OrderService`.

DB požadavky běží přes `QThreadPool`/`QRunnable`. Vyhledávání má debounce
300 ms a generační kontrolu, takže starší výsledek nepřepíše novější.
Připojení GUI používají `psycopg_pool` (`min_size=1`, `max_size=5`).

Read vrstva načítá typy, všech 31 měsíčních stavů, jídelníček s cenami a
kalendáře dávkově. Povolená čísla menu poskytuje jediné capability API
`OrderReadService.get_allowed_menu_numbers`; detaily kontraktu jsou
v `docs/JLL_MENU_CAPABILITIES.md`. Cenu každého kandidáta potvrzuje SQL
dotaz přes `LATERAL getcenamenuden`; kandidát bez platné ceny se nenabídne.
Překryv více sazeb stejného typu pro jeden den je fail-closed chyba
konfigurace.

Stejná service vrstva poskytuje scope-safe read-only čipy, agregovaný stav
výdeje a náhled sestav. Čtečka používá samostatné `ChipReader` rozhraní;
fyzický reader nikdy neprovádí DB write.

## 3. Bezpečnost

Před každou read/write session se ověřuje:

- `environment == lab`;
- nakonfigurovaný host je loopback;
- název databáze začíná `jll_`;
- skutečný název databáze přesně odpovídá konfiguraci;
- serverová adresa je loopback;
- `pg_control_system().system_identifier` odpovídá schválenému clusteru.

Při selhání zůstane GUI v blokovaném stavu.

`SessionPolicy` odděluje:

- viditelný rozsah `allowed_categories`;
- oprávnění (`diners.view`, `chips.view`, `orders.view`, `orders.change`).

Scope i permissions vynucuje service/application vrstva. GUI je pouze
zobrazuje a podle nich deaktivuje akce. Vyhledávání, detail i výchozí seznam
filtrují aktivní strávníky na backendu. Přesné hledání čipu nikdy nevrátí
identitu mimo scope.

Policy se načítá znovu při každém aplikačním volání. Objednávkový actor má
konkrétní tvar `<instance_id>:<short_code>` a nikdy není pouze `JLL`.

## 4. Hlavní soubory

- `src/jll/policy.py` – session scope a permissions;
- `src/jll/identity.py`, `identity_store.py`, `session.py` – login a actor;
- `src/jll/admin_service.py` – reauth a auditované admin operace;
- `src/jll/config.py` – fail-closed LAB konfigurace a connection pool;
- `src/jll/lab_guard.py` – společný LAB guard;
- `src/jll/read_models.py` – read-only model karty, měsíce a sestav;
- `src/jll/read_service.py` – scoped seznam, search, detail, měsíc, menu,
  identifikace čipu, profil strávníka a denní sestava;
- `src/jll/reports.py` – čistá agregace sestav bez SQL a bez GUI;
- `src/jll/reports_pdf.py` – volitelný PDF výstup sestavy;
- `src/jll/chip_reader.py` – fake a explicitně konfigurovaný serial reader
  včetně OS enumerace portů a factory podle konfigurace;
- `src/jll/write_gates.py` – strojové per-operation FÁZE 3A write gatey;
- `src/jll/version.py` – canonical verze a auditní `client_version`;
- `src/jll/application.py` – user intent, error mapping a refresh po write;
- `src/jll/gui/main_window.py` – nativní Windows UI;
- `src/jll/gui/theme.py` – jediné design tokeny a jediný QSS blok;
- `src/jll/gui/menu_row.py` – klikací řádek jídelníčku;
- `src/jll/gui/setup_wizard.py`, `login_dialog.py`, `admin_dialog.py`;
- `src/jll/gui/chip_dialog.py` – modální čtení čipu s timeoutem a zrušením;
- `src/jll/gui/diner_card_dialog.py` – detailní read-only karta a náhledy
  zápisových formulářů;
- `src/jll/gui/report_dialog.py` – denní sestavy a volba dne;
- `src/jll/gui/read_overview_dialog.py` – stav výdeje;
- `src/jll/gui/workers.py` – práce mimo GUI thread;
- `src/jll/gui/app.py` – sestavení aplikace a lokální logging;
- `config/lab.json` – lokální LAB policy a DB target bez hesla;
- `tools/run_jll_lab.sh` – primární bezpečný Git Bash launcher;
- `tools/run_lab_tests.sh`, `tools/restore_demo_lab.sh` – LAB utility;
- `.ps1` utility – sekundární kompatibilní varianta.

## 5. Konfigurace

Konkrétní instalace není v repozitáři; verzovaná je jen šablona
`config/lab.example.json`. Reálný `config/lab.json` vytvoří Setup Wizard
nebo vlastní kopie šablony.

`config/lab.json` má tvar (hodnoty níže jsou ilustrativní; `site_*`,
`database` i `expected_system_identifier` se liší podle instalace a
konkrétní hodnoty do repozitáře nepatří):

```json
{
  "site_name": "DEMO LAB",
  "site_id": "DEMO",
  "instance_id": "DEMO-LAB01",
  "allowed_categories": ["KAT2"],
  "host": "127.0.0.1",
  "port": 5433,
  "database": "jll_demo_lab",
  "user": "postgres",
  "environment": "lab",
  "expected_system_identifier": "1000000000000000001",
  "business_timezone": "Europe/Prague",
  "strict_config_lock": true,
  "search_limit": 30,
  "reader_port": null,
  "reader_baud_rate": 19200,
  "reader_line_end": "\r"
}
```

Heslo v souboru není. Setup jej ukládá přes Windows Credential
Manager/keyring; `JLL_LAB_DB_PASSWORD` je LAB alternativa. User identities,
Argon2id PIN hashes a permissions jsou v necommitovaném
`config/users.lab.json`.

## 6. Instalace a spuštění

Primárně v Git Bash:

```bash
py -3.11 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[test]"
./tools/run_jll_lab.sh
```

Nebo dvojklikem/spuštěním:

```text
run_jll_lab.bat
```

Samotný preflight bez otevření GUI:

```bash
./tools/run_jll_lab.sh --probe-only
```

Launcher neprovádí restore ani jiný destruktivní DB krok.

## 7. Responsive layout

Hlavní plocha je `QSplitter(Qt.Horizontal)`:

```text
levý panel    ~30 % šířky, min 300 px, max 450 px
pravá karta   zbytek
```

Uživatel může splitter posunout ručně. Pravá karta je vnořený
`QSplitter(Qt.Vertical)`:

```text
horní pane    hlavička strávníka, kompaktní čipy, navigace měsíce, měsíční grid
dolní pane    JÍDELNÍČEK VYBRANÉHO DNE ve QScrollArea
```

Po každém renderu se horní pane zmenší na výšku obsahu gridu, takže volné
místo dostane jídelníček. Grid nepoužívá `fixedHeight`; výška řádku i šířka
popisků vycházejí z `QFontMetrics`, aby layout přežil Windows scaling.

Šířka dnů se počítá z viewportu:

```text
day_width = viewport_width // počet_dní   (minimum 17 px)
```

Přepočet spouští `resizeEvent` i event filter na viewportu gridu, takže se
šířky srovnají i po dosednutí layoutu. Vodorovný posuv gridu je pouze
fallback pod podporovanou šířkou nebo při extrémním font scalingu. Celá
aplikace nemá vodorovný posuv; scrolluje se jen uvnitř obsahových oblastí.

Podporovaná rozlišení:

```text
1366×768   (minimum okna 1024×600)
1440×900
1920×1080
scaling 100 %, 125 %, 150 %
```

## 8. Menu je číslo a celý řádek je klikací

Objednávka je kombinace typu stravy a čísla menu. Řádek jídelníčku má tvar:

```text
[1]  Pad thai s kuřecím masem      88,00 Kč   [Přihlásit 1]
```

- řádek je jeden widget `MenuRow`; klik na číslo, název, cenu i prázdnou
  plochu je jedna hit-area (popisky mají `WA_TransparentForMouseEvents`);
- typ stravy je nadpis nad řádky, nikdy není zaměněn za číslo menu;
- DEMO `Oběd-A..D` zůstávají jedna vizuální skupina „OBĚD“, ale každý typ má
  vlastní nadpis a vlastní čísla menu;
- skupina jednoho typu svůj název neopakuje (`SVAČINA`, ne `SVAČINA` +
  `Svačina`);
- povolená čísla přicházejí z `public.sazby`, GUI je nepočítá;
- nezveřejněný jídelníček se hlásí jednou za skupinu, ne pro každý typ;
- název jídla skládá `string_agg` jen z neprázdných částí, takže nevzniká
  prázdný text typu `•  •`; menu bez jakéhokoli textu je nezveřejněné;
- v měsíčním gridu je hlavním obsahem buňky číslo objednaného menu, DB stav
  se zobrazí jen v LAB diagnostice.

Klik do řádku nese pouze bezpečný přihlašovací záměr:

```text
nic objednáno        → menu_add
objednáno jiné menu  → menu_change
objednaný řádek      → nic; řádek není klikací
```

Odhlášení je vždy jen explicitní tlačítko `Odhlásit N` s potvrzením. Stejné
pravidlo platí pro klávesy `1..9`, takže žádná rychlá interakce nemůže
objednávku smazat omylem.

Objednaný řádek má velmi světle zelené pozadí celé plochy, téměř černý tučný
text, `✓ OBJEDNÁNO` a tmavě zelený akcent čísla menu. Hover objednaný stav
nepřebíjí.

Měsíční grid:

```text
priorita obsahu buňky   číslo objednaného menu > `*` = nevaří se > prázdno
`*`                     jen podle cooking-day zdroje (varnedny), ne podle víkendu
víkend                  pouze klidné pozadí
vybraný den             nejvýraznější podbarvení
dnešek                  jen jemný tón, nikdy nepřekryje číslo ani `*`
```

Tooltip buňky:

```text
Oběd-C
04.09.2026
Menu 1
```

## 8a. Design tokeny a typografie

Veškerý vzhled je v `src/jll/gui/theme.py`. Widgety nemají vlastní QSS ani
vlastní velikosti fontu; `theme.apply_role` nastaví font a dynamickou
property `textRole`, kterou používá jediný centrální QSS blok.

```text
T1  PRIMARY   15,5 pt bold      jméno strávníka, hlavní nadpis
T2  BODY      11,5 pt regular   jména v seznamu, názvy jídel, běžný text
T3  ACTION    11,0 pt bold      typ stravy, tlačítka, sekční nadpisy, objednaná položka
T4  META      10,0 pt regular   cena, kategorie, třída, ev. číslo, status, diagnostika
```

Pátý styl neexistuje; test `test_typography_uses_only_four_central_roles`
kontroluje každý `QLabel` a `QPushButton` v okně a
`test_gui_modules_have_no_local_font_or_color_styling` zakazuje lokální
`setStyleSheet`, `font-size`, `setPointSize` i `QFont(` mimo theme.

`theme.TextScale` (`NORMAL`, `LARGE`, `EXTRA_LARGE`) je připravený jediný bod
pro budoucí režimy Normální / Velký text / Velmi velký text.

Sémantické barvy: `background`, `surface`, `border`, `text_primary`,
`text_secondary`, `accent`, `selected`, `today`, `ordered_background`,
`ordered_selected`, `ordered_accent`, `ordered_text`, `non_cooking`,
`weekend`, `disabled`, `danger`, `lab_warning`. Dále theme drží `SPACING`,
`RADIUS`, `BORDER_WIDTH`, `CONTROL_HEIGHT` a `ROW_HEIGHT`.

Tlačítka mají jednotný styl a variantu `primary`, `secondary`,
`destructive`, `pending` nebo `compact`; disabled stav je řešen QSS, ne
ad-hoc barvou. Minimální hit target řádku je `ROW_HEIGHT` (32 px).

## 9. UI workflow

1. First-run setup vytvoří instalaci a prvního admina; další start zobrazí login.
2. Aplikace ověří LAB guard a načte pouze první omezenou stránku strávníků.
3. Search podporuje jméno, evidenční číslo a aktivní přidělený čip
   (`public.cipy.stav='P'`); zastaralé `stravnik.cip` není identifikační
   fallback. Jméno je
   diakritika-insensitive a tokenized AND.
4. Kliknutí otevře kartu strávníka.
5. Měsíční mřížka ukazuje objednaná menu, `*` pro nevarné dny, dnešek a výběr.
   Primární navigace je `‹ ZÁŘÍ 2026 ›`; date picker je sekundární. Změna
   měsíce zachová strávníka i search a načítá se asynchronně.
6. Kliknutí na buňku vybere den a současně aktivuje typ stravy toho řádku.
7. Klik do řádku jídelníčku i kontextové tlačítko mapují záměr na `menu_add`
   nebo `menu_change`; `menu_delete` má vždy vlastní tlačítko a potvrzení
   s typem stravy a číslem menu.
8. exkluzivní A–D jsou jedna vizuální skupina. Volba jiné varianty vytvoří jediný
   call do `OrderService`.
9. Po úspěchu i business chybě se stav vždy znovu načte z databáze.
10. Karta zobrazuje všechny čipové řádky dostupné pro vybraného strávníka.
    `P` a `Z` mají doložený popis; neznámé stavy nejsou domýšleny.
11. **Stav výdeje** zobrazuje pro datum objednáno/vydáno/zbývá; `ZBÝVÁ` je
    dominantní hodnota a dokončený řádek je zeleně odlišený.
12. **Sestavy** otevřou denní sestavu: jmenný seznam, jídelníček s porcemi,
    kategorie a rozpad norem, s volbou `Dnes`, `Zítra`, následujícího
    varného dne nebo konkrétního data.
13. **Identifikovat čip** u search baru načte čip a otevře kartu jeho
    vlastníka, pokud je ve scope; jinak zobrazí jen bezpečnou hlášku.
14. **Karta strávníka** je detailní read-only pohled (Údaje, Finance, Čipy).
    Náhledy `Editovat strávníka` a `Nový strávník` mají zakázané `Uložit`,
    protože jejich write kontrakty nejsou doložené.

## 9a. Detailní karta strávníka

Karta zobrazuje jen sloupce s doloženým významem: evidenční číslo,
kategorii a její název, normu, třídu, datum narození, variabilní symbol,
způsob platby, stav a poznámky. PIN, rodné číslo, kontaktní ani přihlašovací
údaje se z databáze vůbec nečtou.

Finance ukazují disponibilní kredit stejným výpočtem, jaký používá
objednávkový preflight, minimální povolený zůstatek z `public.kategor` a
zbývající prostor do limitu. Nedoložené finanční sloupce se nezobrazují.

Sekce Čipy vyžaduje `chips.view` a je pouze pro čtení. Právě identifikovaný
čip je zvýrazněný tučně. Karta se načítá mimo GUI thread; při chybě se
nezobrazí ani částečná identita, jen bezpečná hláška.

## 10. Klávesový workflow

```text
Ctrl+F      aktivuje search
↑ / ↓       prochází výsledky
Enter       otevře vybraného strávníka
Esc         vyčistí search, poté zavře kartu
1..9        přihlásí nebo změní dané číslo menu aktivního typu stravy
```

Aktivní typ stravy se nastaví kliknutím na buňku měsíčního gridu nebo na
řádek jídelníčku a je vypsaný v nadpisu jídelníčku i s dostupnými čísly.
Digit shortcut se neaktivuje, pokud má fokus textový vstup (`QLineEdit`,
`QTextEdit`, `QDateEdit`) nebo pokud číslo není v capability z `sazby`.
Číslo již objednaného menu jen připomene, že odhlásit lze pouze tlačítkem.

DB stavy `N/S/*/...` nejsou hlavní UX; zobrazí se jen v LAB diagnostice.
SQL traceback se uživateli nezobrazuje. Dialog obsahuje pouze bezpečný kód
a correlation ID.

## 11. Logování

Lokální rotovaný log je `logs/jll-lab.log`. Zaznamenává start, LAB
preflight, typ akce, `evidcislo`, bezpečný error code a dobu požadavku.
Heslo se neloguje. Search text ani nalezená jména se nelogují.

## 12. Ověření

Automatické testy pokrývají:

- české mapování všech business error codes;
- add/delete/change intent;
- A→B jako jediný call do `OrderService`;
- backendové vynucení `orders.change`;
- refresh po úspěšném i neúspěšném write;
- stale search result guard;
- worker mimo GUI thread;
- měsíční mřížku;
- category-safe první stránku, search a detail v PostgreSQL;
- skutečný add → A→B → delete workflow v izolované kopii LAB DB;
- deadline error a out-of-scope search bez úniku identity.
- fake/serial reader lifecycle, timeout, cancellation a explicitní port;
- backend permission `admin.reader` a maskovanou reader diagnostiku;
- scope shodu souhrnu přihlášek a stavu výdeje;
- asynchronní GUI náhledy stavu výdeje a sestav;
- layout smoke pro 1366×768, 1440×900 a 1920×1080;
- layout při font scalingu 10/12/15 pt;
- měsíční grid pro 28, 29, 30 i 31 dní bez vodorovného posuvu;
- neexistenci overlapu gridu, jídelníčku a diagnostiky;
- capability povolených menu proti `public.sazby` v LAB DB;
- oddělení typu stravy a čísla menu;
- `menu_add` i `menu_change` číslem menu přes `OrderService`;
- klávesy 1..9 včetně ochrany textových vstupů a limitu z `sazby`;
- zachování strávníka, dne a search textu po resize;
- `*` pro nevarný pracovní den i nevarný víkend;
- varný víkend a varný pracovní den bez `*`;
- prioritu objednaného čísla menu nad `*`;
- klik do názvu, ceny i prázdné plochy řádku jako `menu_add`/`menu_change`;
- ochranu objednaného řádku před auto-odhlášením klikem i klávesou;
- explicitní `Odhlásit` včetně potvrzovacího textu;
- full-row ordered state (pozadí, tučný téměř černý text, `✓ OBJEDNÁNO`);
- varianty tlačítek `primary`, `secondary` a `destructive`;
- výraznější vybraný den než jemný marker dneška;
- pouze 4 typografické role u všech labelů a tlačítek;
- neexistenci lokálního QSS a lokálních velikostí fontu mimo theme;
- odstranění duplicitního názvu u skupiny jednoho typu stravy;
- enumeraci COM portů, `build_chip_reader`, uložení nastavení čtečky přes
  `admin.reader` + reauth a zachování nedostupného nakonfigurovaného portu;
- modální čtení čipu: úspěch, timeout, zrušení, nedostupná čtečka a odmítnutí
  neomezeného timeoutu;
- všechny čtyři výsledky identifikace čipu včetně toho, že čip mimo scope
  neotevře kartu a nevrátí žádnou identitu;
- stavy čipu `P`, `B`, `Z` i nedoložený stav bez interpretace `V`;
- viditelnost a tooltip tlačítka `Identifikovat čip` podle `chips.view`
  a podle dostupnosti čtečky;
- kartu strávníka: doložené sloupce bez tajných hodnot, finance včetně
  zbývajícího prostoru do limitu, čipy, zvýraznění identifikovaného čipu
  a chybový stav bez částečné identity;
- náhledy editace a nového strávníka se zakázaným `Uložit`;
- sestavy: řazení s diakritikou, seskupení podle kategorií, matici norem
  s nulami, prázdný den, `Dnes`/`Zítra`/následující varný den, výběr data,
  chybový stav a viditelnost PDF podle `reports.print`;
- PDF export synteticky (hlavička, `%%EOF`, úklid dočasného souboru,
  odmítnutí jiné přípony a české glyfy ve zvoleném fontu);
- panel stavu výdeje: dominantní `ZBÝVÁ`, kontextové počty, zelený stav
  dokončeného řádku z theme a překreslení bez zbytků starých řádků;
- scope-safe identifikaci čipu, profil strávníka a denní sestavu proti
  klonu LAB databáze, včetně shody kreditu s objednávkovým preflightem
  a shody součtu porcí se souhrnem přihlášek.

Ruční/automatizovaný startup probe byl proveden nativně ve Windows.
End-to-end workflow používá dočasnou databázi vytvořenou z
`jll_demo_lab`; po testu je odstraněna.

Poslední ověření (noční mise po FÁZI 3D):

```text
compileall: PASS
unit testy: 195 PASS
celá sada: 243 PASS + 3 očekávané strict XFAIL
Git Bash test launcher: PASS
```

Předchozí ověření (FÁZE 3C): 129 unit PASS, celkem 169 PASS + 3 strict XFAIL.

Vizuální smoke proti LAB DB (mimo repozitář,
`%TEMP%/jll_layout_smoke_3c`), kategorie `KAT5`:

```text
2026-09-03  1366×728   30 dní, day_px 32, 45 buněk `*`, 2 objednané řádky
2026-09-03  1920×1040  30 dní, day_px 33, bez vodorovného posuvu
2026-09-10  1366×728   30 dní, 5 klikacích řádků `Přihlásit 1`
2023-12-04  1366×728   31 dní, 75 buněk `*`, jídelníček nezveřejněn
```

`*` v září 2026 pokrývá 8 víkendových dnů i státní svátek 28. 9., takže
nevarný pracovní den je doložený i na reálných datech.

Ve smoke datu 2026-09-03 už byl deadline `menu_add`/`menu_change` vyčerpaný,
takže byl vizuálně ověřen objednaný řádek, ochrana objednaného řádku a `*`;
klik do řádku jako `menu_add`/`menu_change` je ověřen na 2026-09-10 a
automatickými testy s řízenou dostupností.

Vizuální smoke vyžaduje nativní platformu (`QT_QPA_PLATFORM=windows`);
v `offscreen` režimu, který používají testy, nejsou dostupné systémové fonty
a export by obsahoval jen prázdné glyfy.

Screenshot se necommituje: zdrojový LAB dump obsahuje jména strávníků a
obrazový export by vložil osobní údaje do repozitáře.

## 13. Známé limity

- Nový strávník, editace strávníka a chip writes jsou fail-closed, protože
  jejich write kontrakty nejsou plně doložené.
- Tlačítka těchto operací používají společný registr `PARTIAL/BLOCKED`;
  změna permission sama write nezapne.
- Stav výdeje i sestavy jsou pouze pro čtení; JLL nevydává ani neúčtuje.
- Serial reader adapter je implementovaný podle zdrojové reference, ale
  fyzický hardware nebyl připojen ani HIL ověřen. Stav `Připojena` proto
  znamená jen to, že nakonfigurovaný port vidí OS.
- Identifikace čipu i test čtečky jsou ověřené pouze s `FakeChipReader`
  a automatickými testy, ne skutečným přiložením čipu.
- PDF export je volitelný; bez `reportlab` nebo bez systémového TrueType
  fontu se ohlásí česky a zbytek sestav zůstane funkční.
- Login, dynamické permissions a lokální Admin foundation jsou implementovány.
- Změna DB/instance/scope v administraci zůstává read-only.
- GUI není installer a nemá auto-update.
- Měsíční grid při šířce okna pod podporovaným minimem nebo při extrémním
  font scalingu spadne na vodorovný posuv uvnitř gridu; ostatní části
  layoutu se nerozbijí.
- Levý seznam nemá vodorovný posuv; dlouhá jména se zkracují elipsou a plný
  text je v tooltipu.
- Klávesy `1..9` fungují jen pro aktivní typ stravy; typ se volí kliknutím
  na buňku měsíce nebo na řádek jídelníčku, ne fokusem.
- Odhlášení nelze provést klikem do řádku ani klávesou; je to záměrná
  ochrana proti nechtěnému smazání objednávky.
- Režimy velikosti textu jsou v theme připravené, ale zatím nejsou v UI
  přepínatelné.
- Ruční posun splitteru se pamatuje jen pro běžící sezení; po restartu
  aplikace platí opět výchozí podíl.
- Scaling 125 % a 150 % je ověřen automatickým layout testem přes velikost
  fontu, ne skutečným přepnutím Windows DPI.
- Produkční připojení není podporováno.
- Produkční write zůstává blokován prokázanou JLL↔legacy mixed-writer
  nekonzistencí z FÁZE 1C.

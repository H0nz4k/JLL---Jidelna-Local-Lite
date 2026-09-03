# JLL čipový modul – LAB

## Implementovaný rozsah

- `ChipReader` rozhraní: `start`, `stop`, `read_once`, `status`,
  `device_info`.
- `FakeChipReader`: deterministické LAB/test čtení, timeout, cancellation a
  duplicate debounce.
- `SerialLineChipReader`: explicitně nakonfigurovaný COM port, doložený
  serial-line protokol, bounded timeout, cancellation, reconnect a
  diagnostika z OS enumerace portů.
- Admin záložka **Čtečka**: stav, zařízení, maskované poslední načtení,
  výběr COM portu z OS enumerace, baudrate, ukončení řádku, uložení
  nastavení a modální test čtečky.
- Hlavní obrazovka: tlačítko **Identifikovat čip** u vyhledávacího pole.
- karta strávníka: všechny řádky `public.cipy` patřící scope-safe vybranému
  strávníkovi; nedoložené stavové kódy jsou tak označené.

## Nastavení čtečky v administraci

COM porty se nabízejí jen z OS enumerace (`serial.tools.list_ports`); model,
VID ani PID se nedopočítávají a port se nikdy nehádá. Uložení vyžaduje
`admin.reader` i platnou PIN reautentizaci a zapisuje pouze ne-secret
hodnoty do instalační konfigurace. Reader config se nikdy nedotkne databáze.

Nakonfigurovaný port, který zrovna není v systému vidět, zůstane v seznamu
označený jako nedostupný, aby uložené nastavení nezmizelo jen kvůli
odpojenému kabelu.

## Test čtečky a identifikace čipu

Modální dialog `ChipReadDialog` ukazuje `Přiložte čip ke čtečce…`, má vždy
konečný timeout (0–30 s), tlačítko `Zrušit` nastavující cancel event a
lidskou českou hlášku pro timeout, zrušení i chybu čtečky. Nezapisuje do
databáze a používá se pro admin diagnostiku i pro identifikaci čipu.

Workflow **Identifikovat čip** (`chips.view`) načte čip, normalizuje kód a
provede scope-safe lookup přes `OrderReadService.identify_chip()`:

- vlastník v `allowed_categories` → otevře se jeho karta strávníka se
  zvýrazněným právě načteným čipem a doloženým stavem (`P` přidělen,
  `B` blokován, `Z` ztracen, ostatní jako nedoložený stav; `V` se
  neinterpretuje);
- vlastník mimo scope → pouze `Čip není pro tuto provozovnu dostupný.`
  bez jména, evidenčního čísla, kategorie i třídy;
- čip bez použitelného vlastníka → `Čip nemá dostupného vlastníka.`;
- neznámý kód → `Čip nebyl nalezen.`

Lookup nepoužívá `public.nacti_cip`, protože ta nefiltruje scope. Identita se
do výsledku dostane jen přes JOIN omezený na `allowed_categories`. Bez
nakonfigurované čtečky je tlačítko disabled a tooltip odkáže do administrace.

Reader reference používá 19200 baud, ukončení `CR`, ASCII text a doplnění
na 16 znaků zleva nulami. VID/PID ani konkrétní model zařízení nebyly ve
zdrojích doloženy, proto se port nikdy automaticky nevybírá.

## Konfigurace

Volitelné položky v `config/lab.json`:

```json
{
  "reader_port": "COM7",
  "reader_baud_rate": 19200,
  "reader_line_end": "\r"
}
```

Bez `reader_port` aplikace používá fail-closed `UnavailableChipReader`.
Port se nastavuje pouze po ručním ověření skutečného zařízení. Hesla ani
načtený celý čip se v reader diagnostice nelogují.

Pro diagnostiku je nutné `admin.reader` a platná PIN reautentizace. Pouhé
GUI skrytí není autorita; permission ověřuje `AdminService`.

## DB část

`chips.view` povoluje pouze scoped read. Dotaz začíná už ověřeným strávníkem
v `allowed_categories`; lookup čipu nikdy nevrací vlastníka mimo scope.

`chips.assign`, `chips.return`, `chips.block` a `chips.lost` existují v
policy modelu, ale DB write gate je `PARTIAL`. Tlačítka jsou proto disabled a
žádný write service ani business SQL v GUI neexistuje.

FÁZE 3A přidává strojový fail-closed registr `src/jll/write_gates.py`.
Rozlišuje `PARTIAL` a `BLOCKED` pro každou operaci; `require_proven()`
odmítne použít kterýkoli aktuální gate jako write oprávnění. GUI tooltipy a
diagnostické properties používají tentýž registr, takže text a skutečné
zablokování nemají dvě oddělené pravdy.

## Ověření a omezení

Unit testy simulují serial port i fake reader, pokrývají enumeraci portů,
`build_chip_reader`, permission a reauth u uložení nastavení, timeout,
cancellation a všechny čtyři výsledky identifikace včetně ochrany identity
mimo scope. Integrační test načítá scoped čipy z izolované LAB kopie a
ověřuje, že out-of-scope čip nevrátí žádnou identitu.

Fyzický reader nebyl připojen ani ověřen; software PASS není HIL potvrzení.
Stav `Připojena` proto vychází z OS enumerace portu, ne z odpovědi zařízení.

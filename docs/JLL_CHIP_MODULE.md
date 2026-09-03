# JLL čipový modul – LAB

## Implementovaný rozsah

- `ChipReader` rozhraní: `start`, `stop`, `read_once`, `status`,
  `device_info`.
- `FakeChipReader`: deterministické LAB/test čtení, timeout, cancellation a
  duplicate debounce.
- `SerialLineChipReader`: explicitně nakonfigurovaný COM port, doložený
  serial-line protokol, bounded timeout, cancellation, reconnect a
  diagnostika z OS enumerace portů.
- Admin záložka **Čtečka**: stav, zařízení, maskované poslední načtení a
  desetisekundový test.
- karta strávníka: všechny řádky `public.cipy` patřící scope-safe vybranému
  strávníkovi; nedoložené stavové kódy jsou tak označené.

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

Unit testy simulují serial port i fake reader. Integrační test načítá scoped
čipy z izolované LAB kopie. Fyzický reader nebyl připojen ani ověřen; software
PASS není HIL potvrzení.

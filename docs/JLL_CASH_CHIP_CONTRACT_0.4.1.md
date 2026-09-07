# JLL cash chip contract 0.4.1

## Legacy call sites (PROVEN)

### Assign — `stravnik.pas` `VyberzaCip`

```pascal
Edit1.Text := '1';                 // hotově
Edit5.text := '0';                 // mesic
castka := Backup.CenaZaPrvniCip;   // kladná
typZauctovani := 3;
```

### Return — `stravnik.pas` `VratzaCip`

```pascal
Edit1.Text := '1';
castka := -Backup.CenaZaPrvniCip;
typZauctovani := 4;
```

## typplatby (PROVEN)

LAB `public.typplatb`: `1` = **Hotově**.

Chip path **musí** použít `1`, pokud se má tvrdit legacy parita.
Nahrazení bankou/`99` je produktová odchylka, ne hardening.

## účet (PROVEN default dialogu)

`PlatbaDlg.NastavUcet` → `TTypUct` → `ComboBox2.itemindex := 1`.

LAB `typuct` pořadí: `SKOL`, `STRAV`, `UBYT` → index 1 = **`STRAV`**.

Není hardcode ze `stravnik.ucet`; je to default UI index číselníku.
Historické `penden` řádky typ `C` dominantně mají `ucet='STRAV'`.

## typsluzby (PROVEN call site + DB)

`Platba.pas` pro `typZauctovani in [3,4]` volá:

```pascal
ZapisPlatbu(..., typsluzby='', den=0)
```

`DataModule1.ZapisPlatbu` **před** DB doplní `defaultniStrava`, pokud je prázdné.

LAB přímý SQL `zapisplatbu(..., ptypsluzby='')`:

- `penden.typstravy` = `''`
- `platbatm`/`platbabm` beze změny (`mesic=0` + prázdná/ne-strava služba)

Historické chip řádky mají vyplněné `Oběd-A` atd. (= výsledek Delphi default fill).

## mesic / rok / den (PROVEN)

- `mesic = 0`, `den = 0`
- `rok`: Delphi `mesic<>tentomesic` → `budoucirok`, přičemž `budoucirok:=Tentorok`
- `zapisplatbu` neaktualizuje `platbatm`/`platbabm` když `pmesic=0`
- finanční evidence zálohy = řádek `penden` typ **`C`**

Znaménka v `penden`:

- deposit: `+CenaZaPrvniCip`
- refund: `-CenaZaPrvniCip`

## Pokladní doklad (PROVEN side-effect, NOT ported)

Po úspěšném `ZapisPlatbu`, pokud `edit1='1'`:

1. volitelně EET (`ModulEET`) — LAB **`ModulEET=0`** → EET neaktivní
2. `SaveTexty(...)`
3. `INSERT INTO uctenky_kasy (...)` přes `RunSQL`
4. `inc(CisloPrijmovehoDokladu)` + zápis do parametry/INI
5. tisk QuickReport (post-UI; tiskárna ≠ business commit boundary)

### Assign (typZauctovani=3)

- UI doklad: **příjmový** (`P` + číslo)
- `uctenky_kasy` insert s `zpusob_platby='1'`

### Return (typZauctovani=4)

- UI doklad: **výdajový** (`V` + číslo)
- stejná insert větev (větev caption ≠ příjmový StrConst214)

`uctenky_kasy` je součást provozní evidence hotovosti → pro PROVEN cash chip
musí být ve stejné JLL transakci jako `penden`+chip.

## EET (PROVEN LAB)

`parametry.ModulEET = 0` → bezpečně neportovat.
FIK/BKP nejsou povinné při vypnutém modulu.
To **neodstraňuje** povinnost `uctenky_kasy` + číslování dokladu.

## Tisk vs commit

Tisk je UI side-effect po DB zápisu. Selhání tiskárny legacy typicky
neroluje účetní zápis. JLL proto nesmí vyžadovat tisk k DONE.
Absence `uctenky_kasy` řádku ale znamená nekompletní hotovostní contract.

## JLL 0.4.1 status

```text
cash chip deposit/refund = BLOCKED
```

Dokud nebude portován minimálně:

- `typplatby=1`
- účet dle dialog defaultu (`STRAV` / index 1)
- `penden` typ C, mesic 0
- `uctenky_kasy` + `CisloPrijmovehoDokladu`
- atomicita s chip lifecycle

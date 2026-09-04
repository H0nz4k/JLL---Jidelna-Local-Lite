# JLL Sestavy – read-only jmenné sestavy a souhrny

Stav: **IMPLEMENTOVÁNO jako GUI sestava s volitelným PDF**

Sekce **Sestavy** vyžaduje `reports.view` a otevírá dialog pro jeden zvolený
den. Backend vrací kompletní `DailyReport` z jedné read transakce, takže
náhled neblokuje GUI a nevzniká N+1 dotaz na strávníka.

## Obsah sestavy

`OrderReadService.load_daily_report(target)` vrací:

- **jmenný seznam** (`NamedOrderRow`): jméno, kategorie, typ stravy, číslo
  menu, norma a název objednaného jídla;
- **jídelníček a porce** (`OrderReportRow`): typ stravy, menu, počet porcí a
  název jídla;
- **kategorie** (`CategoryOrderSummary`): kategorie, název, norma a počet
  objednávek;
- **normy** (`NormMenuSummary`): rozpad menu podle normy pro každý typ
  stravy.

Všechny čtyři dotazy vždy aplikují efektivní `allowed_categories`. Přihlášky
používají číselný marker `1..9` v příslušném `dXX`; názvy jídel jsou dávkově
agregované z publikovaného českého jídelníčku. Jmenný seznam fail-closed
skončí chybou nad limitem řádků namísto tichého oříznutí.

## Agregace

`src/jll/reports.py` neobsahuje SQL ani GUI. Řeší jen:

- řazení jmenného seznamu (jméno, typ stravy, menu, evidenční číslo);
- řazení, ve kterém diakritika nerozhazuje abecedu (`Čermák` mezi `Cejnar`
  a `Dvořák`); digraf `ch` se neřeší, protože bez doložené collation by šlo
  o odhad;
- volitelné rozdělení podle kategorií (`grouped`), kde kategorie bez
  objednávky nevytvoří prázdný blok;
- matici norma × menu, ve které normy `A`–`D` zůstávají i s nulou stejně
  jako v referenci.

Stejná agregace se používá pro GUI náhled i pro PDF, takže tisk nemůže
zobrazit jiná čísla než obrazovka.

## Volba dne

Dialog nabízí `Dnes`, `Zítra`, `Následující varný den` a výběr data.
`Dnes` i `Zítra` se počítají ze serverového business data, ne z hodin
stanice. `Následující varný den` používá `next_cooking_day()`, který čte
autoritativní kalendář `public.varnedny` pro zobrazované typy stravy; den se
neodvozuje z pracovního týdne. Pokud kalendář další varný den nemá, datum se
nezmění a dialog to napíše.

## PDF

PDF export je volitelný a vyžaduje `reports.print`. `reportlab` je volitelná
lokální závislost (`pip install "jidelna-local-lite[pdf]"`) a importuje se až
při skutečném exportu, takže bez něj zůstane zbytek sestav funkční a
uživatel dostane českou hlášku.

Font se hledá v systému (Segoe UI, Arial, DejaVu Sans) nebo v proměnné
`JLL_REPORT_FONT`. Žádný binární font se do repozitáře nekopíruje, takže
není potřeba řešit licenci fontu kvůli veřejnému repozitáři. Export zapisuje
přes dočasný soubor, takže přerušený tisk nepřepíše dřívější platné PDF.

Vytvořené PDF obsahuje osobní údaje strávníků. Do repozitáře nepatří a
`.gitignore` jej drží mimo verzování.

## Ověření

Unit testy pokrývají řazení včetně diakritiky, seskupení podle kategorií,
matici norem s nulami, prázdný den, přepínání dnů, chybový stav a PDF
(hlavička `%PDF-`, `%%EOF`, úklid dočasného souboru, odmítnutí jiné přípony
než `.pdf` a přítomnost českých glyfů ve zvoleném fontu).

Integrační testy proti klonu LAB databáze ověřují, že jmenný seznam i
souhrny zůstávají uvnitř `allowed_categories` a že součet porcí souhlasí se
samostatným souhrnem přihlášek.

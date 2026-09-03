# JLL čipy – forenzní kontrakt

Stav research: **FÁZE 3A PARTIAL**  
CHIP WRITE CONTRACT: **žádná operace není PROVEN pro JLL write**

## Doložené zdroje

- `zdroje/demo.sql`: autoritativní schéma lokální kopie DEMO.
- `zdroje/Stravnik_edit/osoba_new_gui_last_v.py`: referenční pomocný klient,
  nikoli autoritativní business kontrakt.
- `zdroje/Stravnik_edit/editOsobaV2/osoba20_ctk_phase2.py`: serial reader
  reference a jednoduchý create workflow.
- lokální `jll_demo_lab`: pouze read-only katalogové a agregované kontroly po
  úspěšném JLL LAB guardu.

## Schéma a invarianty

`public.cipy` obsahuje `cislo`, `id`, `stravnik`, `vydano`, `vraceno`, `stav`,
cenová pole a `updated_dt`. Jediný nalezený databázový constraint je primární
klíč nad `cislo`. Nebyl nalezen FK na `stravnik`, unikátní omezení
`stravnik`, stavový CHECK ani business trigger; dva triggery bridge pouze
nastavují timestamp.

Z toho je doloženo:

- číslo čipu je globálně unikátní na úrovni tabulky;
- DB dovoluje více řádků čipů pro jednoho strávníka;
- DB sama nevynucuje povolenou množinu stavů ani právě jeden aktivní čip;
- DB sama nevynucuje existenci vlastníka.

Agregovaná LAB kontrola bez osobních dat našla stavy `B`, `P`, `V`, `Z`,
osiřelé řádky a 245 strávníků s více než jedním řádkem ve stavu `P`.
Nelze proto zavést invariant „právě jeden P“ bez dalšího business důkazu.
`public.histcipu` existuje jako historická tabulka, ale v dostupných zdrojích
nebyla nalezena její write cesta.

## Význam stavů

- `P` – **PROVEN: přidělen**. Referenční klient vybírá aktuální čip přes
  `c.stav = 'P'`, při přidělení vkládá nebo aktualizuje stav na `P`.
- `Z` – **PROVEN: ztracený** pouze jako klasifikace v referenčním klientu.
  Bezpečný write přechod do `Z` ani jeho audit doložen nebyl.
- `B` – **PROVEN: blokovaný pro read**; objednavkaNG jej odmítá textem
  „Čip je blokován“. Write přechod blokace/odblokování doložen není.
- `V` – **BLOCKED: význam nedoložen**.
- `NULL` / jiné hodnoty – schéma je dovoluje; význam nedoložen.

JLL zobrazuje `P` jako „Přidělen“, `Z` jako „Ztracen“, `B` jako „Blokován“
a ostatní hodnoty
výslovně jako nedoložené. Nezaměňuje hypotézu s business pravidlem.

## Operace a gate

- Identifikace: **PROVEN pro read**. Funkce `public.nacti_cip(varchar)` čip
  normalizuje na 16 znaků a vrací vlastníka, ale nefiltruje `stav`. JLL ji
  nepoužívá pro scoped GUI lookup, protože by mohla odhalit identitu mimo
  scope. Search přijímá pouze přidělený stav `P`.
- Přidělení: **PARTIAL**. Doložen je referenční `INSERT/UPDATE ... stav='P'`,
  ale ne pravidla pro více `P`, převod vlastníka, ceny, historii a audit.
- Vrácení: **BLOCKED**. Přechod a význam cílového stavu nejsou doloženy.
- Blokace/odblokování: **BLOCKED**.
- Ztráta: **BLOCKED**. Význam `Z` je doložen, write přechod nikoli.
- Převod/nahrazení: **BLOCKED**. Reference přepisuje vlastníka existujícího
  čipu, což maže část historie; není doloženo jako správný kontrakt.
- Historie: **BLOCKED**. Reference někde používá `DELETE FROM public.cipy`;
  JLL tento postup nepřebírá.
- Audit: **BLOCKED**. Nebyla doložena autoritativní událost ani povinná
  sekvence pro chip writes.
- Concurrency: **BLOCKED**. Není doložen společný lock protokol s legacy
  writery.

## Bezpečnostní rozhodnutí

JLL neimplementuje žádný chip DB write. GUI zobrazuje scoped read-only čipy a
tlačítka write operací jsou i při příslušném permission zakázána s vysvětlením.
Globální duplicita může být v budoucnu hlášena pouze genericky; identita
vlastníka mimo `allowed_categories` se nesmí vrátit.

K odemčení write gate je potřeba autoritativně potvrdit význam `B`/`V`,
přechodový diagram všech stavů, pravidlo více aktivních čipů, historizaci,
auditní funkci a společný concurrency protokol.

## FÁZE 3A – autoritativní matice

Terminologie:

- **PROVEN** znamená doložený význam nebo read chování; neznamená automaticky
  oprávnění k write.
- **INFERRED** je korelace dat bez autoritativního write zdroje.
- **UNKNOWN** nemá dostatečný důkaz.
- **BLOCKED** znamená, že JLL operaci nesmí zapisovat.

V dostupných `zdroje` nejsou Pascal/Delphi zdrojáky ani spustitelné/archive
artefakty s další write implementací. Prohledány byly Python varianty,
TypeScript `objednavkaNG`, DB funkce, triggery, rules a data LAB kopie.

### Stavy

- `P`: **PROVEN** přidělený/akceptovaný čip. Vzniká referenčním INSERT nebo
  UPDATE s vlastníkem a `vydano`. Reference také reaktivuje `Z` či jiný stav
  přepsáním na `P`, ale bezpečnost tohoto přechodu není doložena.
- `B`: **PROVEN pouze read význam** blokovaný. Zdroj vzniku a write přechod
  nebyly nalezeny. Historická data obsahují přechody `P→B`, `B→P` a `B→Z`;
  jde pouze o **INFERRED** lifecycle.
- `Z`: **PROVEN pouze read význam** ztracený. Zdroj write přechodu nebyl
  nalezen. Historická data obsahují `P→Z` a `Z→P`; write pravidlo zůstává
  **UNKNOWN**.
- `V`: business význam **UNKNOWN**. Aktuální řádky `V` mají vlastníka `0` a
  historie často obsahuje `P↔V`, což je slučitelné s hypotézou „volný“ nebo
  „vrácený“, ale není to autoritativní důkaz. `vraceno` je v dostupných
  datech vždy NULL.

`public.histcipu` má historické řádky a timestamp triggery. Nebyla nalezena
žádná DB funkce, rule, trigger ani klientský zdroj, který do ní zapisuje.
Proto se z pořadí historických stavů nesmí odvodit write algoritmus.

### Per-operation write gate

| Operace | Gate | Důvod |
| --- | --- | --- |
| assign | PARTIAL | INSERT/UPDATE na `P` je doložen, ale historie, audit a společný concurrency kontrakt chybí |
| return | BLOCKED | cílový stav, odvázání a `histcipu` nejsou doloženy |
| block | BLOCKED | význam `B` je doložen jen pro read, write přechod chybí |
| lost | BLOCKED | význam `Z` je doložen jen pro read, write přechod chybí |
| unblock | BLOCKED | `B/Z→P` nemá autoritativní pravidla ani audit |
| transfer | BLOCKED | helper přepisuje vlastníka v konfliktu s neznámou historií a auditem |

Stejná matice je strojově vyjádřena v `src/jll/write_gates.py`. Žádná
operace nemá `PROVEN`, takže backend ani GUI nemohou gate použít jako write
oprávnění.

### Concurrency

PK `cipy(cislo)` zabrání dvěma současným INSERT stejného přesného kódu, ale
neřeší:

- varianty stejného fyzického tagu;
- souběžný UPDATE/transfer existujícího řádku;
- více `P` čipů jednoho strávníka;
- lost update proti legacy writeru.

Pro absent row by JLL potřeboval deterministický advisory lock nad
normalizovaným kódem ještě před duplicate preflightem; pro existující řádek
`SELECT ... FOR UPDATE` a expected-owner/state revalidaci. Tento návrh ale
nesdílí legacy writer, proto sám neodemyká write gate.

### Audit

`updated_dt` a synchronize notify jsou technická metadata, nikoli business
audit. `public.udalosti` neobsahuje doložený čipový event kontrakt a
`histcipu` write cesta je neznámá. Vymyšlený `insert_udalost` event by nebyl
kompatibilní důkaz. Lokální souborový audit navíc není atomický s DB
transakcí. Požadavek `ActorContext + business write + audit v jedné
transakci` tedy nelze splnit bez nového autoritativního zdroje.

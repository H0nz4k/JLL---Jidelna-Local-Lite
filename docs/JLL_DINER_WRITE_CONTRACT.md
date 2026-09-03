# JLL strávník create/edit – forenzní kontrakt

DINER CREATE CONTRACT: **PARTIAL – write blocked**  
DINER EDIT CONTRACT: **BLOCKED**

## Ověřené schéma

`public.stravnik` má 55 sloupců. DB vynucuje pouze:

- primární klíč `evidcislo`;
- unikátní `varsymb`;
- `hromadny NOT NULL`.

`evidcislo` nemá default, sequence ani identity mechanismus. Insert/update
triggery nastavují synchronizační timestamp/notifikaci, ale nedoplňují
business defaults, nevynucují scope a nevytvářejí auditní událost.

## Create

Referenční `Stravnik_edit` používá
`SELECT COALESCE(MAX(evidcislo), 0) + 1` v jiné transakci než následný insert.
To je race-prone. Současní create writeři nemají doložený společný serverový
lock ani bezpečný allocator. JLL tento postup nepřebírá.

Reference vkládá omezenou množinu polí a hard-coded hodnoty, například
`zpusobplatby='4'`, `stav='A'`, `hromadny=false` a `deleted=false`.
Není doloženo, že jsou tyto defaulty správné pro všechny efektivně povolené
kategorie. Není doloženo ani povinné vytvoření `prihlas`, `stravobv`,
finančních či jiných návazných řádků.

V DB existuje širší cesta `__epks_insert`, která nulově inicializuje finance
a následně volá `doplnobvyklestravnika` a `nastavprihlasdleobvykle` pro
aktuální i další měsíc. Zdrojový create klient tuto cestu nepoužívá. Dva
pozorované create kontrakty proto nelze bez autoritativního rozhodnutí sloučit.

Chybí autoritativní důkaz pro:

- bezpečnou alokaci `evidcislo` při mixed-writer provozu;
- povinná pole a category-dependent defaulty;
- `varsymb` a finance defaults;
- platnosti a stavový lifecycle;
- návazné řádky;
- audit s konkrétním `ActorContext`;
- post-write invarianty.

## Edit

Ve zdrojích jsou doloženy dílčí přímé `UPDATE` operace a soft-delete reference,
nikoli úplný edit kontrakt. Není doloženo:

- která pole jsou bezpečně editovatelná;
- jak změna kategorie ovlivňuje existující přihlášky, ceny a scope;
- optimistic/pessimistic concurrency s legacy editorem;
- auditní funkce a povinná data události;
- atomická post-write revalidace všech návazností.

DB funkce `doplnobvyklestravnikakategor` ukazuje, že category change může
obnovovat `stravobv`, čistit `prihlas` a odmítnout změnu při placených
přihláškách. Volající produkční klient ani závazná interpretace návratových
stavů však ve zdrojích nejsou.

U editace musí být stará i nová kategorie v efektivním
`allowed_categories`; samotná GUI kontrola by nebyla autoritativní.

## Gate a návrh API

Dokud nejsou uvedené body doloženy, `DinerService.create` ani
`DinerService.update` nejsou implementovány. Zamýšlené API musí přijímat
omezený explicitní command, aktuální `SessionPolicy` a `ActorContext`; uvnitř
jedné transakce musí provést LAB guard, permission, scope, lock, write,
post-write revalidaci a audit.

GUI dál poskytuje bezpečnou read-only kartu. Tlačítka **Nový strávník** a
**Editovat strávníka** se zobrazují pouze s `diners.create` / `diners.edit`,
ale zůstávají disabled s vysvětlením write gate. Žádný formulář nepředstírá,
že lze nedoložený write uložit.

K odemčení create gate je potřeba autoritativní allocator a potvrzená sada
defaultů/návazností. K odemčení edit gate je potřeba explicitní whitelist
polí, category-change kontrakt, audit a společný concurrency protokol.

## FÁZE 3A – autoritativní matice

V dostupných zdrojích nejsou Pascal/Delphi ani jiné binární klientské
artefakty s chybějícím create/edit workflow. Aktuální DB funkce a triggery
mají podle zadání nejvyšší prioritu.

### Create

`evidcislo`:

- `stravnik.evidcislo` je PK bez sequence/default/identity;
- helper i DB `__epks_insert()` používají `MAX(evidcislo)+1`;
- `__epks_insert()` je hard-coded integrační skript pro konkrétní osobu,
  nikoli parametrizované veřejné create API;
- žádný allocator table, advisory lock ani autoritativní retry protokol
  nebyl nalezen.

Required rows/defaults jsou konfliktní:

- helper vytváří minimální `stravnik + cipy`, finance nechává NULL a
  nevytvoří `stravobv/prihlas`;
- `__epks_insert()` inicializuje více polí a volá
  `doplnobvyklestravnika`/`nastavprihlasdleobvykle` pro dva měsíce;
- není doloženo, která cesta je autoritativní pro běžného strávníka.

Create audit není doložen. Insert trigger nastaví timestamp a synchronization
notify, ale nevytvoří kompatibilní business událost s actor/before/after.

**Gate: PARTIAL.** Nelze implementovat JLL create write bez vymyšleného
allocatoru, defaultů, návazností a auditu.

### Edit personal data

Ve zdrojových klientech nebyl nalezen whitelist ani write workflow pro
`jmeno`, `trida` a další osobní atributy existujícího strávníka. Obecný
update trigger pouze notifikuje synchronizaci. Schéma samo není business
kontrakt.

**Gate: BLOCKED.**

### Category change

DB `doplnobvyklestravnikakategor(rok, mesic, evidcislo, kategorie)`:

- odstraní a doplní `stravobv` podle sazeb nové kategorie;
- odstraní nulové nepoužitelné `prihlas`;
- vrátí počet placených `prihlas` s jinou kategorií;
- sama neprovede autoritativní `UPDATE stravnik.kategorie`;
- sama nepřepíše všechny měsíční `prihlas.kategorie`;
- v DB ani klientech nemá nalezeného volajícího.

Není proto známo pořadí UPDATE/funkce, rozsah měsíců ani rollback při
nenulovém výsledku. **Gate: BLOCKED.**

### Concurrency a audit

`FOR UPDATE` může chránit JLL patch existujícího řádku, ale legacy full-row
UPDATE může po čekání přepsat novější hodnoty. Optimistic kontrola
`updated_dt` funguje jen pro writery, kteří ji respektují.

Create absent-row race nelze vyřešit row lockem. JLL-only advisory lock
nesdílí legacy `MAX+1` writer a table lock může způsobit, že legacy klient po
čekání vloží již obsazené číslo. Bez společného allocatoru není operace
bezpečná pro mixed-writer prostředí.

`public.udalosti` obsahuje historické události mazání strávníka, nikoli
doložený create/edit/category event kontrakt. Synchronization notify není
audit. Lokální identity audit není atomický s DB write.

Strojová matice je v `src/jll/write_gates.py`:

- `create = PARTIAL`;
- `edit_personal = BLOCKED`;
- `category_change = PARTIAL`.

`PARTIAL` zde popisuje existenci části kontraktu, nikoli povolení write.
Implementační gate všech tří operací zůstává zavřený, protože žádná není
`PROVEN`.

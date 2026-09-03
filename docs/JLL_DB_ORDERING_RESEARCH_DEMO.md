# JLL – forenzní analýza objednávek DEMO DB

Stav výzkumu: **PARTIAL** – FÁZE 0D primárně doložila aktuální TypeScript
source `objednavkaNG 1.8.0`. Současný HEAD už ručně orchestruje DEMO
`vyloucenos`, ale stále nemá audit, locking, post-write revalidaci ani
spolehlivé vyhodnocení DB návratů. Kontrakt je připraven k bezpečnému návrhu
JLL write vrstvy, nikoli k přímému převzetí implementace.

## 1. Rozsah, zdroje a integrita

Analýza byla provedena výhradně read-only. Nebyla připojena ani měněna live DB,
nebyly volány žádné write funkce a neproběhlo DML ani DDL.

Hlavní zdroj:

- `zdroje/demo.sql`, custom-format `pg_dump`
- velikost: `34 504 897` B
- SHA-256:
  `E97B7866B419AC01BEA20D01D4D8483CDCAFBC6624364942DA38E6AF00BAF235`
- rozbaleno pomocí `pg_restore (PostgreSQL) 15.3` do
  `%TEMP%\jll_restore.sql`
- rozbalené SQL: `1 907 581` řádků
- SHA-256 rozbaleného SQL:
  `BFBC3AA9D838CBCBBD11ABF8B30369E425B55AF58862B5D45B2B4698F9CC3E89`

Další zdroje:

- `JLL_PROJECT_START.md`
- `zdroje/RucniOdberStrav`
- `zdroje/DEMO_sestavy_strav`
- `zdroje/Stravnik_edit`

Odkazy `SQL Lx–Ly` níže míří na řádky uvedeného rozbaleného SQL.
Agregované počty byly získány streamovým read-only zpracováním `COPY` bloků.
Osobní a přihlašovací údaje z dumpu nejsou v tomto dokumentu reprodukovány.

## 2. Hlavní závěr

### OVĚŘENO PRO DEMO

**DEMO používá ceník: NE** ve smyslu konfiguračního přepínače
`public.pouzivatcenik()`.

Přesnější technická formulace:

1. Autoritativní sazba a počet povolených menu pocházejí při
   `PouzivatCenik=0` z `public.sazby`.
2. Funkce `public.getceniknamesic()` sazby rozmaterializuje po dnech a menu do
   `public.cenik`.
3. Samotný finanční přepočet objednávky nevolá `dej_sazbu`; používá
   `public.getcenamenuden()`, tedy čte materializovaný `public.cenik`.

Aktivní cenová cesta je proto:

```text
parametry.PouzivatCenik = 0
→ sazby (zdroj sazby + pocetmenu)
→ getceniknamesic(rok, měsíc) [přípravná/materializační operace]
→ cenik (denní materializace)
→ getcenamenuden(...)
→ getcenapocetmesicniprihlasky(...)
→ uloz_prihlasku_s_dotaci(...)
→ prihlas + penden + stravnik.platit{tm|pm}
```

Pro pouhé klientské zjištění sazby existuje samostatná větev:

```text
pouzivatcenik() = false
→ dej_sazbu(kategorie, typstravy, datum)
```

To však není cenová funkce volaná uvnitř analyzovaného write-path.

## 3. `PouzivatCenik` a `public.pouzivatcenik()`

### OVĚŘENO PRO DEMO

- `public.parametry` má klíč `(sekce, parametr)`; struktura je na
  `SQL L15927–L15931`, PK na `SQL L1894092–L1894094`.
- Dump obsahuje:
  `sekce='BACKUP', parametr='PouzivatCenik', hodnota='0'`
  (`SQL L531340–L531344`).
- Přesná signatura:
  `public.pouzivatcenik() RETURNS boolean`
  (`SQL L11910–L11922`).
- Funkce čte výhradně řádek ze sekce `BACKUP`.
- Pouze přesný text `'1'` vrací `true`.
- `'0'` vrací `false`.
- SQL `NULL` je explicitně převeden na `'0'`, tedy `false`.
- Chybějící parametr ponechá výsledek `SELECT INTO` jako `NULL`, který je také
  převeden na `'0'`, tedy `false`.
- Jiná hodnota než `'1'` rovněž vyhodnotí výraz `s='1'` jako `false`.

Bridge totéž publikuje jako `canteen.use_pricelist` porovnáním hodnoty s `'1'`
(`SQL L16007–L16009`).

`pouzivatcenik()` filtruje `sekce='BACKUP'`, zatímco bridge view a
`getceniknamesic()` čtou `PouzivatCenik` bez filtru sekce
(`SQL L9115–L9118`, `SQL L16007–L16009`). V tomto dumpu existuje jediný
odpovídající parametr, takže se větve shodují. U jiné DB by více sekcí mohlo
způsobit rozdílný nebo nejednoznačný výsledek.

## 4. `public.sazby` a `public.dej_sazbu`

### OVĚŘENO PRO DEMO

Struktura `public.sazby` je na `SQL L14307–L14337`. Pro objednávky jsou
nejdůležitější:

- `kategorie`
- `typstravy`
- `platnostod`, `platnostdo`
- `limit_`, `sazba`
- `dotace`, `fksp`
- `pocetmenu`
- `sazbadph`

Primární klíč je `(kategorie, typstravy, platnostod)`
(`SQL L1894293–L1894294`). Další relevantní index je pouze na `kategorie`
(`SQL L1898659–L1898662`).

Přesná signatura:

```text
public.dej_sazbu(
    pkategorie text,
    ptypstravy text,
    pdatum text
) RETURNS double precision
```

Definice je na `SQL L7276–L7289`.

Chování:

- datum očekává jako text `DDMMYYYY`;
- vybírá `sazby.sazba`;
- podmínka platnosti je včetně obou hranic:
  `platnostod <= datum AND platnostdo >= datum`;
- filtruje přesnou kategorii a přesný typ stravy;
- nerozlišuje číslo menu;
- při chybějícím řádku vrátí `NULL`;
- nemá fallback ani `ORDER BY`.

Statická agregace dat:

- 793 řádků;
- 781 řádků má `pocetmenu=1`;
- 12 historických řádků má `pocetmenu=2`, všechny jen pro období
  2023-11-01 až 2023-12-31;
- žádný řádek nemá nenulovou `dotace`;
- žádný řádek nemá `platnostdo IS NULL`;
- v dumpu není překryv platností pro stejnou dvojici
  `(kategorie, typstravy)`;
- k 2026-09-02 je aktivních 244 sazeb a všechny mají `pocetmenu=1`;
- žádná z aktivních sazeb nemá cenu 0.

Konkrétní sazby pro `Oběd-A`:

- `KAT1`, od 2026-09-01: 78,00; `pocetmenu=1`
  (`SQL L1732724`);
- `KAT2`, od 2026-09-01: 83,00; `pocetmenu=1`
  (`SQL L1732757`);
- `KAT3`, od 2026-09-01: 88,00; `pocetmenu=1`
  (`SQL L1732791`);
- `KAT4`, od 2026-08-01: 108,00; `pocetmenu=1`
  (`SQL L1732698`).

Bridge publikuje sazby jako `ejidelnicek_bridge.price`
(`SQL L16572–L16589`). Pozor: ve view je `date_to` naplněno opět
`sazby.platnostod`, nikoli `platnostdo` (`SQL L16584–L16585`). Není ověřeno,
jak tuto anomálii interpretuje externí klient.

## 5. Materializace `sazby → cenik`

### OVĚŘENO PRO DEMO

`public.getceniknamesic(prok integer, pmesic integer) RETURNS boolean`
je na `SQL L9081–L9160`.

Pseudosekvence:

```text
načti PouzivatCenik
pokud NULL nebo '0':
    DELETE cenik pro zadaný rok/měsíc

pro každou kategorii v sazby:
    vyber sazby překrývající daný měsíc
    spoj je s typstrav a ponech typsluzby='strava'
    načti kalendář vaření
    pro každý vařený den:
        pro menu 1..pocetmenu:
            pokud řádek cenik neexistuje:
                vlož sazbu a ostatní složky ze sazby
```

Tato funkce vysvětluje, proč je při `PouzivatCenik=0` současně naplněn
`public.cenik`: nejde o nezávislý ručně řízený zdroj ceny, ale o denní
materializaci sazeb používanou dalšími DB funkcemi.

Funkce není součástí jednotlivé objednávkové transakce. JLL ji nesmí před
objednávkou svévolně volat; je to write/maintenance operace.

### POTENCIÁLNÍ RIZIKO

Výběr sazeb testuje překryv měsíce přes 1. a 28. den a řadí jen podle typu a
`platnostod`. Pokud by dvě sazby stejného typu/kategorie platily v různých
částech jednoho měsíce, první průchod vytvoří denní řádky a další průchod u
existujícího řádku aktualizuje jen `sazbadph`, nikoli samotnou sazbu
(`SQL L9132–L9147`). Aktuální LAB data takový překryv nemají.

## 6. `public.cenik` a `public.getcenamenuden`

### OVĚŘENO PRO DEMO

Struktura `public.cenik` je na `SQL L16595–L16620`.

Primární klíč:

```text
(rok, mesic, den, kod_stravy, kategorie, menu, slozka)
```

Zdroj: `SQL L1893893–L1893894`.

Přesná signatura:

```text
public.getcenamenuden(
    ptypstravy text,
    pkategorie text,
    prok integer,
    pmesic integer,
    pden integer,
    pmenu integer,
    OUT cena double precision,
    OUT ok boolean
) RETURNS record
```

Definice: `SQL L8697–L8715`.

Výběr:

```text
typstrav.typstravy = ptypstravy
cenik.kod_stravy = typstrav.kod
cenik.kategorie = pkategorie
cenik.rok/mesic/den = prok/pmesic/pden
cenik.menu = pmenu
slozky_ceny.db_nazev = 'sazba'
```

DEMO má pro složku `sazba` nastaveno `s_dph=true`
(`SQL L1733456–L1733461`), proto funkce k nalezené ceně DPH nepřičítá.

Chybějící cena:

- `cena` zůstane `NULL`;
- `ok=false`;
- žádný fallback na `sazby` uvnitř této funkce neexistuje.

Cena 0:

- schéma ji nezakazuje;
- pokud by existoval řádek s `sazba=0`, funkce vrátí `cena=0, ok=true`;
- v aktuálním dumpu není žádný `cenik.sazba` nulový ani `NULL`.

Statická agregace `public.cenik`:

- 105 577 řádků;
- 98 905 řádků pro menu 1;
- 6 672 řádků pro menu 2;
- žádné menu 3–9;
- všechny řádky mají `slozka=0`;
- žádný duplicitní lookup klíč po ignorování `slozka`;
- všechny `dotace` jsou 0 nebo `NULL`;
- všechny `fksp` jsou 0 nebo `NULL`;
- menu 2 je pouze v historických měsících 2023-11 až 2024-08.

Příklad materializace pro 2026-09-01, `kod_stravy='A'`, menu 1:

- `KAT1`: 78,00 (`SQL L364879`);
- `KAT2`: 83,00 (`SQL L365929`);
- `KAT3`: 88,00 (`SQL L373069`);
- `KAT4`: 108,00 (`SQL L374855`).

Hodnoty odpovídají aktivním řádkům `sazby`.

`public.povolenemenu(...) RETURNS boolean` považuje menu za povolené právě
tehdy, když pro přesný den, typ, kategorii a menu najde `cenik.sazba`, která
není SQL `NULL`; číselná nula by byla povolena (`SQL L11927–L11939`). Není
doloženo, zda ji volá oficiální desktop klient.

Bridge `ejidelnicek_bridge.get_menu_price(menu_id, category_id)` rovněž volá
`public.getcenamenuden` (`SQL L2918–L2949`).

### POTENCIÁLNÍ RIZIKO

`getcenamenuden` nefiltruje `cenik.slozka`, přestože `slozka` je součástí PK.
V DEMO jsou nyní všechny hodnoty 0, takže je výsledek jednoznačný. Schéma ale
umožňuje více řádků pro tentýž lookup a funkce nemá `ORDER BY`.

## 7. Jídelníček a povolené menu

### OVĚŘENO PRO DEMO

Vazba názvu objednatelného menu:

```text
jidelnicek.idmenustravy
→ menustravy.id
→ menustravy.idtypstrj
→ typstrj.id
→ typstrj.oznaceni = znak objednávky 1..9
```

Zdroje:

- schéma `jidelnicek` a `menustravy`: `SQL L16225–L16259`;
- `typstrj` a bridge `menu_type`: `SQL L16371–L16400`;
- data `typstrj` definují Menu 1 až Menu 9:
  `SQL L1750304–L1750315`;
- stejnou vazbu používá legacy report:
  `zdroje/DEMO_sestavy_strav/DEMO/stravovaci_sestava.py L43–L63`.

`idtypstrj` není číslo menu. Číslo/znak ukládaný v `prihlas.dXX` je
`typstrj.oznaceni`.

`jidelnicek` rozlišuje:

- datum;
- jazyk;
- typ stravy;
- část menu (`idmenustravy`);
- `cislojidelnicku`;
- `zverejneny`.

Jeho PK je
`(datum, jazyk, typstravy, idmenustravy, cislojidelnicku)`
(`SQL L1893981–L1893982`).

Data:

- 54 495 řádků;
- všechna data jsou v jazyce `česky`;
- `cislojidelnicku=1`: 52 820 řádků;
- `cislojidelnicku=2`: 670 řádků;
- `cislojidelnicku=4`: 1 005 řádků;
- `zverejneny=true`: 47 295 řádků;
- `zverejneny=false`: 7 200 řádků;
- pro září 2026 je všech 1 474 řádků zveřejněných a mají
  `cislojidelnicku=1`.

Aktivní sazby k 2026-09-02 mají výhradně `pocetmenu=1`. Přesto jídelníček pro
září obsahuje i popisové řádky skupiny Menu 2. Samotná existence textu v
`jidelnicek` tedy není důkaz, že menu lze objednat. Rozhodující je současně
platná sazba/`pocetmenu` a denní cena v `cenik`.

legacy report správně filtruje jazyk, `cislojidelnicku` a objednatelná označení
1–9, ale jako provozní report nefiltruje `zverejneny`
(`stravovaci_sestava.py L50–L63`). Objednávkový preflight musí zveřejnění
řešit samostatně.

## 8. Termíny, `UZAVERKA` a typy stravy

### OVĚŘENO PRO DEMO

Bridge `canteen` publikuje globální termíny a stav uzávěrky
(`SQL L15958–L15985`):

- `prihlasovat_od=14:00:00`;
- `prihlasovat_do=07:00:00`;
- `dnu_na_prihlaseni=1`;
- `dnu_na_zmenu=1`;
- `dnu_na_odhlaseni=1`;
- `PreskakovatNevarneDny=1`.

Data: `SQL L531495–L531500` a `SQL L530920–L530926`.

`signaly` obsahuje `UZAVERKA='N'` (`SQL L1733417–L1733422`).
Bridge vyhodnocuje objednávání jako aktivní, pokud neexistuje
`UZAVERKA='A'` (`SQL L15983–L15985`). K okamžiku dumpu je tedy
`ordering_active=true`.

`ejidelnicek_bridge._canteen.prefer_global_order_limits=false`
(`SQL L169620–L169621`). Bridge současně publikuje termíny jednotlivých typů
z `typstrav` (`SQL L16074–L16084`).

Pro `Oběd-A` až `Oběd-D`, `ObědSZU-A` až `ObědSZU-D` a `Svačina`:

- `prihlasdo=09:00`;
- `menudo=09:00`;
- `odhlasdo=08:00`;
- `prihlasdnu=1`;
- `menudnu=1`;
- `odhlasdnu=0`.

Data: `SQL L1750285–L1750295`.

`Oběd-A` až `Oběd-D` mají vzájemné vyloučení přes `vyloucenos`:

- A vylučuje BCD;
- B vylučuje ACD;
- C vylučuje ABD;
- D vylučuje ABC.

Stejný vzor mají čtyři SZU typy (`SQL L1750285–L1750293`).

### NEOVĚŘENO / OTEVŘENÁ OTÁZKA

Sekundární klientský research na větvi `feature/dodatecna-prihlaska` uvádí,
že `prefer_global_order_limits` se týká výběru globálních proti typovým
termínům, nikoli výběru globálního proti kategoriálnímu debetu.
`objednavkaNG` tento bridge přepínač nečte.

Nadále není pro aktivní legacy kanál ověřeno:

- přesná hraniční podmínka času (`<` proti `<=`);
- význam dne 0/1 v kombinaci s `PreskakovatNevarneDny`;
- zda `pouzivatpcbox` omezuje JLL, pouze PCBox, nebo jiný kanál;
- zda jsou pro všechny kanály povinné stejné termíny.

Žádná z funkcí `objednavka_plus`, `objednavka_minus` ani
`uloz_prihlasku_s_dotaci` termín nebo `UZAVERKA` nekontroluje.

## 9. `public.prihlas` – kontrakt

### OVĚŘENO PRO DEMO

Schéma je na `SQL L14165–L14212`.

Přirozený a vynucený PK:

```text
(stravnik, typsluzby, rok, mesic, poradiprihl)
```

Zdroj: `SQL L1894181–L1894182`.

`id` má sequence default (`SQL L27004`), ale není součástí PK a schéma nad ním
nevynucuje `UNIQUE`. V aktuálních 258 486 řádcích je `id` fakticky unikátní.

Důležitá oprava zadání: `platittm`, `platitpm`, `platbatm` a `platbabm`
nejsou sloupce `public.prihlas`; jsou v `public.stravnik`
(`SQL L16490–L16505`).

`prihlas` ukládá:

- 31 denních znaků `d01..d31`;
- měsíční `cena`, `pocet`, `uctovano`, `placeno`;
- snapshot kategorie a třídy;
- `pocet_dotaci`;
- `poradiprihl`;
- technická `id`, `seq`, `updated_dt`.

Stavy:

- `'1'..'9'`: objednané menu. `public.jeprihlaska()` vrací 1 pouze pro tyto
  znaky (`SQL L10351–L10366`);
- `'N'`: neobjednáno; `objednavka_minus` zapisuje právě `'N'`
  (`SQL L11363–L11368`);
- `'S'`: rovněž neobjednáno, ale používá se jako výchozí/rozpisový stav a při
  vzájemném vyloučení typů; hromadné rozpisové operace převádějí `S→menu` a
  `menu→S` (`SQL L12276–L12325`);
- `'*'`: den mimo použitelný kalendář/nevařený den při generování rozpisu
  (`SQL L11163–L11189`);
- `'B'`: funkce `jeprihlaska` jej nepovažuje za objednávku; přesný business
  význam nebyl pro JLL ověřen.

Read-only agregace `d01..d31`:

- `S`: 3 732 538;
- `*`: 3 196 375;
- `N`: 725 983;
- `1`: 295 273;
- `B`: 61 187;
- `2`: 1 710;
- jiné číslice se v aktuálním stavu tabulky nevyskytují.

Všech 258 486 řádků dumpu má `poradiprihl=1`. DEMO tedy v aktuálním snapshotu
více pořadí v `public.prihlas` fakticky nepoužívá, ačkoli schéma i funkce je
podporují.

Deterministický lookup řádku musí používat celý PK. `id` se má číst až z takto
jednoznačně určeného řádku. `LIMIT 1` bez business klíče není přijatelné.

## 10. `public.objednavka_plus`

### OVĚŘENO PRO DEMO

Signatura:

```text
public.objednavka_plus(
    prok integer,
    pmesic integer,
    den integer,
    menu character,
    pstravnik integer,
    ptypstravy text
) RETURNS integer
```

Definice: `SQL L11383–L11425`.

Pseudosekvence pro běžného strávníka:

```text
načti stravnik.hromadny
pokud true:
    deleguj objednavka_hromadneho_stravnika(..., plus=true)

projdi všechny prihlas řádky stejného strávníka/roku/měsíce/typu:
    vyber první poradiprihl, kde cílový den je S nebo N

pokud žádný není:
    pporadiprihl = dejporadiprihlasky(...)
    nastavprihlasdleobvykle(..., prihlasit=false, pporadiprihl)
    znovu načti měsíční řetězec

přepiš cílový den předaným znakem menu
uloz_prihlasku_s_dotaci(...)
RETURN 1
```

Funkce sama nekontroluje:

- `UZAVERKA`;
- datum ani termín;
- aktivitu/deleted strávníka;
- oprávněnou kategorii JLL;
- `pouzivatpcbox`;
- existenci/zveřejnění jídelníčku;
- rozsah nebo povolení menu;
- existenci ceny;
- kredit;
- `limitprihlasky`;
- výsledek `uloz_prihlasku_s_dotaci` (uloží jej do `ok`, ale nevyhodnotí).

`RETURN 1` není důkaz změny. Funkce jej vrací i tehdy, když nenajde vhodný
řádek nebo navazující update nic nezmění.

### Kritická vlastnost pro změnu menu

Pokud je cílový den již číslice 1–9, `objednavka_plus` tento řádek nevybere.
Není tedy sama o sobě funkcí pro přímou změnu `1→2` ve stejném
`poradiprihl`. Může se pokusit vytvořit další pořadí.

`dejporadiprihlasky()` vrací `max(poradiprihl)+1`; pokud žádný řádek neexistuje,
nastaví nejprve 1 a pak vrátí 2 (`SQL L7782–L7795`). To neodpovídá aktuálním
LAB datům, kde je všude pořadí 1, a vyžaduje ověření na skutečném klientském
workflow.

`nastavprihlasdleobvykle` vytvoří řádek jen při dostupném rozpisu
`stravobv`; jinak není doložen vznik řádku (`SQL L11120–L11194`).

## 11. Odhlášení – `public.objednavka_minus`

### OVĚŘENO PRO DEMO

Signatura:

```text
public.objednavka_minus(
    prok integer,
    pmesic integer,
    den integer,
    menu character,
    pstravnik integer,
    ptypstravy text
) RETURNS integer
```

Definice: `SQL L11343–L11377`.

Pro běžného strávníka projde řádky stejného měsíce a typu, najde první řádek,
jehož cílový den přesně odpovídá předanému `menu`, nahradí jej `'N'` a zavolá
`uloz_prihlasku_s_dotaci`.

Vrací 1 i tehdy, když žádný odpovídající řádek nenajde. Nekontroluje termín,
uzávěrku, cenu, kredit ani oprávnění.

## 12. Wrappery a audit

### OVĚŘENO PRO DEMO

Existují:

- `objednavkaplus(...)` (`SQL L11471–L11484`);
- `objednavkaplusudalost(...)` (`SQL L11490–L11503`);
- `objednavkaminus(...)` (`SQL L11433–L11446`);
- `objednavkaminusudalost(...)` (`SQL L11452–L11465`).

Všechny nejprve volají core plus/minus a potom `public.insert_udalost`.

Wrappery zapisují:

```text
plus:  poznamka = 'S->' || menu
minus: poznamka = menu || '->S'
typ = 'P'
cena = 0
```

Varianty `...udalost` přijímají `cisloverze`, `uzivatel` a `pracoviste`;
`pracoviste` ukládají do sloupce `udalost`.

Audit wrapperů není přesným popisem core změny:

- plus umí měnit `N→menu`, ale audit vždy tvrdí `S→menu`;
- minus zapisuje do `prihlas` znak `N`, ale audit vždy tvrdí `menu→S`;
- event se vytvoří i při no-op, protože návrat core funkce se neověřuje;
- wrapper předává cenu 0.

Proto žádný z těchto wrapperů nelze bez dalšího prohlásit za bezpečný auditní
entry point JLL.

## 13. Skutečné eventy v `public.udalosti`

### OVĚŘENO PRO DEMO

Schéma `public.udalosti`: `SQL L24893–L24906`.

`public.insert_udalost(...) RETURNS boolean` vkládá datum a čas serveru a
předaná metadata (`SQL L10144–L10185`).

V dumpu je 11 290 eventů s `udalost='Přihláška'` a `typ='P'`.

Pro nehromadné strávníky:

- `?->1`: 9 921;
- `?->N`: 1 232;
- `N->1`: 67;
- `S->1`: 46;
- `1->S`: 5;
- `1->N`: 1;
- `1->1`: 2.

Příklady:

- e-jídelníček `?->1` a `?->N`: `SQL L1865855–L1865878`;
- desktop `N->1`: `SQL L1865912`;
- desktop `S->1`: `SQL L1868079`;
- desktop `1->S`: `SQL L1874301` a `SQL L1875062–L1875064`;
- desktop `1->N`: `SQL L1883571`.

Eventy desktopu mají často skutečnou cenu a `udalost='Přihláška'`; nejsou tedy
výstupem výše popsaných wrapperů, které předávají cenu 0 a jiná metadata.
Eventy e-jídelníčku (`uzivatel='e-jidelnicek.cz'`, `?->...`) rovněž neodpovídají
uloženým wrapperům.

Číselné přechody jako `1->2`, `2->4` nebo `0->3` v aktuálních eventech
pocházejí z hromadných účtů a znamenají změnu počtu porcí, nikoli prokázanou
změnu Menu 1 na Menu 2. Příklad `1->2` na `SQL L1879482`.

### NEOVĚŘENO / OTEVŘENÁ OTÁZKA

- Která klientská metoda skládá produkční event `Přihláška/P`.
- Zda má změna typu stravy generovat jeden event, nebo event pro odhlášený i
  nově přihlášený typ.
- Zda má cílový stav odhlášení být v auditu `S`, nebo `N`.
- Co přesně znamená `?` a zda je záměrně kanálově specifické.
- Jak má JLL vyplnit `uzivatel`, `cisloverze`, `cena` a `typstravy`.

## 14. Finanční write-path

### OVĚŘENO PRO DEMO

`public.uloz_prihlasku_s_dotaci(...) RETURNS boolean`
je definována na `SQL L12943–L13001`.

Pseudosekvence:

```text
pporadiprihl = ppocet_na_mesic
pokud 0, použij 1

načti původní prihlas.cena, kategorii a třídu
spočti novou měsíční cenu a počet:
    getcenapocetmesicniprihlasky(...)

rozdil = nova_cena - puvodni_cena

UPDATE prihlas:
    d01..d31
    cena = nova_cena
    pocet = nový počet

pokud abs(rozdil) < 0.01:
    RETURN true

zapisprihlasku(..., pcastka=-rozdil, typ='R',
               poznamka='změna rozpisu')

dotacestr = get_str_dotace(...)
uloz_dotaci(...)
RETURN výsledek uloz_dotaci
```

`getcenapocetmesicniprihlasky`:

- pro každou číslici 1–9 zvýší `pocet`;
- zavolá `getcenamenuden`;
- cenu přičte pouze při `ok=true`;
- chybějící cenu tedy tiše ocení jako 0, ale objednávku započítá.

Zdroj: `SQL L8976–L9028`.

To je kritický důvod, proč musí klient před write ověřit `ok=true` pro přesné
menu. Samotná DB write funkce chybějící cenu nezamítne.

`zapisprihlasku` (`SQL L13747–L13772`):

1. vloží pohyb do `public.penden` přes `insert_penden`
   (`SQL L9856–L9904`);
2. načte účetní `TentoMesic`;
3. pro `strava` / `stravovací služba`:
   - pokud `pmesic = TentoMesic`, provede
     `stravnik.platittm = platittm - pcastka`;
   - jinak provede
     `stravnik.platitpm = platitpm - pcastka`.

Protože `pcastka=-rozdil`, výsledkem je:

- nové jídlo za `P`: `penden.castka=-P`, `platit{tm|pm}` se zvýší o `P`;
- odhlášení jídla za `P`: `penden.castka=+P`,
  `platit{tm|pm}` se sníží o `P`;
- dražší změna o `Δ`: předpis se zvýší o `Δ`;
- levnější změna o `Δ`: předpis se sníží o `Δ`;
- stejná cena / rozdíl pod 0,01: žádný `penden` ani změna `stravnik`;
- cena 0: stav se může změnit bez finančního pohybu.

Objednávková cesta nemění:

- `stravnik.preplatekmm`;
- `stravnik.platbatm`;
- `stravnik.platbabm`.

`platbatm`/`platbabm` mění platební funkce `zapisplatbu`, nikoli
`zapisprihlasku` (`SQL L13688–L13712`).

V dumpu je účetní `TentoMesic=8`, `TentoRok=2026`
(`SQL L531071–L531075`). Objednávka pro září 2026 proto v tomto snapshotu
směřuje do `platitpm`, nikoli `platittm`.

### Kritické omezení návratových hodnot

- `uloz_prihlasku_s_dotaci` nekontroluje počet aktualizovaných řádků;
- při nulovém rozdílu vrátí `true` i po update 0 řádků;
- plus/minus ignorují boolean výsledek;
- plus/minus mohou vrátit 1 bez změny.

Budoucí write transakce proto musí po volání znovu načíst přesný řádek podle
celého PK a ověřit očekávaný stav ještě před `COMMIT`.

## 15. Vzájemné vyloučení typů

### OVĚŘENO PRO DEMO

`public.aplikujspolusvyloucenos(...) RETURNS boolean`
je na `SQL L6861–L6948`.

Při novém přihlášení typu:

- vyhledá jiné objednané typy uvedené v `vyloucenos`;
- změní jejich den na `S`;
- každou změnu uloží přes `uloz_prihlasku_s_dotaci`, tedy včetně finančního
  rozdílu;
- obdobně umí přihlásit povinné typy `spolecnes`.

Při odhlášení umí zrušit související/povinné typy.

DEMO používá `vyloucenos` pro varianty Oběd A–D a SZU A–D; `spolecnes` je u
těchto typů prázdné (`SQL L1750285–L1750293`).

### Kritická otevřená otázka

`objednavka_plus`, `objednavka_minus` ani `uloz_prihlasku_s_dotaci` tuto funkci
nevolají. V dumpu není jiný DB caller. Musí ji tedy případně volat klientská
orchestrace. Bez zdroje produkčního objednávkového klienta nelze bezpečně
určit pořadí volání ani atomickou sekvenci změny Oběd-A → Oběd-B.

## 16. Kredit, `limitprihlasky` a `povoleny_debet`

### KREDIT – ČÁSTEČNĚ OVĚŘENO PRO DEMO

Handoff uvádí kandidátní vzorec z jiného klienta:

```text
preplatekmm - platittm - platitpm + platbatm + platbabm
```

Zdroj: `JLL_PROJECT_START.md L206–L258`. Zdrojový kód `objednavkaNG` ale není
součástí analyzovaných projektových zdrojů, takže nelze potvrdit, že jej
produkční legacy klient skutečně používá.

V Git historii `zdroje/RucniOdberStrav` je na větvi
`feature/dodatecna-prihlaska`, commit
`75d7890aa0243f03707309459d2365a0355be480`, dostupný read-only dokument
`docs/dodatecna_prihlaska.md`. Popisuje reverse-engineering sestaveného
`objednavkaNG` a alternativního e-jídelníčku. Jde o důležitý sekundární důkaz
chování klientů, nikoli o důkaz, který z nich DEMO používá pro konkrétní
operaci.

Podle tohoto research používá `objednavkaNG`
`CreatePrihlaskaService.prihlasJidlo` následující pořadí:

```text
1. UZAVERKA != 'A'
2. strávník existuje a má kategorii
3. typstrav.typsluzby='strava' a pouzivatpcbox=true
4. canRegisterForDate podle typu operace
5. zveřejněný jídelníček, cislojidelnicku=1
6. dostupná číselná cena
7. finanční kontrola pouze pro menu_add
8. createRegistration → objednavka_plus(...)
```

Kandidátní finanční pravidlo `objednavkaNG`:

```text
currentCredit =
    preplatekmm
  - platittm
  - platitpm
  + platbatm
  + platbabm

limitPrihlasky = kategor.limitprihlasky
NULL / prázdné / neplatné hodnoty → 0

povolit právě tehdy, když:
currentCredit - price >= limitPrihlasky
```

Hraniční rovnost je povolena. `objednavkaNG` podle research nečte
`parametry.povoleny_debet` ani `preplatek_sluzby`. Při
`pouzivatcenik()=false` získává preflightovou cenu přímo přes `dej_sazbu`;
DB finanční write-path potom cenu znovu počítá z materializovaného `cenik`.
JLL proto musí před návrhem ověřit, že tyto dvě cenové cesty v DEMO nemohou
divergovat kvůli neaktuální materializaci.

DEMO DB poskytuje v `ejidelnicek_bridge.visitor.account` jiný, podrobnější
vzorec (`SQL L16846–L16878`):

```text
COALESCE(preplatekmm, 0)
+ COALESCE(preplatek_sluzby, 0)
- platittm
- platitpm
+ součet relevantních penden plateb/pohybů od účetního měsíce dále
```

Do subquery vstupují:

- `penden.typ='P'`;
- předpisy typů `služba`;
- předpisy `doplňkový prodej`.

Bridge tedy nepoužívá přímo jednoduchý součet uložených
`platbatm+platbabm` a zahrnuje `preplatek_sluzby`.

Podle stejného klientského research e-jídelníček vybírá limit jako
`category.debit_allowed`, při jeho absenci `canteen.debit_allowed`, jinak 0,
a zamítá při `account - price + debit_allowed < 0`. Kladných 200 zde tedy
znamená jinou znaménkovou logiku než kladných 200 v pravidle
`objednavkaNG`.

`public.get_preplatky_stravnika` navíc vrací tři jiné pohledy na přeplatek a
zohledňuje cenu budoucích přihlášek (`SQL L8455–L8484`).

Závěr: oba klientské algoritmy jsou sekundárně zdokumentovány, ale přesný
preflightový kredit aktivního legacy objednávkového kanálu je **NEOVĚŘEN**.

### `kategor.limitprihlasky`

Schéma: `SQL L14122–L14155`.

Agregace 53 kategorií:

- 40 kategorií: `limitprihlasky=200`;
- 12 kategorií: `NULL`;
- 1 kategorie (`SZU`): `0`.

Příklady:

- `KAT1`, Žáci 7–10 let: 200;
- `KAT2`, Žáci 11–14 let: 200;
- `KAT3`, Žáci 15+ let: 200;
- `KAT4`, Zaměstnanci: 200;
- `KAT6`, `KAT7`, `KAT8`, `KAT9`: 200;
- `SZU`: 0.

Ukázková data začínají na `SQL L456798–L456806`.

Bridge publikuje tuto hodnotu jako `category.debit_allowed`
(`SQL L16038–L16047`).

Podmínka zamítnutí
`currentCredit - price < limitPrihlasky` je sekundárním research potvrzena pro
inspektovaný `objednavkaNG`. Nelze ji však bez určení aktivního kanálu
prohlásit za pravidlo produkčního DEMO workflow; e-jídelníček používá výše
uvedenou opačnou interpretaci `debit_allowed`.

### `povoleny_debet`

- `parametry.povoleny_debet=200` (`SQL L530934`);
- bridge jej publikuje jako `canteen.debit_allowed`
  (`SQL L15992–L15995`).

Pro inspektovaný `objednavkaNG` je sekundárně doloženo pouze kategoriální
`limitprihlasky`. Pro e-jídelníček je doložen kategoriální údaj s fallbackem
na globální `povoleny_debet`. Není ověřeno, který algoritmus je autoritativní
pro zamýšlený legacy/JLL kanál.

## 17. Dotace

### OVĚŘENO PRO AKTUÁLNÍ DEMO SNAPSHOT

Call-chain po nenulové finanční změně:

```text
uloz_prihlasku_s_dotaci
→ get_str_dotace
→ getceny_dotaci_mesic
→ getcenadotaceden
→ uloz_dotaci
→ případně prihlas řádku typu 'stravovací služba'
→ případně zapisprihlasku
```

Zdroje:

- `get_str_dotace`: `SQL L8490–L8529`;
- `getcenadotaceden`: `SQL L8535–L8553`;
- `getceny_dotaci_mesic`: `SQL L9263–L9284`;
- `uloz_dotaci`: `SQL L12754–L12810`.

Aktuální DEMO konfigurace:

- všech 793 `sazby.dotace` je 0/NULL;
- všech 105 577 `cenik.dotace` je 0/NULL;
- v `typstrav` je 12 typů `typsluzby='strava'` a jeden
  `doplňkový prodej`, ale žádný typ `stravovací služba`;
- `slozky_ceny` neobsahuje `db_nazev='dotace'`, přestože
  `getcenadotaceden` takový řádek vyžaduje
  (`SQL L1733456–L1733461`, `SQL L8542–L8548`).

Statickým důsledkem je, že v tomto snapshotu není aktivní samostatný dotační
předpis. `uloz_dotaci` nenajde typ `stravovací služba` a finanční dotační
update nemá cílový řádek.

JLL přesto nesmí dotační algoritmus reimplementovat. Pokud bude v jiné DB
aktivní, musí zůstat uvnitř existující DB business logiky.

### POTENCIÁLNÍ RIZIKO

`uloz_prihlasku_s_dotaci` při `abs(rozdil)<0.01` vrací ještě před
`get_str_dotace/uloz_dotaci`. U klienta s nenulovou a menu-specifickou dotací
by změna menu za stejnou cenu nemusela dotační přepočet spustit. Pro DEMO s
nulovými dotacemi to v aktuálním snapshotu nemá finanční dopad.

## 18. Hromadní strávníci

### OVĚŘENO PRO DEMO

- `stravnik.hromadny=true`: 21 z 2 717 strávníků;
- všech 21 má data v `public.prihlasn`;
- `public.prihlasn`: 1 816 řádků;
- variantu 1 má 1 764 řádků, variantu 2 má 52 řádků.

Schéma `prihlasn`: `SQL L14222–L14299`; PK je
`(stravnik, typsluzby, varianta, rok, mesic)`
(`SQL L1894189–L1894190`).

`objednavka_plus/minus` delegují při `hromadny=true` na
`objednavka_hromadneho_stravnika`
(`SQL L11296–L11336`).

Ta:

- najde přesný `prihlasn` podle typu a `varianta=menu`;
- zvýší/sníží počet porcí dne, celkové `pocet` a `cena`;
- zapíše finanční rozdíl přes `zapisprihlasku`;
- při nenalezeném řádku vrátí 0.

Minus větev explicitně nebrání snížení pod nulu; klient musí množství předem
ověřit. Hromadní strávníci jsou mimo první pilot JLL.

## 19. Bridge write cesta

### OVĚŘENO PRO DEMO

`ejidelnicek_bridge.order_data` mapuje jeden `prihlas` řádek na měsíční
`data_ordered` a zachovává `order_index=poradiprihl`
(`SQL L16438–L16455`).

`INSERT` i `UPDATE` view mají INSTEAD OF trigger `save_order`
(`SQL L1899582–L1899592`).

`save_order()` předává celý nový 31znakový řetězec přímo do:

```text
public.uloz_prihlasku_s_dotaci(
    typstravy,
    rok,
    mesic,
    visitor_id,
    data_ordered,
    0
)
```

Zdroj: `SQL L3201–L3227`.

To je prokázaná write cesta e-jídelníčkového bridge, nikoli důkaz, že je to
správný veřejný entry point pro budoucí JLL. Trigger nekontroluje termíny,
kredit, menu ani audit a ignoruje boolean výsledek.

`save_order_count` naopak používá `objednavkaminus/objednavkaplus` pro změnu
množství (`SQL L3233–L3318`).

## 20. Co musí JLL ověřit před write

### OVĚŘENO JAKO NUTNÉ Z DB KONTRAKTU

Bez těchto kontrol může analyzovaná DB funkce provést chybnou nebo neauditovanou
změnu:

1. PostgreSQL serverový datum a čas.
2. Category scope: cílový strávník musí stále patřit do
   `allowed_categories`; tato bezpečnostní hranice je závazná podle
   `JLL_PROJECT_START.md L66–L109`.
3. Strávník existuje, stále patří do scope a není hromadný pro první pilot.
   Přesné objednávkové podmínky pro `stav`, `deleted` a interval platnosti musí
   potvrdit produkční klient; pickup klient používá
   `stav='A' AND COALESCE(deleted,false)=false`
   (`zdroje/RucniOdberStrav/README.md L237–L246`).
4. Jednoznačný `prihlas` řádek podle celého PK, v DEMO očekávaně
   `poradiprihl=1`.
5. Aktuální znak cílového dne a očekávaný přechod.
6. `UZAVERKA` a příslušný termín operace.
7. Typ stravy, kalendář vaření a kanálové povolení.
8. Zveřejněný jídelníček se správným jazykem a `cislojidelnicku`.
9. Menu je objednatelné pro přesný typ/kategorii/den:
   aktivní sazba, `menu <= pocetmenu` a `getcenamenuden(...).ok=true`.
10. Kredit a správně interpretovaný limit.
11. Vzájemná vyloučení `vyloucenos`.
12. Bezprostředně před změnou revalidovat stejné údaje v jedné transakci.
13. Po DB volání ověřit očekávaný stav, cenu a cílový řádek před `COMMIT`.
14. Event/audit provést atomicky ve stejné transakci.

### CO MÁ ZŮSTAT V DB BUSINESS LOGICE

- přepočet celé měsíční ceny z jednotlivých dnů;
- výpočet a zápis finančního rozdílu;
- vložení `penden`;
- aktualizace `stravnik.platittm/platitpm`;
- případný dotační přepočet;
- změny hromadného účtu, pokud budou někdy podporovány.

JLL nesmí přímo aktualizovat `prihlas`, `penden` ani finanční sloupce
`stravnik`.

## 21. NEOVĚŘENO / OTEVŘENÉ OTÁZKY – blokery write vrstvy

1. **Zdroj skutečného klienta.** V projektových zdrojích není
   `objednavkaNG` ani třídy `CreatePrihlaskaService`, `prihlasJidlo`,
   `canRegisterForDate`, `createRegistration`. Historická větev
   `RucniOdberStrav` obsahuje podrobný sekundární reverse-engineering, ale
   nikoli primární klientský artefakt ani důkaz, který kanál je pro
   zamýšlený legacy/JLL workflow autoritativní.
2. **Přesný termínový algoritmus.** Hodnoty jsou známé, ale chybí kanonická
   implementace hranic času, dnů a přeskakování nevařených dnů.
3. **Kredit a limit.** Není potvrzeno, který ze dvou rozdílných klientských
   algoritmů produkční legacy objednávka používá.
4. **Oficiální transakční orchestrace.** Není známo, zda desktop volá
   `objednavka_plus/minus`, přímé `uloz_prihlasku_s_dotaci`,
   `aplikujspolusvyloucenos`, nebo jejich kombinaci.
5. **Změna menu.** Aktivní DEMO sazby povolují pouze menu 1. Volba Oběd A–D
   je modelována samostatnými vzájemně vyloučenými typy stravy. Chybí
   kanonická sekvence změny A→B a její atomický audit.
6. **Odhlášení `N` proti `S`.** Core minus zapisuje `N`, wrapper tvrdí `S` a
   produkční eventy obsahují obě varianty.
7. **Audit.** Produkční eventy nejsou generovány analyzovanými wrappery;
   přesná klientská implementace není dostupná.
8. **`cislojidelnicku`.** Pro aktuální září je 1, ale obecné pravidlo výběru
   pro kategorie s `kategor.jidelnicek IS NULL` není doloženo.
9. **Live shoda.** Nebyla dostupná/použita live legacy DB; závěry platí pro
   konkrétní hash dumpu.
10. **Souběh.** Read-only fáze nemohla ověřit zamykání a chování při dvou
    současných změnách stejného měsíčního řádku.

## 22. Mapa operací

### PŘIHLÁSIT

```text
[NEOVĚŘENO] přesná klientská preflight sekvence
→ [OVĚŘENO] zkontrolovat UZAVERKA a typový/globální termín
→ [OVĚŘENO] ověřit allowed_categories a nehromadný účet
→ [OVĚŘENO] ověřit zveřejněný jídelníček a cislojidelnicku
→ [OVĚŘENO] ověřit menu proti pocetmenu a getcenamenuden.ok=true
→ [NEOVĚŘENO] spočítat kanonický DEMO kredit a limit
→ [NEOVĚŘENO] zvolit oficiální entry point
→ [OVĚŘENO] DB přepočítá měsíční cenu a finanční rozdíl
→ [OVĚŘENO] DB zapíše penden a platit{tm|pm}
→ [OVĚŘENO] DB obsahuje dotační call-chain; v DEMO je nyní neaktivní
→ [NEOVĚŘENO] kompatibilní produkční event
→ [OVĚŘENO] výsledný stav musí být číslice 1–9 a musí být revalidován
```

### ZMĚNIT MENU / VARIANTU STRAVY

```text
[NEOVĚŘENO] zda JLL mění číslo menu v jednom typu, nebo exkluzivní typ A–D
→ [OVĚŘENO] zkontrolovat menudnu/menudo a uzávěrku
→ [OVĚŘENO] ověřit nové menu/typ, zveřejnění a přesnou cenu
→ [NEOVĚŘENO] kanonický kreditní test pro dražší variantu
→ [OVĚŘENO] uloz_prihlasku_s_dotaci umí čistý rozdíl nové a staré ceny
→ [OVĚŘENO] aplikujspolusvyloucenos umí finančně zrušit vyloučený typ
→ [NEOVĚŘENO] správné pořadí a atomická kombinace těchto funkcí
→ [OVĚŘENO] dražší změna zvýší předpis, levnější jej sníží
→ [OVĚŘENO] stejná cena nevytvoří finanční pohyb
→ [NEOVĚŘENO] produkční event pro změnu
→ [OVĚŘENO] po změně revalidovat všechny dotčené typy/řádky
```

### ODHLÁSIT

```text
[NEOVĚŘENO] přesná klientská preflight sekvence
→ [OVĚŘENO] zkontrolovat odhlasdnu/odhlasdo a uzávěrku
→ [NEOVĚŘENO] zvolit oficiální entry point a výsledný N/S kontrakt
→ [OVĚŘENO] objednavka_minus mění odpovídající menu na N
→ [OVĚŘENO] DB sníží měsíční cenu
→ [OVĚŘENO] penden dostane kladné vrácení a platit{tm|pm} se sníží
→ [OVĚŘENO] dotační call-chain je v DEMO nyní fakticky bez pohybu
→ [NEOVĚŘENO] event 1->S proti 1->N
→ [OVĚŘENO] výsledný stav a finance musí být před COMMIT revalidovány
```

## 23. POTENCIÁLNÍ PERFORMANCE A CONCURRENCY RIZIKA

1. `prihlas` má vhodný PK a index `prihlasinx`
   `(stravnik, rok, mesic, typsluzby)` (`SQL L1898924–L1898927`).
   Samostatný index je částečně redundantní s PK v jiném pořadí.
2. `objednavka_plus/minus` skládají celý 31denní řetězec a
   `uloz_prihlasku_s_dotaci` zapisuje všech 31 sloupců. Souběžné změny různých
   dnů téhož měsíce mohou bez explicitního zamčení vytvořit lost update.
3. `dejporadiprihlasky=max+1` není zamčené a je závod při souběžném založení.
4. `getcenamenuden` je díky prefixu PK efektivní, ale nefiltruje `slozka`.
5. `dej_sazbu` využije PK pro kategorii, typ a `platnostod`; `platnostdo` je
   zbytkový filtr. Bez zákazu překryvů nemá jednoznačnost vynucenou schématem.
6. `prihlas.id` nemá index ani `UNIQUE`, přestože jej používají některé
   lookupy a navazující funkce. V aktuálním dumpu je fakticky unikátní.
7. `ejidelnicek_bridge.visitor.account` obsahuje korelovanou agregaci nad
   `penden`. `penden` má 629 924 řádků, ale index
   `(datum, evidcislo, cas)` začíná datem, zatímco korelace začíná
   `evidcislo` a vytváří datum textovou konkatenací
   (`SQL L16858–L16877`, index `SQL L1898812–L1898815`).
8. `udalosti` má pouze index na `updated_dt` (`SQL L1899382`), ne na
   `(stravnik, datumobj)`.
9. Bridge používá `ctid_to_bigint` jako `category_id`/`price_id`.
   `ctid` není stabilní business identifikátor a může se změnit fyzickou
   reorganizací tabulky.
10. `menu_aggregated` nefiltruje jazyk, `cislojidelnicku` ani `zverejneny`
   (`SQL L16265–L16280`), což je kromě výkonu i riziko správnosti.
11. Vzdálený JLL musí slučovat preflight do malého počtu parametrizovaných
    dotazů, ale nesmí kvůli tomu vynechat revalidaci před write.

## 24. Rozhodnutí pro další fázi

- Cenový zdroj a denní materializace: **pochopeno**.
- Finanční delta uvnitř `uloz_prihlasku_s_dotaci`: **pochopena**.
- Aktivní dotační stav DEMO: **pochopen jako nulový/neaktivní**.
- Algoritmy preflightu `objednavkaNG` a e-jídelníčku: **sekundárně
  zdokumentovány, ale autoritativní legacy kanál neurčen**.
- Přesná změna varianty A–D: **nepochopena**.
- Produkční audit: **nepochopen**.
- Jediný bezpečný oficiální DB entry point pro JLL: **neurčen**.
- Návrh JLL write vrstvy: **zatím nepřipraven**.

Bezpečný další krok je určit autoritativní legacy objednávkový kanál pro JLL
(desktop `objednavkaNG` proti e-jídelníčku) a read-only porovnat jeho primární
artefakt s dostupným reverse-engineeringem: zejména volání
`aplikujspolusvyloucenos`, použitou write funkci a sestavení eventu.

## 25. FÁZE 0B – AUTORITATIVNÍ KLIENTSKÝ KONTRAKT

### 25.1 Rozsah, primární artefakt a integrita

FÁZE 0B byla provedena read-only vůči DEMO DB i zdrojovým artefaktům.
Nebyla volána žádná write DB funkce ani provedeno DML/DDL. Jedinou změnou
projektu je tato dokumentace.

Primární klientský artefakt byl nalezen:

```text
C:\Work\projects\objednavkaNG\
  electron-build-Windows-22.14.0-v0.1.0\
  win-unpacked\resources\app.asar
```

Identifikace:

- velikost `app.asar`: `22 263 153` B;
- SHA-256:
  `B808DE56CA53EFD5F376BE05C52A8371155173DF08984035B96BB8A81616671B`;
- npm package: `objednavka-ng`;
- package verze: `0.0.0`;
- označení adresáře buildu: `Windows-22.14.0-v0.1.0`;
- hlavní vstup: `dist/main/index.cjs`;
- lokální TypeScript `src` repozitář nebyl nalezen.

Pro statickou analýzu byl `app.asar` rozbalen pouze do dočasného adresáře.
Relevantní bundle zachovává komentáře s původními cestami, zejména:

```text
src/main/foods/create-prihlaska.service.ts
src/main/foods/create-prihlaska.utils.ts
src/main/foods/get-jidelnicek.service.ts
src/main/foods/get-jidelnicek-dates.service.ts
```

Odkazy `NG Lx–Ly` níže míří na extrahovaný
`dist/main/index.cjs` z uvedeného hashe. Odkazy `UI Lx–Ly` míří na
naformátovanou pracovní kopii
`dist/render/assets/index-D9ZIcJn6.js` ze stejného `app.asar`.

Pokus o live ověření skončil ještě před navázáním DB session: lokálně
konfigurovaný endpoint odmítl cílovou databázi jako neexistující. Příkazy
`BEGIN`, `SET TRANSACTION READ ONLY` ani žádný SQL dotaz se proto na live DB
nespustily. Závěry jsou označeny jako ověřené v dumpu, nikoli v live DB.

### 25.2 Doporučený referenční kanál

```text
Doporučený referenční kanál pro JLL:
objednavkaNG
```

`objednavkaNG` je lokální Electron desktop klient připojený přímo k
PostgreSQL přes `pg` a Kysely (`NG L700–L739`). Objednávkový preflight i
volání DB business funkcí probíhají v klientovi. To odpovídá zamýšlenému JLL
výrazně lépe než e-jídelníček, jehož data a write cesta jsou publikovány přes
`ejidelnicek_bridge` a používají odlišný účetní model.

Volba referenčního kanálu neznamená, že je jeho implementace bezpečná ke
zkopírování. Primární artefakt doložil níže popsané mezery v auditu,
vzájemném vyloučení, kontrole návratových hodnot a souběhu.

### 25.3 Autoritativní preflight a call graph

`CreatePrihlaskaService.prihlasJidlo` obaluje celou operaci Kysely transakcí
(`NG L781–L888`) a provádí tuto sekvenci:

```text
vstup: evidcislo, datum, typstravy, action, menu

1. načti UZAVERKA
   hodnota == 'A' → zamítnout
   hodnota == 'N', jiná nebo chybějící → pokračovat

2. načti stravnik podle evidcislo
   nenalezen → zamítnout
   kategorie je NULL/prázdná → zamítnout

3. načti typstrav přes:
   typstravy = vstup
   typsluzby = 'strava'
   pouzivatpcbox = true
   nenalezen → zamítnout

4. načti SELECT NOW() z PostgreSQL

5. canRegisterForDate podle action:
   menu_add    → prihlasdnu + prihlasdo
   menu_change → menudnu    + menudo
   menu_delete → odhlasdnu  + odhlasdo

6. pokud je menu truthy, ověř jidelnicek:
   datum = targetDate
   typstravy = vstup
   zverejneny = true
   cislojidelnicku = 1
   menustravy.caststravy = menu

7. vždy načti cenu přes getPriceForMenu
   NULL / NaN / Infinity → zamítnout

8. vždy spočti kredit a načti kategor.limitprihlasky
   nedostatečný kredit zamítni pouze pro menu_add

9. menu_add    → objednavka_plus(...)
   menu_delete → objednavka_minus(...)
   menu_change → lookup starého menu, minus, plus
```

Zdroj: `NG L784–L887`.

Klient nekontroluje:

- JLL `allowed_categories`;
- `stravnik.stav`, `deleted` ani interval platnosti;
- globální termíny;
- `PreskakovatNevarneDny`;
- `prefer_global_order_limits`;
- `sazby.pocetmenu` explicitním preflightem;
- hromadný účet;
- vzájemné vyloučení typů;
- audit objednávky;
- výsledný stav `prihlas` po DB volání.

### 25.4 Přesný termínový algoritmus

Primární implementace `canRegisterForDate` je na `NG L1053–L1123`.

```text
function canRegisterForDate(currentDateFromSelectNow, targetDate, action):
    if action == menu_add:
        dayTo  = typstrav.prihlasdnu
        timeTo = typstrav.prihlasdo
    else if action == menu_change:
        dayTo  = typstrav.menudnu
        timeTo = typstrav.menudo
    else if action == menu_delete:
        dayTo  = typstrav.odhlasdnu
        timeTo = typstrav.odhlasdo
    else:
        reject

    if dayTo is NULL or timeTo is NULL:
        reject

    normalizedDayTo = max(0, Number(dayTo))
    parse timeTo as H:MM[:SS]
    invalid textual format:
        reject

    deadline = clone(targetDate)
    deadline local time = 00:00:00.000
    deadline local calendar date -= normalizedDayTo
    deadline local time = parsed H:MM:SS.000

    allow exactly when:
        currentDateFromSelectNow <= deadline
```

Přesné důsledky:

- `dnu=0` znamená deadline v cílový kalendářní den v zadaný čas;
- `dnu=1` znamená předchozí kalendářní den v zadaný čas;
- hraniční okamžik je povolen díky `<=`;
- dny jsou kalendářní, nikoli varné;
- `PreskakovatNevarneDny` klient vůbec nečte;
- globální termíny klient vůbec nečte;
- každý druh operace používá vlastní sloupce `typstrav`;
- aktuální okamžik pochází z PostgreSQL `SELECT NOW()`;
- výpočet kalendářního dne a hodin provádí JavaScript `Date` v lokální časové
  zóně klientského procesu. Server dodává autoritativní okamžik, ale klientská
  časová zóna ovlivňuje sestavení deadline;
- `UZAVERKA='A'` blokuje. Jakákoli jiná nebo chybějící hodnota neblokuje
  (`NG L1046–L1052`);
- neplatná numerická hodnota `dayTo`, která není `NULL`, není samostatně
  odmítnuta; vede k neplatnému deadline a výsledkem je zamítnutí přes
  nepravdivé časové porovnání.

Pro aktivní DEMO hodnoty:

```text
menu_add:
  targetDate - 1 kalendářní den v 09:00:00

menu_change:
  targetDate - 1 kalendářní den v 09:00:00

menu_delete:
  targetDate - 0 kalendářních dnů v 08:00:00
```

Termínový algoritmus je primárně doložen, ale vědomě neimplementuje
`PreskakovatNevarneDny=1`.

### 25.5 Finanční preflight

Primární klient počítá (`NG L790–L850`):

```text
currentCredit =
    parseFloat(preplatekmm || '0')
  - parseFloat(platittm    || '0')
  - parseFloat(platitpm    || '0')
  + parseFloat(platbatm    || '0')
  + parseFloat(platbabm    || '0')

parsedLimit = parseFloat(kategor.limitprihlasky || '0')
limitPrihlasky = isFinite(parsedLimit) ? parsedLimit : 0

isInsufficientCredit =
    currentCredit - price < limitPrihlasky
```

Zamítnutí přes `isInsufficientCredit` se provede pouze pro `menu_add`.
Hraniční rovnost je povolena.

NULL, prázdný řetězec a numerická nula vstupních kreditních polí se přes
`value || '0'` převedou na 0. Neprázdný nečíselný text vytvoří `NaN`.
Na rozdíl od limitu klient nekontroluje `Number.isFinite(currentCredit)`;
porovnání s `NaN` je false a finanční zamítnutí se tím může obejít.

Klient nečte:

- `preplatek_sluzby`;
- globální `parametry.povoleny_debet`;
- účetní agregaci `ejidelnicek_bridge.visitor.account`.

Cena se načítá pro všechny tři akce. Při `PouzivatCenik=false` klient volá:

```text
dej_sazbu(kategorie, typstravy, encodedate(rok, mesic, den))
```

Při `PouzivatCenik=true` volá:

```text
getcenamenuden(typstravy, kategorie, rok, mesic, den, menu)
```

Zdroj: `NG L1008–L1044`. Pro DEMO `PouzivatCenik=0` je tedy preflightová
cena primárně ověřena jako `dej_sazbu`, zatímco DB finanční write-path zůstává
na `getcenamenuden` nad `cenik`.

```text
FINANČNÍ PREFLIGHT OBJEDNAVKANG – PRIMÁRNĚ OVĚŘEN
```

### 25.6 Konzistence preflightové a write-path ceny

Byla provedena streamová read-only analýza COPY bloků:

- `public.sazby`: 793 řádků;
- `public.cenik`: 105 577 řádků;
- `public.typstrav`: 13 řádků;
- `public.varnedny`: 392 řádků;
- `public.slozky_ceny`: 4 řádky.

Pro září 2026 byl očekávaný prostor sestaven pro každou sazbu platnou v daný
den, `typstrav.typsluzby='strava'`, každý den s `varnedny.dXX='A'` a každé
menu `1..sazby.pocetmenu`. Porovnával se materializovaný řádek
`cenik.slozka=0`. `slozky_ceny.db_nazev='sazba'` má `s_dph=true`, takže
`getcenamenuden` sazbu dále nenavyšuje o DPH.

Výsledek pro aktuální měsíc dumpu, září 2026:

```text
očekávaných kombinací:             5 124
počet porovnaných kombinací:       5 124
počet shod:                        5 124
počet neshod:                          0
počet chybějících cenik řádků:         0
cenik řádků bez platné sazby:          0
neočekávaných řádků s platnou sazbou:  0
duplicitních cenik klíčů:               0
nejednoznačných aktivních sazeb:        0
```

Jde o 244 aktivních sazeb, všechny s `pocetmenu=1`, a 21 varných dnů.
Pro všechny porovnané kombinace proto platí:

```text
dej_sazbu(...) == cenik.sazba == getcenamenuden(...).cena
```

Následující měsíc, říjen 2026, nelze v dumpu porovnat:

- existuje 244 sazeb platných k 2026-10-01;
- neexistuje žádný říjnový řádek `varnedny`;
- neexistuje žádný říjnový řádek `cenik`;
- rozsah materializovaného `cenik` končí zářím 2026.

Říjnové nuly tedy nejsou shoda ani neshoda, ale nepřítomný budoucí
materializovaný měsíc. `getceniknamesic()` nebyla volána.

### 25.7 Přihlášení, odhlášení a změna menu v jednom typu

#### Přihlášení

`createRegistration` volá pouze:

```text
SELECT objednavka_plus(rok, mesic, den, menu, evidcislo, typstravy)
```

Úspěch vyhodnotí jako `rows[0].result !== null`, nikoli jako prokázanou změnu
nebo konkrétní návrat `1` (`NG L889–L912`).

#### Odhlášení

`cancelRegistration` volá pouze:

```text
SELECT objednavka_minus(rok, mesic, den, menu, evidcislo, typstravy)
```

Opět testuje pouze nenulový SQL výsledek (`NG L914–L940`). Core funkce podle
dumpu mění přesnou číslici menu na `N`, nikoli na `S`.

#### Změna menu v jednom typu

`changeRegistration`:

```text
SELECT dXX
FROM prihlas
WHERE stravnik, mesic, rok, typsluzby
LIMIT 1

orderedMenu = parseInt(dXX)
objednavka_minus(..., orderedMenu, ...)
objednavka_plus(..., newMenu, ...)
```

Zdroj: `NG L941–L1000`.

Lookup neobsahuje `poradiprihl`, `ORDER BY` ani celý PK. Oba návraty se
kontrolují pouze proti SQL `NULL`. Po plus se znovu nenačte `prihlas`.

Celý preflight je v Kysely transakci, ale aplikační chyby jsou uvnitř callbacku
převáděny na běžné `{success:false}` návraty. Neúspěch vyjádřený návratovou
hodnotou po úspěšném minus proto sám nevyvolá rollback. SQL výjimka zpravidla
zneplatní PostgreSQL transakci, ale klient nemá explicitní rollback ani
post-write revalidaci. Chybí `FOR UPDATE`, takže existuje i lost-update riziko
nad měsíčním řádkem.

### 25.8 Oběd A–D

Renderer určuje akci vždy jen uvnitř jedné zobrazené kategorie
`typstravy`:

```text
vybrané menu == orderedMenuId typu → menu_delete
typ už má číselné orderedMenuId     → menu_change
jinak                               → menu_add
```

Zdroj: `UI L5659–L5672`.

Oběd-A, B, C a D jsou čtyři samostatné `typstravy`, každá s jediným
Menu 1. Pokud je objednáno `Oběd-A / Menu 1` a uživatel klikne na
`Oběd-B / Menu 1`, položka B nemá vlastní `orderedMenuId`; renderer proto
odešle:

```text
action = menu_add
typstravy = Oběd-B
menu = 1
```

Main proces následně volá pouze `objednavka_plus(..., 'Oběd-B')`.
Neodhlásí Oběd-A a nevolá `aplikujspolusvyloucenos`.

V celém `app.asar` nejsou symboly:

```text
aplikujspolusvyloucenos
insert_udalost
objednavkaplus
objednavkaminus
uloz_prihlasku_s_dotaci
```

V dumpu nemá `aplikujspolusvyloucenos` žádný DB call site; vedle definice,
`ALTER` a ACL se nevyskytuje. Core `objednavka_plus/minus` ji nevolají.

Autoritativní výsledek tedy není bezpečná A→B orchestrace, ale doložený deficit
`objednavkaNG`: klient může přidat B a ponechat A objednané současně, přestože
`typstrav.vyloucenos` A/B zakazuje. JLL tento postup nesmí převzít.

```text
aplikujspolusvyloucenos orchestrace v objednavkaNG:
NEEXISTUJE
```

E-jídelníčková produkční data ukazují jiný kanál. V dumpu bylo anonymně
korelováno 323 dvojic eventů `?->N` a `?->1` se stejným strávníkem, cílovým
datem a přesně stejným timestampem, ale různým kódem typu. Z toho 25 dvojic
má směr A→B. Data podporují dvoukrokovou změnu typu v e-jídelníčku, ale bez
jeho klientského zdroje nedokazují pořadí SQL volání ani transakční hranici a
nejsou náhradou chybějící orchestrace v `objednavkaNG`.

### 25.9 Přesný kontrakt N / S

| Původ | Původní stav | Akce | Výsledný stav | Zdroj |
|---|---|---|---|---|
| Obvyklý rozpis `stravobv` | neexistující měsíční řádek | `nastavprihlasdleobvykle(..., prihlasit=false)` | znak rozpisu, typicky `S`, nevařený den `*`, nestravný měsíc `N` | SQL L11120–L11194 |
| Obvyklý rozpis `stravobv` | `S` | `nastavprihlasdleobvykle(..., prihlasit=true)` | `1` | SQL L11171–L11176 |
| Ruční objednávka | `S` nebo `N` | `objednavka_plus` | menu `1..9` | SQL L11401–L11422 |
| Ruční objednávka | menu `1..9` | `objednavka_minus` | `N` | SQL L11360–L11369 |
| Změna menu v jednom typu přes NG | menu `1..9` | minus, potom plus | přechodně `N`, cílově nové menu | NG L941–L1000 + SQL L11343–L11425 |
| Přidání vzájemně vyloučeného typu přes DB helper | menu `1..9` v jiném typu | `aplikujspolusvyloucenos` | `S` | SQL L6861–L6948 |
| Hromadná rozpisová odhláška | menu `1..9` + maska `N` | `str2or(..., prihlasovat=false)` | `S` | SQL L12276–L12327 |
| Přidání A→B přes NG | A=`1`, B=`S/N` | `menu_add` pouze na B | A zůstává `1`, B může být `1` | UI L5659–L5672 + NG L854–L864 |

Pro referenční `objednavkaNG` tedy ruční odhlášení znamená `menu→N`.
`S` je rozpisový/výchozí stav a také stav používaný DB helperem při
vzájemném vyloučení nebo hromadné rozpisové odhlášce. Neexistuje obecné
pravidlo „každé odhlášení končí S“.

### 25.10 Audit/event

Primární `objednavkaNG` neskládá ani nezapisuje objednávkový event:

- nevolá `insert_udalost`;
- nevolá wrappery `objednavkaplus/minus*`;
- core `objednavka_plus/minus` samy event nevkládají;
- pro přihlášení, odhlášení ani změnu proto nemá klient žádná eventová pole.

Reálná data `public.udalosti` obsahují 11 290 eventů
`udalost='Přihláška' AND typ='P'`:

- e-jídelníček: 11 153 eventů, vždy verze `v2.0.29`, cena `NULL`,
  `poznamka='?->1'` 9 921× a `'?->N'` 1 232×, `typstravy` je jednopísmenný
  kód;
- ostatní/desktop: 137 eventů, vždy verze `24.1.7` a nenulová cena;
  relevantně `N->1` 67×, `S->1` 46×, `1->S` 5× a `1->N` 1×;
  `typstravy` je textový název.

Žádný z těchto eventů nelze připsat package verzi `objednavkaNG 0.0.0`.
Produkční data pocházejí z e-jídelníčku a jiného desktop klienta
verze `24.1.7`. Neexistuje tedy shoda:

```text
KLIENTSKÝ KÓD objednavkaNG
↔
PRODUKČNÍ OBJEDNÁVKOVÝ EVENT
```

DB wrappery navíc zapisují cenu 0 a pevné poznámky `S->menu` / `menu->S`,
což neodpovídá ani core přechodu `menu->N`, ani uvedeným produkčním eventům.
Auditní kontrakt pro JLL proto zůstává neurčený.

### 25.11 Transakční model a concurrency

`objednavkaNG` používá Kysely `transaction().execute(...)` kolem celého
preflightu a write volání. Nepoužívá:

- `FOR UPDATE`;
- explicitní aplikační lock;
- celý PK při lookupu měsíční přihlášky;
- post-write načtení a porovnání stavu;
- explicitní rollback při `{success:false}`;
- audit ve stejné transakci.

DB core funkce skládají a ukládají celý 31denní řetězec. Dvě souběžné změny
různých dnů stejného měsíčního řádku proto mohou bez zamčení způsobit lost
update. `LIMIT 1` v NG může při více `poradiprihl` vybrat neurčený řádek.
To jsou deficity referenčního klienta, nikoli požadavky pro JLL.

### 25.12 `pouzivatpcbox`

```text
JLL má respektovat pouzivatpcbox: ANO
```

Primární klient filtruje `typstrav.pouzivatpcbox=true`:

- při seznamu zobrazovaných typů (`NG L1262–L1268`);
- znovu v objednávkovém preflightu (`NG L806–L814`).

Typ, který podmínku nesplní, není v UI objednatelný a write preflight jej
odmítne jako nenalezený. Pro DEMO ji splňují Oběd A–D a Svačina; SZU A–D ji
nesplňují.

### 25.13 `cislojidelnicku`

`objednavkaNG` používá pevně:

```text
cislojidelnicku = 1
```

Podmínka je jak v načítání jídelníčku (`NG L1281–L1289`), tak v preflightu
konkrétní objednávky (`NG L833–L838`). Klient nečte `kategor.jidelnicek`,
nemá větev pro `NULL` a nemá fallback. Autoritativní pravidlo tohoto buildu
je tedy hardcoded `1`, nikoli kategoriální výběr.

### 25.14 Bezpečný DB entry point

#### PŘIHLÁSIT

```text
Referenční volání objednavkaNG: objednavka_plus(...)
Bezpečný samostatný entry point JLL: NEURČENO
```

Funkce zajišťuje finanční write-path, ale nekontroluje preflight, ignoruje
boolean z `uloz_prihlasku_s_dotaci`, může vrátit 1 bez změny, neřeší
vzájemné vyloučení ani audit. NG výsledek nerevaliduje.

#### ODHLÁSIT

```text
Referenční volání objednavkaNG: objednavka_minus(...)
Bezpečný samostatný entry point JLL: NEURČENO
```

Funkce finančně zruší přesně nalezené menu a zapisuje `N`, ale rovněž může
vrátit 1 bez změny a nemá audit ani post-write důkaz.

#### ZMĚNIT VARIANTU A–D

```text
Referenční volání objednavkaNG: pouze objednavka_plus na cílový typ
Bezpečný entry point JLL: NEURČENO
```

Referenční klient neprovádí bezpečnou změnu. `aplikujspolusvyloucenos` umí
finančně převést vyloučený typ na `S`, ale chybí autoritativní klientská
sekvence, audit a spolehlivé návratové hodnoty. Nelze rozhodnout, zda má JLL
dělat minus A→N, plus B, plus B→vyloučení A na S nebo jinou kanonickou
sekvenci.

### 25.15 Povinná matice důkazů

| Pravidlo | DEMO DB dump | Primární klient | Reálná udalosti data | Stav |
|---|---|---|---|---|
| Cenový režim | `PouzivatCenik=0`, sazby→cenik | čte `pouzivatcenik()` | — | OVĚŘENO |
| Cena preflightu | `dej_sazbu` definována | při false volá `dej_sazbu` | — | OVĚŘENO |
| Cena write-path | `getcenamenuden` v `uloz_prihlasku_s_dotaci` | volá core plus/minus | desktop eventy nesou cenu | OVĚŘENO |
| Cenová konzistence 2026-09 | 5 124/5 124 shod | větve ceny doloženy | — | OVĚŘENO |
| Cenová konzistence 2026-10 | chybí `varnedny` i `cenik` | sazbu by četl | — | NEOVĚŘENO |
| Kredit | sloupce existují | přesný pětisložkový vzorec | — | OVĚŘENO |
| Limit | `kategor.limitprihlasky` | `<`, rovnost povolena | — | OVĚŘENO |
| Termín přihlášení | hodnoty `typstrav` | přesný kalendářní algoritmus | — | OVĚŘENO |
| Termín změny | hodnoty `typstrav` | přesný kalendářní algoritmus | — | OVĚŘENO |
| Termín odhlášení | hodnoty `typstrav` | přesný kalendářní algoritmus | — | OVĚŘENO |
| `PreskakovatNevarneDny` | hodnota 1 | vůbec nečte | — | ROZPOR |
| `UZAVERKA` | A/N signál | pouze A blokuje | — | OVĚŘENO |
| `pouzivatpcbox` | A–D true, SZU A–D false | UI i preflight vyžadují true | — | OVĚŘENO |
| `cislojidelnicku` | kategorie i jídelníčky existují | hardcoded 1 | — | OVĚŘENO |
| Povolené menu | aktivně `pocetmenu=1` | jídelníček + cena, ne explicitní počet | — | ČÁSTEČNĚ |
| N/S | DB funkce určují přechody | minus→N, same-type change přes N | data obsahují N i S | OVĚŘENO |
| Plus | může vrátit 1 bez změny | testuje jen non-NULL | produkční NG event chybí | ROZPOR |
| Minus | může vrátit 1 bez změny | testuje jen non-NULL | produkční NG event chybí | ROZPOR |
| `vyloucenos` | A–D nakonfigurováno | ignorováno | e-j má párové změny | ROZPOR |
| `aplikujspolusvyloucenos` | definována, bez DB calleru | žádný call site | — | NEOVĚŘENO |
| Audit přihlášení | wrapper neodpovídá core | žádný event | jiné kanály mají eventy | ROZPOR |
| Audit odhlášení | wrapper tvrdí S, core píše N | žádný event | jiné kanály mají N i S | ROZPOR |
| Změna menu v jednom typu | minus+plus technicky dostupné | přesná NG sekvence | nelze připsat NG | ČÁSTEČNĚ |
| Změna A→B | DB helper dostupný | pouze přidá B, A ponechá | e-j páruje `?->N/?->1` | ROZPOR |
| Transakce | core bez termínů/locků | Kysely transakce bez locku/revalidace | — | ČÁSTEČNĚ |

### 25.16 GO / NO-GO gate

```text
Primární objednavkaNG artefakt nalezen: ANO

Referenční kanál pro JLL určen:
objednavkaNG

Termínový algoritmus plně doložen: ANO
Finanční preflight primárně doložen: ANO
Cena preflight vs write-path konzistentní: ANO
N/S kontrakt doložen: ANO
změna Oběd A–D doložena: ANO
aplikujspolusvyloucenos orchestrace doložena: NE
Produkční audit/event doložen: NE

Bezpečný entry point PŘIHLÁSIT určen: NE
Bezpečný entry point ODHLÁSIT určen: NE
Bezpečný entry point ZMĚNIT A–D určen: NE

Připraveno pro návrh JLL write vrstvy: NE
```

Konkrétní zbývající blokery:

1. `objednavkaNG` neobsahuje žádnou A–D orchestrace s
   `aplikujspolusvyloucenos`; jeho skutečné chování porušuje DEMO
   `vyloucenos`.
2. `objednavkaNG` nevytváří objednávkový audit a produkční eventy v dumpu
   patří jiným kanálům/verzím. Chybí autoritativní event kontrakt pro JLL.
3. `objednavka_plus/minus` ani klientská kontrola návratu nedokazují změnu.
   Chybí schválená atomická orchestrace s lockem, revalidací a auditem pro
   přihlášení, odhlášení i změnu.
4. Říjen 2026 má v dumpu platné sazby, ale nemá `varnedny` ani materializovaný
   `cenik`; budoucí měsíc nebylo možné ověřit a live DB nebyla dostupná.

## 26. FÁZE 0D – AKTUÁLNÍ SOURCE OBJEDNAVKANG

### 26.1 Identita autoritativního source

Aktuální funkční TypeScript repozitář:

```text
C:\Work\projects\JidelnaLiteLocal\zdroje\objednavkaNG
```

Read-only Git identita:

```text
branch: main
HEAD: da87e221e1bb9c26cd203d76238ac9c981cc15c1
HEAD commit: da87e22 ci: add install --frozen-lockfile --ignore-scripts to install step
remote: https://github.com/altisima/objednavkaNG.git
working tree: clean
package version: 1.8.0
```

FÁZE 0B analyzovala starší sestavený `app.asar` s package verzí `0.0.0`.
Pro aktuální chování klienta jej od této sekce nahrazuje TypeScript source na
uvedeném HEAD. Níže označené `KOREKCE` jsou změny proti závěrům starého buildu.

Primární source soubory:

- `src/main/foods/services/create-prihlaska.service.ts`;
- `src/main/foods/shared/services/shared-foods.service.ts`;
- `src/main/foods/shared/utils/shared-foods.utils.ts`;
- `src/main/foods/use-cases/create-prihlaska.use-case.ts`;
- `src/main/foods/foods.controller.ts`;
- `src/render/features/MenuList/MenuItem.svelte`;
- `src/render/features/MenuList/MenuList.svelte`.

### 26.2 Společný vstup a UI volba operace

Renderer v `MenuItem.svelte L92–L108` volí:

```text
menu.isOrdered == true
→ menu_delete

menu není objednáno a category.orderedMenuId je číslo
→ menu_change

menu není objednáno a category.orderedMenuId není číslo
→ menu_add
```

Payload:

```text
evidcislo
datum
menu = menu.idMenu
action
typstravy = menu.typstravy
```

Nejprve se přes `foods.needsConfirmation` spustí samostatná read transakce.
Pro `menu_add/menu_change` vrací „potvrzení není potřeba“. Pro
`menu_delete` může vyžádat potvrzení přesně při
`currentCredit < -abs(limitprihlasky)`; budoucí vratku za odhlášení do tohoto
testu nezapočítává (`create-prihlaska.service.ts L34–L79`). Po potvrzení nebo
při nepotřebném potvrzení renderer spustí skutečnou mutaci
(`MenuList.svelte L80–L113`).

Skutečný write call graph začíná:

```text
MenuItem.onChange
→ MenuList.orderMutation
→ preload window.electron.createPrihlaska
→ FoodsController.handlePrihlasJidlo
→ CreatePrihlaskaUseCase.execute
→ CreatePrihlaskaService.prihlasJidlo
→ Kysely transaction().execute(...)
```

Zdroj controller/use-case:
`foods.controller.ts L50–L56`,
`create-prihlaska.use-case.ts L13–L18`.

### 26.3 Společný preflight `prepareOrderContext`

Aktuální pořadí v
`create-prihlaska.service.ts L369–L566`:

```text
1. isUzaverka()
   chybějící hodnota → zamítnout
   hodnota 'A'       → zamítnout

2. načíst stravnik podle evidcislo
   načíst kategorii a kreditní pole
   nenalezen / bez kategorie → zamítnout

3. načíst typstrav:
   typstravy = vstup
   pouzivatpcbox = true
   typsluzby = 'strava'
   načíst termíny, spolecnes, vyloucenos

4. načíst PostgreSQL SELECT NOW()

5. canRegisterForDate(...)
   včetně ověření cílového varného dne

6. ověřit existenci alespoň jednoho řádku jidelnicek:
   datum, typstravy, zverejneny=true, cislojidelnicku=1

7. načíst PouzivatCenik a cenu přesného menu

8. spočítat currentCredit a načíst kategor.limitprihlasky

9. sestavit operace pro spolecnes/vyloucenos
```

Backend v kroku 6 neověřuje, že konkrétní `menu` odpovídá konkrétnímu
publikovanému řádku jídelníčku. Ověřuje pouze existenci nějakého publikovaného
řádku pro datum a typ. Běžné UI posílá zobrazené menu, IPC/backend kontrakt
však sám přesnou vazbu menu→jídelníček nevynucuje.

Stejně jako starý build source nekontroluje JLL `allowed_categories`,
`stravnik.stav`, `deleted`, interval platnosti ani hromadný účet.

### 26.4 KOREKCE – přesný termínový algoritmus aktuálního source

Aktuální source již nepoužívá čisté `targetDate - dnu`. Implementace je v:

- `create-prihlaska.service.ts L664–L803`;
- `shared-foods.service.ts L89–L109, L242–L355`;
- `shared-foods.utils.ts L1–L91`.

Akce stále vybírá:

```text
menu_add    → prihlasdnu + prihlasdo
menu_change → menudnu    + menudo
menu_delete → odhlasdnu  + odhlasdo
```

Přesný algoritmus:

```text
currentDate = PostgreSQL SELECT NOW()
targetDate musí mít varnedny.dXX == 'A'

dayOffset/time = sloupce podle action
čas musí být validní H:MM[:SS] v rozsahu 00:00:00–23:59:59

načti varnedny pro aktuální a následující měsíc relativně k currentDate

pokud dayOffset == 0:
    workingDayOffset = 0
jinak:
    od currentDate zkoušej dayCount = 1, 2, 3, ...
    vyber první datum, které:
        je nejméně dayOffset kalendářních dnů v budoucnosti
        a zároveň má varnedny.dXX == 'A'
    mimo aktuální+následující měsíc → zamítnout

operationStartDate =
    currentDate + workingDayOffset kalendářních dnů
    s nastaveným limitním časem

pokud targetDate je před kalendářním dnem operationStartDate:
    zamítnout
pokud targetDate je později:
    povolit
pokud jde o stejný den:
    povolit pouze current local time < limitní čas
```

Hranice je tedy striktní `<`: přesně v limitním čase už operace povolena
není (`shared-foods.utils.ts L62–L83`).

Algoritmus nepočítá „N varných dnů“. `dayOffset` je minimální počet
kalendářních dnů a výsledek se posune dopředu na první varný den. Parametr
`PreskakovatNevarneDny` source vůbec nečte; varné dny používá bezpodmínečně.
Výpočet kalendáře a hodin probíhá přes lokální JavaScript `Date`, zatímco
aktuální okamžik pochází ze serverového `NOW()`.

Text chyby zobrazuje cutoff vypočtený jako
`targetDate - raw dayOffset` (`create-prihlaska.service.ts L771–L799`), což
není stejný výpočet jako skutečné povolení přes `operationStartDate`.

```text
KOREKCE proti FÁZI 0B:
aktuální source používá varnedny a striktní časovou hranici <.
```

### 26.5 PŘIHLÁSIT – přesný call graph

```text
MenuItem:
  isOrdered=false
  category.orderedMenuId=null
→ action=menu_add

→ needsConfirmation (samostatný preflight)
→ orderMutation
→ IPC foods.createPrihlaska
→ CreatePrihlaskaService.prihlasJidlo
→ Kysely transaction
→ prepareOrderContext
→ finanční kontroly pro menu_add
→ sestavit související operace:
     nejprve cancel všech aktuálně objednaných vyloučených/společných typů
     potom create povinných spolecnes, vždy Menu 1
→ nakonec create hlavního typu/menu
→ SharedFoodsService.executeObjednavkaPlus
→ SELECT objednavka_plus(
     rok,
     mesic,
     den,
     menu,
     evidcislo,
     typstravy
   )
```

Zdroj:

- `MenuItem.svelte L92–L108`;
- `MenuList.svelte L30–L62, L80–L113`;
- `create-prihlaska.service.ts L82–L191, L369–L585`;
- `shared-foods.service.ts L166–L201`.

Návrat se vyhodnotí pouze jako:

```text
result.rows[0]?.result !== null
```

Návrat `0` je tedy úspěch a návrat `1` není důkaz skutečné změny. DB
`objednavka_plus` může vrátit 1 i při no-op a ignoruje boolean z finančního
write-path. Post-write stav se nenačítá.

Po klientském `success` renderer pouze refetchne jídelníček a strávníka
(`MenuList.svelte L47–L62`). Výsledek refetch se neporovnává s očekávaným
stavem, takže nejde o post-write revalidaci.

Objednávkový audit se nevytváří.

### 26.6 ODHLÁSIT – přesný call graph

UI určí `menu_delete`, pokud `menu.isOrdered=true`
(`MenuItem.svelte L97–L101`). Odesílá ID právě zobrazeného objednaného menu.

```text
menu_delete
→ needsConfirmation
→ po případném potvrzení celý preflight znovu v prihlasJidlo
→ cena hlavního menu se znovu načte
→ currentCredit a limit se znovu spočítají
→ kredit není důvodem k zamítnutí menu_delete
→ připraví se cancel operace pro objednané spolecnes i vyloucenos
→ nakonec cancel hlavního typu
→ SharedFoodsService.executeObjednavkaMinus
→ SELECT objednavka_minus(
     rok,
     mesic,
     den,
     menu,
     evidcislo,
     typstravy
   )
```

Zdroj:
`create-prihlaska.service.ts L109–L191, L218–L365, L587–L609`,
`shared-foods.service.ts L204–L240`.

Původní menu hlavní odhlášky pochází přímo z UI payloadu. Backend před
`cancelRegistration` samostatně neověřuje, že tento znak je aktuálně uložený.
Core DB `objednavka_minus` hledá přesnou číslici a zapisuje `N`
(`SQL L11343–L11377`).

Návrat je opět pouze `!== null`; neexistuje post-write ověření ani event.

### 26.7 ZMĚNA MENU V JEDNOM TYPU – přesný call graph

```text
Menu 1 je objednáno
uživatel vybere Menu 2 ve stejném typstravy

MenuItem:
  Menu 2 není isOrdered
  category.orderedMenuId je číslo
→ action=menu_change

→ společný preflight s menudnu + menudo
→ související cancel/create operace
→ changeRegistration
→ getOrderedMenuForDay
→ SELECT dXX FROM prihlas
   WHERE stravnik
     AND mesic
     AND rok
     AND typsluzby
   executeTakeFirst()
→ objednavka_minus(..., oldMenu, ...)
→ objednavka_plus(..., newMenu, ...)
```

Zdroj:
`create-prihlaska.service.ts L170–L183, L611–L661`,
`shared-foods.service.ts L134–L163`.

Lookup:

- nepoužívá celý PK;
- nepoužívá `poradiprihl`;
- nepoužívá `ORDER BY`;
- nepoužívá `FOR UPDATE`;
- při více řádcích vybírá neurčený první řádek.

Kreditní zamítnutí se pro `menu_change` neprovádí, ani pokud je nové menu
dražší. Cena nového menu se ale musí podařit načíst.

Po plus neexistuje revalidace výsledného menu.

### 26.8 Oběd-A→B v aktuálním source

Pro stav:

```text
Oběd-A / Menu 1 = objednáno
Oběd-B / Menu 1 = neobjednáno
```

renderer vyhodnotí B v samostatné kategorii typu:

```text
action = menu_add
typstravy = Oběd-B
menu = 1
backend metoda = prihlasJidlo
```

`prepareOrderContext` načte pro Oběd-B:

```text
vyloucenos = ACD
```

TypeScript helper `aplikujSpolecneSVyloucenoS` projde kódy A, C, D. Pro A
načte denní znak z `prihlas`, zjistí objednané Menu 1 a vytvoří
`objednavkaMinusInput` pro Oběd-A. Pro C/D bez číselného menu cancel
nevytvoří.

Výsledná sekvence operací:

```text
1. SELECT objednavka_minus(..., menu=1, typstravy='Oběd-A')
2. SELECT objednavka_plus (..., menu=1, typstravy='Oběd-B')
```

Obě operace běží sekvenčně uvnitř jedné Kysely transakce
(`create-prihlaska.service.ts L124–L183, L218–L365`).

```text
Oběd-A→B chování aktuálního objednavkaNG:
odhlásí A přes objednavka_minus na N a potom přihlásí B přes
objednavka_plus na Menu 1.
```

Tím aktuální source na rozdíl od starého `app.asar` prakticky respektuje
`vyloucenos`. Nepoužívá však DB helper a výsledný stav A je `N`, zatímco
`public.aplikujspolusvyloucenos` by vyloučený typ změnila na `S`.

Omezení source helperu:

- související typ musí mít `pouzivatpcbox=true`;
- pokud pro související typ nelze načíst cenu, celý vztah se přeskočí, takže
  objednaný vyloučený typ může zůstat;
- pokud cena existuje, ale chybí měsíční `prihlas` řádek souvisejícího typu,
  celý preflight skončí chybou;
- helper lookup nepoužívá `poradiprihl` ani `ORDER BY`;
- při `menu_delete` se nejprve ruší i nalezené související objednávky;
- žádná změna není po zápisu revalidována.

### 26.9 Vztah k DB funkci `aplikujspolusvyloucenos`

DB signatura:

```text
public.aplikujspolusvyloucenos(
    prok integer,
    pmesic integer,
    puvodniprihlaska varchar,
    prihlaskaden varchar,
    pden integer,
    ptypstravy varchar,
    pevidcislo integer
) RETURNS boolean
```

Zdroj: `SQL L6861–L6948`.

Při přihlášení hlavního typu, pokud původně nebyl objednán:

- projde `vyloucenos`;
- objednané vyloučené typy přepíše na `S`;
- projde `spolecnes`;
- neobjednané společné typy přepíše na `1`;
- každou související změnu ukládá přes
  `uloz_prihlasku_s_dotaci`, tedy včetně finanční delty.

Při odhlášení:

- objednané `spolecnes` a závislé typy přepíše na `S`;
- opět používá `uloz_prihlasku_s_dotaci`.

Funkce sama nemění hlavní předaný typ a vrací `true` bez vyhodnocení všech
vnitřních boolean výsledků. Obsahuje diagnostické `insert_udalost` typu `D`,
nikoli úplný objednávkový audit.

V aktuálním TypeScript source neexistuje call site textu
`aplikujspolusvyloucenos`. Podobně pojmenovaná metoda
`aplikujSpolecneSVyloucenoS` je čistě klientský plánovač přímých
`objednavka_minus/plus`.

```text
objednavkaNG volá public.aplikujspolusvyloucenos: NE
DB schopnost existuje, objednavkaNG ji nevyužívá.
```

### 26.10 KOREKCE – cena a finanční preflight

Cena je potvrzena přímo v
`shared-foods.service.ts L21–L87`:

```text
PouzivatCenik=false
→ dej_sazbu(kategorie, typstravy, DDMMYYYY)

PouzivatCenik=true
→ getcenamenuden(typstravy, kategorie, rok, mesic, den, menu)
```

Kredit zůstává:

```text
currentCredit =
    parseFloat(preplatekmm || '0')
  - parseFloat(platittm    || '0')
  - parseFloat(platitpm    || '0')
  + parseFloat(platbatm    || '0')
  + parseFloat(platbabm    || '0')
```

Aktuální source však limit normalizuje:

```text
limitPrihlasky =
    isFinite(parseFloat(value || '0'))
    ? abs(parseFloat(value || '0'))
    : 0
```

a pro `menu_add` zamítá:

```text
currentCredit - price < -limitPrihlasky
```

Zdroj: `create-prihlaska.service.ts L501–L525, L109–L123`.

```text
KOREKCE proti FÁZI 0B:
aktuální source používá zápornou hranici -abs(limitprihlasky),
nikoli porovnání proti kladnému limitprihlasky.
```

Write zamítnutí kreditem:

- `menu_add`: ANO;
- `menu_change`: NE;
- `menu_delete`: NE.

`needsConfirmation` používá u odhlášení kredit pouze k rozhodnutí, zda ukázat
potvrzovací dialog; nejde o zamítnutí.

Pro `spolecnes` source kontroluje cenu hlavního jídla a součet cen společných
typů dvěma oddělenými podmínkami. Nekontroluje
`currentCredit - (main price + related prices)` jednou společnou podmínkou.

Stejně jako starý build se nekontroluje `Number.isFinite(currentCredit)`;
neprázdný nečíselný finanční údaj může vytvořit `NaN` a porovnání obejít.

```text
parametry.povoleny_debet používáno: NE
preplatek_sluzby používáno: NE
```

Výskyty těchto názvů v generovaném `database.types.ts` nejsou runtime použití.

### 26.11 Audit/event

Celý runtime source byl prohledán na:

```text
insert_udalost
objednavkaplus
objednavkaminus
objednavkaplusudalost
objednavkaminusudalost
udalosti
Přihláška
cisloverze
```

Nebyl nalezen žádný runtime call site objednávkového auditu. Tabulka
`udalosti` a `cisloverze` jsou pouze součástí generovaných DB typů.

```text
ObjednavkaNG vytváří audit objednávek: NE
OBJEDNAVKANG AUDIT OBJEDNÁVEK: NEIMPLEMENTOVÁN
```

### 26.12 Transakce, business neúspěch a SQL exception

`prihlasJidlo` používá jednu Kysely transakci pro druhý, autoritativní
preflight i všechny související a hlavní operace
(`create-prihlaska.service.ts L82–L191`).

Operace jsou vykonávány sekvenčně:

```text
related cancel
→ related create
→ main create/cancel/change
```

Při prvním `Result.success=false` metoda provede obyčejný `return r`. Nevyhodí
výjimku a nevolá explicitní rollback. Kysely callback se tedy normálně
dokončí a předchozí úspěšné operace mohou být commitnuty.

```text
Může menu_change skončit částečným stavem,
když minus proběhne a plus businessově neuspěje?
ANO
```

To platí pro business neúspěch reprezentovaný nenulovou transakcí a
návratovou hodnotou `false`, například SQL `NULL` bez exception.

Při skutečné SQL exception ji `executeObjednavkaPlus/Minus` zachytí a vrátí
`false` (`shared-foods.service.ts L166–L240`). PostgreSQL tím ale označí
transakci jako aborted; následný commit ji rollbackne. SQL exception tedy
necommitne předchozí DB změny. Jiná zachycená aplikační výjimka, která
PostgreSQL transakci neabortuje, může skončit stejným částečným commitem jako
business `false`.

Chybí:

- explicitní rollback při business neúspěchu;
- `FOR UPDATE`;
- advisory lock;
- celý PK a `poradiprihl` v lookupech;
- kontrola row count;
- kontrola přesné návratové hodnoty;
- post-write revalidace;
- audit ve stejné transakci.

Concurrency/locking aktuálního klienta není dostatečné. Souběžné operace nad
stejným měsíčním 31denním řetězcem mohou vytvořit lost update.

### 26.13 Co je použitelné pro JLL

| Funkce | objednavkaNG dělá | DB poskytuje | Pro JLL použitelné |
|---|---|---|---|
| Přihlásit | fail-closed preflight, související operace, `objednavka_plus` | finanční přepočet a zápis | ČÁSTEČNĚ |
| Odhlásit | cena+termín, související cancel, `objednavka_minus` | změna na `N` a finanční vratka | ČÁSTEČNĚ |
| Změnit Menu 1→2 | lookup, minus, plus | obě core funkce | ČÁSTEČNĚ |
| Změnit Oběd-A→B | podle `vyloucenos` minus A, plus B | core funkce i samostatný DB helper | ČÁSTEČNĚ |
| Finance | `dej_sazbu/getcenamenuden`, kredit, záporný absolutní limit | `uloz_prihlasku_s_dotaci` | ČÁSTEČNĚ |
| Vyloučení typů | klientská orchestrace přes minus/plus | `aplikujspolusvyloucenos` s výsledkem `S` | ČÁSTEČNĚ |
| Audit | neimplementován | `insert_udalost` a nespolehlivé wrappery | NE |
| Post-write ověření | pouze UI refetch bez assertion | stav lze znovu načíst | NE |

Z aktuálního source lze pro návrh JLL převzít:

- rozdělení akcí `menu_add/menu_change/menu_delete`;
- fail-closed `UZAVERKA`;
- PostgreSQL `NOW()` jako zdroj aktuálního okamžiku;
- action-specific sloupce termínů a kontrolu cílového varného dne;
- `pouzivatpcbox=true`, `zverejneny=true`, `cislojidelnicku=1`;
- cenové větvení `dej_sazbu/getcenamenuden`;
- pětisložkový kredit a zápornou interpretaci absolutního limitu;
- čtení `spolecnes/vyloucenos`;
- DB finanční write-path přes existující core plus/minus.

V JLL je nutné bezpečně doplnit:

- `allowed_categories`, stav/deleted/platnost a zákaz hromadného účtu;
- ověření přesného menu proti publikovanému jídelníčku;
- `Number.isFinite(currentCredit)` a společný finanční test hlavní+související
  stravy;
- jednoznačný lookup celým PK včetně `poradiprihl`;
- row lock nebo ekvivalentní ochranu proti lost update;
- rollback vyvolaný exception při každém business neúspěchu;
- kontrolu skutečné změny, ceny a všech dotčených typů před commit;
- vědomé rozhodnutí `N` proti `S` pro vyloučený typ;
- atomický objednávkový audit s ověřenými poli.

### 26.14 Závěrečný report FÁZE 0D

```text
Aktuální objednavkaNG source ověřeno: ANO
Source HEAD:
da87e221e1bb9c26cd203d76238ac9c981cc15c1

PŘIHLÁSIT logika plně pochopena: ANO
ODHLÁSIT logika plně pochopena: ANO
ZMĚNA MENU 1→2 plně pochopena: ANO

Oběd-A→B chování objednavkaNG:
UI pošle menu_add pro Oběd-B/Menu 1; při úspěšném souvisejícím preflightu
backend podle vyloucenos nejprve zavolá objednavka_minus pro
Oběd-A/Menu 1 (A→N) a potom objednavka_plus pro Oběd-B/Menu 1.

objednavkaNG respektuje vyloucenos: ANO
objednavkaNG volá aplikujspolusvyloucenos: NE

Finanční preflight potvrzen ze source: ANO
Termíny potvrzeny ze source: ANO
Audit objednávek implementován: NE

Post-write revalidace existuje: NE
Concurrency/locking je dostatečné: NE

Z objednavkaNG lze pro JLL bezpečně převzít:
action model, fail-closed preflight, serverový čas, typové termíny a varné
dny, cenové větvení, kreditní zdroje, vyloucenos/spolecnes a DB finanční
core funkce.

V JLL je nutné bezpečně doplnit:
category scope, validaci přesného menu, finite a souhrnný finanční test,
jednoznačný PK lookup, locking, rollback na business neúspěch, post-write
revalidaci, N/S pravidlo a atomický audit.

Připraveno navrhnout JLL objednávkovou write vrstvu: ANO
```

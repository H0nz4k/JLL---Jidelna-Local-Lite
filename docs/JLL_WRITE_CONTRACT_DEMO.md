# JLL – bezpečný objednávkový write kontrakt pro DEMO

Stav návrhu: **FÁZE 1A – návrh pro LAB implementaci**.

Tento dokument definuje budoucí aplikační kontrakt JLL pro přihlášení,
odhlášení, změnu menu v jednom typu a změnu exkluzivní varianty Oběd-A až Oběd-D.
Neobsahuje produkční implementaci ani oprávnění zapisovat do live legacy DB.

Autoritativní vstupy:

- `docs/JLL_DB_ORDERING_RESEARCH_DEMO.md`, zejména FÁZE 0D;
- `objednavkaNG` 1.8.0, HEAD
  `da87e221e1bb9c26cd203d76238ac9c981cc15c1`;
- LAB dump `zdroje/demo.sql`;
- DB core funkce `public.objednavka_plus(...)` a
  `public.objednavka_minus(...)`.

## 1. Principy

### 1.1 Bezpečnostní invariants

Po každém úspěšném `COMMIT` musí platit:

```text
I1: Nikdy nejsou objednány dva vzájemně vyloučené exkluzivní typy současně.

I2: Každý write cílí pouze na strávníka v allowed_categories.

I3: Žádný business neúspěch nesmí commitnout dílčí operaci.

I4: DB návrat 1 není důkaz úspěchu; důkazem je post-write stav.

I5: Finance zapisuje pouze existující DB business logika.

I6: Chybějící/nečíselná cena nebo nevyčíslitelný výsledný kredit znamená
    fail closed; pouze raw NULL finanční komponenta má source-defined nulu.

I7: Audit vznikne jen pro skutečně commitnutou změnu.

I8: Ruční odhlášení JLL končí N.

I9: Každý A→B/C/D přechod je atomický.

I10: Souběžná operace nesmí způsobit lost update.
```

Další invariants:

```text
I11: GUI ani read/preflight service neprovádějí business write SQL.

I12: Žádný write neproběhne bez autoritativního preflightu uvnitř stejné
     transakce a po získání locků.

I13: Každý dotčený prihlas řádek je před write jednoznačný celým PK:
     stravnik, typsluzby, rok, mesic, poradiprihl.

I14: Vstupní menu je znak 1..9 a je doloženo konkrétním zveřejněným
     jídelníčkem i dostupnou DB cenou.

I15: JLL přímo neaktualizuje prihlas, penden ani finanční sloupce stravnik.

I16: Audit, business změna, finance a finální revalidace sdílejí jednu
     transakci.
```

### 1.2 Stavový model

- `1` až `9` znamená objednané menu.
- `N` a `S` jsou pro nový plus přípustné neobjednané výchozí stavy.
- Ruční `menu_delete` a klientsky řízené vyloučení končí vždy `N`.
- `*`, `B`, `NULL`, prázdná nebo jiná hodnota nejsou automaticky
  interpretovány. Operace nad takovým cílovým stavem skončí fail closed.
- JLL nepoužije `public.aplikujspolusvyloucenos`, protože mění vyloučený typ
  na `S`, zatímco aktuální runtime kontrakt `objednavkaNG` používá `N`.

```text
JLL objednávkový runtime kontrakt: N
```

### 1.3 Jediný povolený write-path

JLL volá pouze:

```text
public.objednavka_plus(...)
public.objednavka_minus(...)
public.insert_udalost(...)
```

První dvě funkce smějí měnit objednávky a přes
`uloz_prihlasku_s_dotaci(...)` i finance a dotace. JLL nesmí sestavit nový
31denní řetězec a nesmí přímo měnit účetní data.

Wrappery `objednavkaplus*` a `objednavkaminus*` se nepoužijí. Jejich
poznámky `S->menu` a `menu->S`, cena 0 a audit no-op operací neodpovídají
skutečnému core přechodu.

## 2. Veřejný aplikační kontrakt

Write service přijímá kanonický příkaz:

```text
OrderCommand:
  action: menu_add | menu_delete | menu_change
  evidcislo: integer
  datum: validní lokální datum YYYY-MM-DD bez časové složky
  typstravy: neprázdný přesný DB identifikátor
  menu: integer 1..9
  allowed_categories: neprázdná množina přesných kategor.oznaceni
  actor: identita autentizovaného uživatele nebo schválené technické identity
  client_version: verze JLL
```

`allowed_categories` nikdy nepochází z GUI payloadu jako důvěryhodný údaj.
Dodá jej autorizovaná session/policy vrstva. SQL používá pouze
parametrizovanou podmínku `kategorie = ANY(:allowed_categories)`.

Výsledek:

```text
OrderResult:
  success: true
  action
  datum
  evidcislo
  committed_transitions[]
  committed_at
```

Při neúspěchu se vrací bezpečný error code až po rollbacku. Interní DB
detaily, existence strávníka mimo scope ani finanční údaje jiného scope se
neprozrazují.

UX potvrzení odhlášky je mimo DB transakci. Je pouze informativní; po
potvrzení se spustí nový, plný autoritativní preflight uvnitř write transakce.

## 3. Přesný preflight

### 3.1 Dvě úrovně preflightu

`OrderReadService` smí předem vrátit uživateli dostupnost, cenu a očekávaný
dopad. Jeho výsledek není oprávnění k zápisu a nelze jej přenést do write
služby jako důkaz.

`OrderTransactionService` po získání transakčních locků zopakuje všechny
bezpečnostně významné kontroly nad aktuálními daty. Pouze tento druhý
preflight je autoritativní.

### 3.2 Validace vstupu

Před DB voláním:

1. `evidcislo` je celé číslo v rozsahu PostgreSQL `integer`.
2. `datum` je reálné datum; den odpovídá měsíci a je v rozsahu podporovaném
   DB funkcemi.
3. `menu` je celé číslo 1 až 9. Do core funkce se předá jediný znak.
4. `action` je jedna ze tří povolených hodnot.
5. `typstravy`, `actor` a `client_version` splňují délky cílových DB polí.
6. `allowed_categories` není prázdné, neobsahuje `NULL` ani duplicity.
7. Jakákoli implicitní konverze neplatného čísla, data nebo menu je zakázána.

### 3.3 Globální a uživatelský guard

Uvnitř transakce:

1. `UZAVERKA` musí existovat a mít hodnotu jinou než `A`. Chybějící nebo
   nečitelný signál znamená fail closed.
2. Strávník se načte a zamkne jediným scoped dotazem:

```sql
SELECT ...
FROM public.stravnik
WHERE evidcislo = :evidcislo
  AND kategorie = ANY(:allowed_categories)
  AND stav = 'A'
  AND COALESCE(deleted, false) = false
  AND hromadny IS NOT TRUE
FOR UPDATE;
```

3. Musí existovat právě jeden řádek a neprázdná kategorie.
4. Stejná scope a activity podmínka se databázově ověří těsně před každým
   voláním `objednavka_plus`, `objednavka_minus` a `insert_udalost`.
5. Zamknutý řádek `stravnik` brání běžné souběžné změně kategorie nebo stavu
   do konce transakce. Opakovaný guard je přesto povinný obranný assertion.

`stravnik.platnostod`, `platnostdo`, `datumzahajeni` a `datumukonceni` ve
schématu existují, ale jejich objednávkový business význam není ve FÁZI 0D
doložen. První pilot je nebude svévolně interpretovat. Jde o otevřenou otázku
z části 15, nikoli o domyšlené pravidlo.

### 3.4 Typ stravy

Cílový i každý související typ musí jednoznačně splnit:

```text
typstrav.typsluzby = 'strava'
typstrav.pouzivatpcbox = true
```

Načtou se jeho termíny, `spolecnes`, `vyloucenos`, `kod` a přesný
`typstravy`. Vztahové znaky se mapují přes `typstrav.kod`, stejně jako v
aktuálním source. Neznámý, duplicitní nebo nepovolený vztahový kód znamená
fail closed; vztah se nesmí tiše přeskočit kvůli chybějící ceně.

První pilot používá přímé vztahy stejně jako `objednavkaNG 1.8.0`. Rekurzivní
rozvinutí vnořených `spolecnes` není bez doloženého business pravidla
povoleno.

### 3.5 Serverový čas, termín a varný den

Autoritativní okamžik pochází výhradně ze serverového PostgreSQL času.
`NOW()` se načte kvůli shodě se source kontraktem a jako timestamp transakce.
PostgreSQL jej ale fixuje na začátku transakce, takže po čekání na lock může
být pro striktní deadline zastaralý. Po získání všech locků a těsně před
každým business write se proto načte čerstvý `clock_timestamp()`. Z tohoto
jediného čerstvého okamžiku se znovu provede celý termínový výpočet, včetně
výběru aktuálního/následujícího měsíce a opětovného načtení potřebných
`varnedny`. Nesmí se spojit nový čas se starým kalendářním základem. Jde o
bezpečnostní zpřísnění, nikoli o použití klientských hodin.

Výpočet musí používat explicitně nakonfigurovanou serverovou časovou zónu
shodnou s jídelnou; nesmí záviset na náhodné časové zóně klientského
počítače.

Akce vybírá:

```text
menu_add    -> prihlasdnu + prihlasdo
menu_change -> menudnu    + menudo
menu_delete -> odhlasdnu  + odhlasdo
```

Algoritmus převzatý z aktuálního source:

1. Cílový den musí mít v `varnedny` pro cílový typ hodnotu `A`.
2. `dnu` i čas musí být přítomné a validní; jinak fail closed.
3. Je-li `dnu=0`, offset je nula.
4. Jinak se od serverového dne hledá první varný den, který je nejméně
   `dnu` kalendářních dnů v budoucnosti.
5. Hledání je omezeno na aktuální a následující měsíc vůči serverovému
   okamžiku použitému pro danou revalidaci. Chybějící potřebný kalendář
   znamená fail closed.
6. Cílový den před vypočteným operation start dnem je zamítnut.
7. Cílový den po něm je povolen.
8. Ve stejný den platí striktní hranice `current_time < limit_time`.

změna A→B je z pohledu source `menu_add` cílového B, proto používá
`prihlasdnu/prihlasdo` cílového typu. Interní minus A nepoužívá samostatný
odhlašovací termín. Automatické související kroky sdílejí termín
uživatelské business operace; nejde o samostatné uživatelské příkazy.

### 3.6 Konkrétní menu a jídelníček

Pro každé nově přihlašované menu a pro explicitně požadované menu
odhlášky musí existovat konkrétní vazba:

```text
jidelnicek
-> menustravy
-> typstrj
```

Povinné podmínky:

```text
jidelnicek.datum = :datum
jidelnicek.typstravy = :typstravy
jidelnicek.jazyk = 'česky'
jidelnicek.zverejneny = true
jidelnicek.cislojidelnicku = 1
menustravy.id = jidelnicek.idmenustravy
menustravy.typstravy = jidelnicek.typstravy
typstrj.id = menustravy.idtypstrj
typstrj.oznaceni = CAST(:menu AS text)
```

Stačí `EXISTS`, protože jedno menu může mít více částí. Pokud join vrací
části více různých menu nebo je vazba nekonzistentní, operace se zamítne.
Samotný text jídelníčku není důkaz objednatelnosti.

Pro automatický minus již existujícího konfliktního typu je rozhodující
zamknutý skutečný stav. Publikace starého jídla se může mezitím změnit;
odstranění známé objednávky se kvůli tomu samo o sobě nezablokuje. Cena však
musí být bezpečně doložena pro finanční plán a post-write kontrolu.

### 3.7 Cena a shoda s write-path

Cena se reprezentuje desetinným typem, nikoli binárním `float`.

Při `pouzivatcenik()=false`:

1. `dej_sazbu(kategorie, typstravy, DDMMYYYY)` musí vrátit konečné číslo.
2. Aktivní `sazby` musí jednoznačně povolovat požadované menu přes
   `pocetmenu`.
3. `getcenamenuden(..., menu)` musí současně vrátit `ok=true` a konečnou
   cenu, protože právě tuto materializovanou cestu použije DB finanční core.
4. Preflightová sazba a write-path cena se musí shodovat s tolerancí menší
   než 0,01.

Při `pouzivatcenik()=true` musí `getcenamenuden(...)` vrátit `ok=true`,
jednoznačnou a konečnou cenu.

`NULL`, `NaN`, nekonečno, záporná cena, nejednoznačná sazba nebo cenový
rozpor znamenají fail closed. Nulová cena se nezamítá pouze proto, že je
nulová, pokud ji DB explicitně vrátí jako platnou; zaznamená se však do
diagnostiky, protože aktuální DEMO snapshot nulové aktivní ceny nemá.

Tato dvojí kontrola při `PouzivatCenik=0` je bezpečnostní zpřísnění JLL.
Brání stavu, kdy klient vidí platnou sazbu, ale měsíční `cenik` potřebný pro
write-path chybí nebo je zastaralý.

## 4. Locking model

### 4.1 Transakční režim

Každý příkaz běží v jediné PostgreSQL transakci s izolací `READ COMMITTED`.
Tato volba je záměrná: každý revalidační statement musí vidět stav
commitnutý po předchozím čekání na lock. `REPEATABLE READ` ani
`SERIALIZABLE` se zde nepoužijí jako náhrada explicitních locků, protože
jejich fixní snapshot by mohl revalidovat zastaralou konfiguraci.

Lock a statement timeout jsou konečné a konfigurovatelné. SQLSTATE `40P01`
nebo `55P03` lze automaticky zopakovat nejvýše v malém, konfigurovaném počtu
pokusů. Každý pokus začíná novou transakcí, znovu načte serverový čas a
zopakuje celý preflight. `OrderBusinessError` se nikdy automaticky
neopakuje.

### 4.2 Advisory transaction lock

Core funkce čtou a přepisují celý měsíční 31denní řádek. Lock pouze nad
`evidcislo + rok + mesic + den` by proto nechránil dva souběžné zápisy do
různých dnů stejného měsíce.

JLL jako první lock získá transaction-scoped advisory lock nad:

```text
evidcislo + rok + mesic
```

Bezkolizní kódování pro platný PostgreSQL `integer` `evidcislo`:

```sql
SELECT pg_advisory_xact_lock(
  (:evidcislo::bigint * 1000000)
  + (:rok::bigint * 100)
  + :mesic::bigint
);
```

Šestimístný suffix `YYYYMM` je menší než násobitel `1000000`, takže různé
business klíče se neslijí. Lock se automaticky uvolní při commit/rollbacku.
Chrání i případ, kdy cílový `prihlas` řádek ještě neexistuje.

Tento lock serializuje všechny JLL objednávkové zápisy jednoho strávníka v
jednom měsíci. Menší paralelismus je přijatelný výměnou za ochranu celého
měsíčního řetězce.

### 4.3 Row locks

Po advisory locku se nejprve stabilizuje konfigurační predikát jedním
table-lock statementem:

```sql
LOCK TABLE
  public.cenik,
  public.jidelnicek,
  public.kategor,
  public.menustravy,
  public.parametry,
  public.sazby,
  public.signaly,
  public.slozky_ceny,
  public.stravobv,
  public.typstrav,
  public.typstrj,
  public.varnedny
IN SHARE MODE;
```

`SHARE` dovolí souběžné čtení a stejné JLL objednávkové transakce, ale do
commit/rollbacku zabrání konfiguračnímu `INSERT/UPDATE/DELETE`. Tím chrání i
proti phantom insertu překrývající sazby nebo další cenové složky, který
samotné `FOR SHARE` nad existujícími řádky zachytit neumí. Lock seznam i
pořadí jsou pro všechny JLL transakce pevné. Pokud DB role tento lock nemůže
získat, operace se fail closed odmítne; implementace nesmí ochranu tiše
vynechat.

Potom:

1. Zamkni scoped `stravnik` přes `FOR UPDATE`.
2. Načti přesné guard/config řádky v aktuálním `READ COMMITTED` snapshotu a
   drž je přes `FOR SHARE`: `signaly.UZAVERKA`, kategorii, parametr
   `PouzivatCenik`, cílové a související `typstrav`, potřebné `varnedny`,
   přesné řádky `jidelnicek`, `menustravy`, `typstrj`, aktivní `sazby`,
   použité `cenik` a příslušné `slozky_ceny`.
3. Víceřádkové config lookupy se zamykají samostatnými přesnými dotazy v
   deterministickém pořadí; nespoléhá se na neurčené pořadí locků uvnitř
   komplexního joinu. Chybějící nebo nejednoznačný guard řádek znamená
   fail closed.
4. Odvoď úplnou množinu potenciálně dotčených typů.
5. Seřaď je stabilně podle `typstravy`, potom `poradiprihl`.
6. Jedním parametrizovaným dotazem načti všechny existující `prihlas` řádky
   pro strávníka, rok, měsíc a tuto množinu typů:

```sql
SELECT ...
FROM public.prihlas
WHERE stravnik = :evidcislo
  AND rok = :rok
  AND mesic = :mesic
  AND typsluzby = ANY(:affected_types)
ORDER BY typsluzby, poradiprihl
FOR UPDATE;
```

Pořadí je vždy advisory lock, konfigurační table lock, scoped `stravnik`,
config row locks a nakonec ordered `prihlas FOR UPDATE`. Všechny JLL
transakce používají stejné pořadí, čímž se omezuje deadlock risk.

### 4.4 Jednoznačné `poradiprihl`

Pro každý dotčený typ:

- jeden řádek: zachyť jeho celý PK včetně `poradiprihl`;
- více řádků: `AMBIGUOUS_ORDER_ROW`, rollback;
- žádný řádek před minus/change: `ORDER_ROW_MISSING`, rollback;
- žádný řádek před plus: core smí pod advisory lockem zkusit vytvoření, ale
  návrat 1 se neuzná jako úspěch.

Po plus z neexistujícího stavu musí existovat právě jeden řádek daného typu
pro měsíc, jeho denní stav musí být přesné cílové menu a jeho
`poradiprihl` se stane explicitní součástí post-write identity. Nula nebo
více než jeden řádek znamená rollback.

První pilot tedy podporuje pouze jednoznačné `poradiprihl`; nespoléhá na
`LIMIT 1` ani na předpoklad hodnoty 1. DEMO snapshot má všude hodnotu 1, ale
core `dejporadiprihlasky()` může při chybějícím řádku zvolit 2. Post-write
pravidlo bezpečně přijme pouze jednoznačně vytvořený řádek; nevytvořený nebo
duplicitní výsledek rollbackne.

### 4.5 Omezení advisory locku

Starší klienti advisory lock JLL neberou. Existující `prihlas` a `stravnik`
řádky chrání standardní row locky, ale absolutní koordinaci s libovolným
legacy writerem nelze bez jeho spolupráce garantovat. LAB concurrency test
musí zahrnout i souběžný zápis jiným DB session. Do produkce je bezpečné jít
až po prokázání, že row locky zabrání lost update ve skutečné kombinaci
writerů. Chybějící měsíční řádek zůstává pro mixed-writer provoz zvláštní
riziko a může být produkčně feature-gated na `ORDER_ROW_MISSING`.

## 5. Plán operace a finanční preflight

### 5.1 Normalizovaný plán

Po locku se sestaví `OrderPlan` jako množina skutečných přechodů:

```text
Transition:
  typstravy
  full_prihlas_pk nebo EXPECT_CREATE
  before_state
  after_state
  before_price
  after_price
  reason: primary | spolecnes | vyloucenos
```

No-op přechody se neprovádějí a neauditují. Hlavní no-op je business chyba,
nikoli úspěch. Každý typ se v plánu objeví nejvýše jednou; konfliktní
požadavky na různé cílové stavy znamenají rollback.

Pro `spolecnes` se stejně jako v source plánuje Menu 1. Pokud je již Menu 1
objednáno, je to no-op. Pokud je objednáno jiné menu, plán obsahuje atomický
přechod staré menu → 1. Chybějící nebo neplatná cena souvisejícího typu
nevede k přeskočení vztahu, ale k fail closed.

Pro `vyloucenos` se před přidáním cíle plánuje odstranění všech skutečně
objednaných konfliktů na `N`.

### 5.2 Kredit

Source `objednavkaNG` definuje pro jednotlivé finanční komponenty
`NULL/prázdné -> 0`. JLL tento doložený business význam zachová, ale
normalizaci provede explicitně do `Decimal(0)`. Každá non-NULL komponenta
musí být přesně převoditelná na konečný desetinný údaj a po normalizaci se
finite validace provede nad všemi pěti vstupy i výsledkem:

```text
currentCredit =
    preplatekmm
  - platittm
  - platitpm
  + platbatm
  + platbabm
```

Limit:

```text
allowed_debt = abs(limitprihlasky nebo 0)
minimum_balance = -allowed_debt
```

Neplatný `limitprihlasky` není tiše interpretován jako 0; bezpečný JLL
kontrakt jej na rozdíl od source odmítne jako poškozená finanční data.

### 5.3 Celkový čistý dopad

Pro každý přechod:

```text
N/S -> menu  = +new_price
menu -> N    = -old_price
old -> new   = new_price - old_price
```

Celý plán:

```text
planned_financial_delta = SUM(delta všech skutečných přechodů)
projected_balance = currentCredit - planned_financial_delta
```

Operace, která může zvýšit předpis, je povolena pouze když:

```text
projected_balance >= minimum_balance
```

Hraniční rovnost je povolena. Čistá vratka ani odhlášení nejsou blokovány
kreditem.

Jde pouze o bezpečnostní preflight. Skutečný měsíční přepočet, `penden`,
`platittm/platitpm` a dotace provádí výhradně DB core. Po operaci se
porovnává skutečný finanční výsledek s plánem; JLL žádný účetní údaj samo
nezapisuje.

### 5.4 BEZPEČNOSTNÍ ZPŘÍSNĚNÍ JLL

Souhrnný test se použije i pro:

- `menu_change`, pokud je nové menu dražší;
- Oběd-A→B/C/D jako čistý rozdíl odstraněných a přidaných jídel;
- všechny automatické `spolecnes`;
- kombinaci více vyloučených a přidávaných typů.

Aktuální `objednavkaNG` kredit u `menu_change` nekontroluje a hlavní plus a
`spolecnes` testuje odděleně. JLL toto chování z bezpečnostních důvodů
nepřebírá.

## 6. PŘIHLÁSIT – atomická transakce

Předpoklad hlavního přechodu:

```text
před: N nebo S, případně bezpečně chybějící jednoznačně vytvořitelný řádek
po: přesně požadované menu 1..9
```

Sekvence:

```text
BEGIN ISOLATION LEVEL READ COMMITTED

nastav konečný lock/statement timeout
načti PostgreSQL NOW() jako timestamp transakce
získej advisory xact lock pro evidcislo + rok + mesic
získej konfigurační LOCK TABLE ... IN SHARE MODE
načti a FOR UPDATE zamkni scoped aktivního nehromadného strávníka
ověř UZAVERKA fail closed
načti cílový typ, termín, varnedny, spolecnes a vyloucenos
načti všechny související typy; neznámý vztah = chyba
zamkni existující prihlas řádky ve stabilním pořadí

načti čerstvý serverový clock_timestamp()
z něj znovu načti varnedny a celý deadline výpočet
revaliduj celý autoritativní preflight
ověř konkrétní publikované cílové menu
ověř ceny preflight i finanční write-path
odvoď všechny skutečné konflikty a povinné spolecnes
sestav normalizovaný OrderPlan
ověř jednoznačné poradiprihl
ověř finite kredit a planned_financial_delta

pro každý plánovaný minus v deterministickém pořadí:
  načti nový clock_timestamp() a znovu spočti celý deadline/varnedny základ
  revaliduj category scope a aktivitu
  revaliduj přesný before state
  zavolej objednavka_minus(...)
  ignoruj návrat 1 jako důkaz
  načti přesný PK a ověř after state = N
  ověř měsíční cenu/pocet a průběžné invariants
  při odchylce THROW OrderBusinessError

pro každý povinný spolecnes plus ve stabilním pořadí:
  načti nový clock_timestamp() a znovu spočti celý deadline/varnedny základ
  revaliduj category scope a aktivitu
  revaliduj přesný before state a konkrétní menu/cenu
  zavolej objednavka_plus(...)
  načti jednoznačný výsledný PK
  ověř after state = 1
  ověř měsíční cenu/pocet a průběžné invariants
  při odchylce THROW OrderBusinessError

načti nový clock_timestamp() a znovu spočti celý deadline/varnedny základ
revaliduj category scope, UZAVERKA, termín, cílové menu a cenu
zavolej hlavní objednavka_plus(...)
načti jednoznačný výsledný PK
ověř after state = požadované menu

ověř finální stav všech dotčených a vyloučených typů
ověř skutečný finanční dopad
vlož audit každého skutečného business přechodu
ověř každý insert_udalost(...) = true
proveď poslední scope a invariant assertion

COMMIT
```

Jakýkoli chybějící vztah, neplatná cena, změněný preflight, no-op core
funkce, chybný post-state, audit `false` nebo exception znamená rollback.

## 7. ODHLÁSIT – atomická transakce

Předpoklad:

```text
před: přesně požadované a aktuálně uložené menu
po: N
```

Sekvence locků a společného preflightu je shodná s částí 6. Rozdíly:

1. Použije se `odhlasdnu/odhlasdo`.
2. Staré menu se nebere pouze z payloadu. Musí se shodovat se zamknutým
   denním stavem jednoznačného PK.
3. Kredit se načte a ověří jako validní finanční údaj, ale odhlášku
   neblokuje.
4. Povinné související odhlášky podle `spolecnes` jsou součást stejného
   plánu a transakce.
5. `vyloucenos` samo o sobě není důvod mazat další typ při prosté odhlášce.
   Tento vztah omezuje souběžné přihlášení. Každý skutečně rušený
   `spolecnes` přechází na `N`.
6. Automatické rušení závislých `spolecnes` mimo přímý vztah cíle se v prvním
   pilotu nepovolí bez schváleného business pravidla.

Write část:

```text
pro každý skutečně rušený související typ ve stabilním pořadí:
  fresh clock_timestamp() + celý deadline/varnedny přepočet
  assert scope + přesný before state
  objednavka_minus(...)
  post-read přes celý PK
  vyžaduj N

fresh clock_timestamp() + celý deadline/varnedny přepočet
assert scope + target state = požadované menu
objednavka_minus(...) pro hlavní typ
post-read přes celý PK
vyžaduj N

ověř ceny, počty, finance, vztahové invariants a audit
COMMIT
```

Jestliže hlavní stav už je `N/S`, jde o no-op a operace se rollbackne s
`ORDER_STATE_CONFLICT`; nevytvoří se audit.

## 8. ZMĚNA MENU 1→2 V JEDNOM TYPU

Tato operace je `menu_change`; použije `menudnu/menudo`.

Předpoklad:

```text
před: jednoznačné old menu 1..9
po: jiné, konkrétně požadované new menu 1..9
```

`old_menu == new_menu` je no-op chyba. Nové menu musí mít přesnou
publikovanou vazbu a bezpečnou cenu. Staré menu se čte ze zamknutého PK,
nikoli neurčitým `executeTakeFirst()`.

Sekvence:

```text
BEGIN + společné locky a autoritativní preflight

sestav plán old_price -> new_price
ověř projected_balance včetně případných souvisejících přechodů

fresh clock_timestamp() + celý deadline/varnedny přepočet
assert scope + stav = old_menu
objednavka_minus(..., old_menu, ...)
post-read: přesný PK musí mít N

fresh clock_timestamp() + celý deadline/varnedny přepočet
assert scope + stav = N
revaliduj new menu a new price
objednavka_plus(..., new_menu, ...)
post-read: stejný jednoznačný PK musí mít new_menu

ověř finance, vztahy a finální invariants
zapiš jeden audit old_menu->new_menu pro hlavní business přechod
zapiš samostatné eventy pouze pro skutečně změněné související typy
COMMIT
```

Pokud plus businessově neuspěje, post-read neodpovídá nebo audit selže,
vyhozená `OrderBusinessError` rollbackne i předchozí minus.

Toto je **BEZPEČNOSTNÍ ZPŘÍSNĚNÍ JLL**: dražší změna podléhá souhrnnému
finančnímu preflightu, i když aktuální source kontroluje kredit jen u
`menu_add`.

## 9. ZMĚNA DEMO VARIANTY Oběd-A → Oběd-B/C/D

Pro aktuální DEMO jde o `menu_add` cílového typu s Menu 1 a klientskou
orchestraci `minus conflict -> plus target`.

Příklad A→B:

```text
před:
  Oběd-A = 1
  Oběd-B = N nebo S

po:
  Oběd-A = N
  Oběd-B = 1
  Oběd-C/D ani jiný typ ve vyloucenos B není objednán
```

Přesná sekvence:

```text
BEGIN ISOLATION LEVEL READ COMMITTED
advisory lock evidcislo + rok + mesic
konfigurační LOCK TABLE ... IN SHARE MODE
FOR UPDATE scoped stravnik

načti cílový B a jeho vyloucenos
mapuj všechny kódy přes typstrav.kod
načti všechny aktuální stavy A/C/D a další přímé konflikty
zamkni všechny jejich existující prihlas řádky v lexikografickém pořadí

načti čerstvý clock_timestamp() a znovu spočti celý deadline/varnedny základ
ověř UZAVERKA, menu_add termín B, varný den B a konkrétní B/Menu 1
ověř ceny všech skutečně rušených konfliktů a cíle
sestav jeden plán:
  každý objednaný konflikt menu->N
  B N/S->1
ověř planned_financial_delta a projected_balance

pro každý objednaný konflikt ve stabilním pořadí:
  fresh clock_timestamp() + celý deadline/varnedny přepočet
  assert scope + exact before state
  objednavka_minus(conflict)
  post-read conflict = N

fresh clock_timestamp() + celý deadline/varnedny přepočet
assert scope + B = N/S
revaliduj B/Menu 1 a cenu
objednavka_plus(B, 1)
post-read B = 1

finální scan všech vyloucenos B:
  žádný nesmí mít znak 1..9
ověř A = N, B = 1 a finanční postconditions

audit:
  Oběd-A: 1->N
  Oběd-B: N/S->1
  případně samostatný event pro každý další skutečně odstraněný konflikt

COMMIT
```

Pokud B plus selže, celá transakce vrátí A i ostatní konflikty do původního
stavu. `public.aplikujspolusvyloucenos` se nevolá.

## 10. Post-write revalidace

### 10.1 Po každé core funkci

Bezprostředně po každém plus/minus:

1. Znovu načti všechny řádky typu pro strávníka, rok a měsíc.
2. Vyžaduj právě jeden jednoznačný `poradiprihl`.
3. Ověř přesný znak `dXX`.
4. Ověř, že žádný jiný řádek stejného typu nemá v daný den objednané menu.
5. Ověř očekávanou změnu `pocet`.
6. Ověř měsíční `cena` proti výsledku autoritativní DB cenové cesty a
   očekávanému směru/deltě.
7. Ověř, že scope guard stále platí.

Návrat core funkce se uloží jen pro diagnostiku. `1`, `0` ani non-NULL
nemohou nahradit post-read.

### 10.2 Finanční postconditions

Před prvním write se uloží snapshot:

```text
prihlas.cena a pocet všech dotčených řádků
stravnik.platittm
stravnik.platitpm
relevantní penden stav pro tuto transakci
```

Po posledním write se ověří:

- součet změn `prihlas.cena` odpovídá `planned_financial_delta` s tolerancí
  menší než 0,01;
- směr a souhrnná změna `platittm + platitpm` odpovídají stejné deltě;
- plus zvýšil a minus snížil `pocet` o počet skutečných přechodů;
- finanční pohyb nevznikl pro no-op;
- případné `penden` pohyby odpovídají DB core výsledku a nevznikly přímým
  zápisem JLL.

Pokud existující DB logika vrátí jinou finanční realitu než bezpečný plán,
JLL účetnictví neopravuje. Vyhodí chybu a rollbackne celou transakci.

DEMO snapshot má nulové dotace. LAB pilot musí tuto podmínku předem ověřit.
Konfigurace s nenulovou dotací není bez samostatných dotačních postconditions
automaticky podporována.

### 10.3 Finální vztahové postconditions

Před auditem a po auditu se ověří:

- cílový typ má očekávané menu nebo `N`;
- všechny plánované související typy mají očekávaný stav;
- žádný typ z aktuálního `vyloucenos` cíle nemá `1..9`;
- A→B splňuje A=`N`, B=`menu`;
- žádný neplánovaný dotčený typ se nezměnil;
- scope a aktivita strávníka stále platí.

## 11. Error a rollback pravidla

### 11.1 Interní výjimka

Očekávaný business neúspěch reprezentuje:

```text
OrderBusinessError:
  code
  safe_message
  internal_context
```

Příklady kódů:

```text
ORDERING_CLOSED
OUT_OF_SCOPE_OR_INACTIVE
HOUSEHOLD_ACCOUNT_UNSUPPORTED
DEADLINE_EXPIRED
NON_COOKING_DAY
MENU_NOT_AVAILABLE
PRICE_INVALID
PRICE_PATH_MISMATCH
CREDIT_DATA_INVALID
INSUFFICIENT_CREDIT
AMBIGUOUS_ORDER_ROW
ORDER_ROW_MISSING
ORDER_STATE_CONFLICT
RELATION_CONFIG_INVALID
POSTCONDITION_FAILED
AUDIT_FAILED
CONCURRENT_MODIFICATION
```

Každé zjištění tohoto stavu uvnitř transaction callbacku musí udělat
`throw`, nikoli `return false`.

### 11.2 Technické chyby

- SQL exception se nezachytí a nepřevede na normální success/failure návrat
  uvnitř transakce; propaguje se tak, aby driver provedl rollback.
- Zachycení je dovoleno až vně transaction callbacku pro mapování bezpečné
  odpovědi a logování.
- `40P01` a `55P03` lze omezeně retryovat podle části 4.
- Lock timeout, statement timeout a ztráta spojení se nikdy neinterpretují
  jako neznámý success. Klient po takové chybě pouze read-only ověří stav;
  původní příkaz slepě neopakuje mimo řízenou idempotentní retry politiku.

### 11.3 Fail closed

Rollback vyvolá mimo jiné:

- změna category scope mezi read a write;
- více `poradiprihl`;
- chybějící přesné menu;
- neplatná nebo rozdílná cena;
- nečíselný kredit;
- business no-op core funkce;
- neočekávaný stav po kterémkoli mezikroku;
- finanční odchylka;
- porušení `vyloucenos`;
- `insert_udalost=false` nebo audit exception.

## 12. Category scope

Category scope je authorization boundary, ne UI filtr.

1. `allowed_categories` vytváří serverová autorizace.
2. Každý samostatný read nad konkrétním strávníkem obsahuje scoped podmínku.
3. Write transakce načte `stravnik` scoped dotazem `FOR UPDATE`.
4. Před každým business write a auditem se provede stejný DB assertion.
5. Nalezení strávníka pouze bez scope se nepoužije jako fallback.
6. Pokud kategorie během čekání na lock přešla mimo scope, scoped načtení po
   získání locku nevrátí řádek a operace rollbackne bez write.
7. Logy a error response nesmějí odhalit údaje strávníka mimo scope.

Zamčení `stravnik` znamená, že standardní souběžný `UPDATE` kategorie musí
počkat. Finální scope assertion chrání kontrakt i proti aplikační chybě v
plánu.

## 13. JLL AUDITNÍ KONTRAKT – NÁVRH K SCHVÁLENÍ

Tato část je nový návrh JLL. Není to historicky autoritativně potvrzený
JidelnaSQL kontrakt.

### 13.1 DB API

Použije se:

```text
public.insert_udalost(
  puzivatel text,
  pudalost text,
  ptyp text,
  ppoznamka text,
  pcisloverze text,
  pstravnik integer,
  pdatumobj text,
  pcena integer,
  ptypstravy text
) RETURNS boolean
```

Pole:

```text
uzivatel    = skutečný autentizovaný uživatel;
              schválená technická identita "JLL" jen bez osobního loginu
udalost     = "Přihláška"
typ         = "P"
poznamka    = skutečný business přechod, např. N->1, S->1, 1->N, 1->2
cisloverze  = přesná verze JLL
stravnik    = evidcislo
datumobj    = cílové datum jako DDMMYYYY
cena        = cena konkrétního menu podle níže uvedeného pravidla
typstravy   = přesný text typstrav.typstravy
```

Vstupy se před write validují proti délkám `udalosti`: uživatel 25,
udalost 30, typ 1, poznámka 50, verze 10 a typ stravy 30 znaků.

### 13.2 Cena eventu

- `N/S->menu`: cena přidaného menu.
- `menu->N`: cena odstraněného menu.
- `old->new`: cena nového menu; čistá delta je v interním structured logu,
  nikoli v omezeném historickém poli `cena`.
- A→B: event A nese cenu odstraněného A, event B cenu přidaného B.

DB API přijímá `integer` a tabulka ukládá `numeric(15,0)`. Cena se předá
jen pokud je autoritativní cena přesně celočíselná a vejde se do rozsahu.
Neintegrální cena se nesmí svévolně zaokrouhlit; do `pcena` se předá `NULL`
a omezení se zaznamená. Aktuální DEMO ceny jsou celočíselné.

### 13.3 Počet a granularita eventů

- Přihlášení: jeden event za každý skutečně přidaný typ.
- Odhlášení: jeden event za každý skutečně odstraněný typ.
- Změna menu v jednom typu: jeden event `old->new`, nikoli dva eventy
  `old->N` a `N->new`, protože audit popisuje atomickou business operaci.
- A→B: dva eventy, A `1->N` a B `N/S->1`.
- Další skutečně změněný `spolecnes` nebo konflikt má vlastní event.
- No-op nemá event.

Všechny eventy se vloží až po úspěšné business a finanční revalidaci, ale
stále před commit. Pokud kterýkoli návrat není přesně `true`, vyhodí se
`AUDIT_FAILED` a rollbackne se business změna i již vložené eventy.

`insert_udalost` nemá correlation ID ani jednoznačný návrat vloženého řádku.
V první implementaci je důkazem úspěchu návrat `true` ve stejné transakci a
absence SQL exception. Přidání korelačního identifikátoru by vyžadovalo
samostatně schválenou změnu kontraktu nebo schématu.

## 14. Výkonový model a vrstvy

### 14.1 Rozdělení odpovědností

```text
OrderReadService
  read-only UX preflight, nabídka akcí, preview ceny a potvrzení

OrderTransactionService
  autoritativní transakce, locking, plán, core calls, revalidace, audit

OrderRepository
  pouze parametrizované dotazy a přesně typované DB funkce
  žádná business rozhodnutí v GUI
```

GUI nikdy neposílá SQL, neskládá finanční vzorec jako autoritu a nerozhoduje
o category scope.

### 14.2 Omezení round-tripů

Preflight se spojí bez oslabení correctness:

1. Jedním dotazem serverový čas, `UZAVERKA`, scoped strávník a kategorii.
2. Jedním dotazem cílový typ a všechny typy mapované z
   `spolecnes/vyloucenos`.
3. Jedním dotazem `varnedny` pro potřebné měsíce a typy.
4. Jedním dotazem exact-menu `EXISTS` pro všechna přidávaná menu.
5. Jedním dotazem ceny všech plánovaných before/after stavů, pokud lze
   zachovat stejné chování DB funkcí.
6. Jedním ordered `FOR UPDATE` dotazem všechny existující `prihlas` řádky.

Následné core call + post-read páry zůstávají oddělené, protože po každé DB
business funkci je povinná revalidace. Pro DEMO A→B je očekávaný write počet
malý: minus A, plus B, dva post-ready, finální assertion a dva audit calls.

Vzdálené spojení musí mít connection pooling, konečné timeouty a měření
latence. Transakce se nesmí držet během čekání na UX potvrzení.

## 15. Otevřené otázky

Následující otázky neblokují návrh, ale musí být uzavřeny před příslušným
produkčním rozsahem:

1. Jaký je přesný objednávkový význam `platnostod`, `platnostdo`,
   `datumzahajeni` a `datumukonceni` strávníka?
2. Má být technický actor přesně `JLL`, nebo vždy osobní login? Jak se mapuje
   delší identita do limitu 25 znaků?
3. Má audit u neintegrální ceny ukládat `NULL`, nebo bude schválena jiná
   verze DB API s desetinnou cenou?
4. Mají se `spolecnes` vztahy rozvíjet rekurzivně a jak se řeší cyklus?
5. Má prosté `menu_delete` rušit pouze přímé `spolecnes`, i závislé typy,
   nebo žádné automatické typy? První pilot povolí jen explicitně ověřený
   přímý vztah.
6. Jaký je provozní režim souběhu JLL se staršími writery, které nepoužívají
   advisory lock?
7. Má produkční JLL DB role oprávnění získat `SHARE` lock nad všemi
   konfiguračními tabulkami a je krátké blokování jejich admin DML provozně
   přijatelné? Bez ekvivalentního společného config-lock protokolu nelze tento
   guard odstranit.
8. Jaké konkrétní hodnoty lock timeoutu, statement timeoutu a retry limitu
   odpovídají latenci centrální legacy DB?
9. Má být `cislojidelnicku=1` trvalý JLL kontrakt, nebo později
   konfigurovatelná politika? Pro první pilot je autoritativně pevné 1.
10. Je bezpečné v produkci přijmout jednoznačně nově vytvořené
   `poradiprihl=2`, nebo má první release chybějící měsíční řádek vždy
   odmítnout? LAB musí změřit skutečné chování `stravobv`.
11. Jak přesně post-validovat nenulové dotace? Dokud není odpověď, první
    pilot je omezen na doložený DEMO stav s nulovou dotací.
12. Potvrdit business rozhodnutí, že při prostém delete se `vyloucenos`
    nemaže. Návrh jej považuje za constraint pro add, nikoli závislost pro
    delete.

## 16. Akceptační kritéria budoucí LAB implementace

Implementace může být označena jako připravená k LAB testu pouze pokud:

1. Neobsahuje přímý `UPDATE/INSERT/DELETE` nad `prihlas`, `penden` ani
   finančními sloupci `stravnik`.
2. Všechny čtyři operace používají jedinou `READ COMMITTED` transakci s
   explicitními guard, advisory a row locky.
3. První lock je měsíční advisory xact lock; existující řádky jsou navíc
   zamčeny ordered `FOR UPDATE`.
4. Konfigurační predikáty jsou proti phantom DML chráněny jednotným
   `LOCK TABLE ... IN SHARE MODE`; chybějící oprávnění znamená fail closed.
5. Category scope je v každém read/write guardu a `stravnik` je scoped
   `FOR UPDATE`.
6. Více `poradiprihl` se fail closed odmítne.
7. Přesné menu se ověřuje přes
   `jidelnicek -> menustravy -> typstrj.oznaceni`.
8. Při `PouzivatCenik=0` se ověří shoda `dej_sazbu` a
   `getcenamenuden`.
9. Všechny finanční hodnoty používají přesný decimal typ a finite validaci.
10. `planned_financial_delta` zahrnuje hlavní i všechny související kroky.
11. Dražší `menu_change` je blokována stejným minimálním zůstatkem jako add.
12. Každý business failure uvnitř callbacku vyhodí exception a rollbackne.
13. Po každém plus/minus existuje assertion přesného PK, stavu, ceny a počtu.
14. Finální assertion ověřuje všechny dotčené `vyloucenos`.
15. Ruční delete a A→B minus končí `N`.
16. A→B je `minus A -> assert N -> plus B -> assert menu` v jedné transakci.
17. Audit se zapisuje přes `insert_udalost`, odpovídá skutečným přechodům a
    jeho failure rollbackne vše.
18. No-op nevytvoří event ani success.
19. Lock timeout a deadlock mají bezpečný, omezený retry.
20. GUI potvrzení nedrží otevřenou transakci.
21. Integrační testy běží pouze proti obnovitelné LAB DB, nikdy proti live
    produkci bez samostatného oprávnění.
22. Termín se po získání všech locků a před každým write revaliduje čerstvým
    serverovým časem, nikoli zastaralým transaction `NOW()` nebo klientskými
    hodinami.

Povinné LAB testy:

- add `N->1` a `S->1`;
- delete `1->N`;
- change `1->2`, včetně dražší a levnější varianty;
- A→B a současně A→C ve dvou sessions;
- dvě změny různých dnů stejného měsíčního řádku;
- stejný den ve dvou sessions;
- category změněná během čekání na lock;
- více `poradiprihl`;
- chybějící měsíční řádek a chybějící `stravobv`;
- core návrat 1 bez skutečné změny;
- minus úspěch a následný plus business failure – celý stav musí rollbacknout;
- chybějící/NaN/nekonečná cena či kredit;
- nesoulad `dej_sazbu` proti `getcenamenuden`;
- nepublikované nebo jiné konkrétní menu;
- audit `false`/exception – business změna i finance musí rollbacknout;
- lock timeout, deadlock a retry limit;
- chybějící oprávnění ke konfiguračnímu `SHARE` locku;
- phantom pokus o změnu sazby/ceníku/jídelníčku během objednávky;
- kontrola, že žádný vyloučený exkluzivní typ nezůstane objednán;
- finanční delta v `prihlas`, `penden` a `platittm/platitpm`;
- nulová dotace jako povinná pilotní precondition.

## 17. Závěrečný report FÁZE 1A

```text
JLL write kontrakt navržen: ANO

PŘIHLÁSIT kontrakt kompletní: ANO
ODHLÁSIT kontrakt kompletní: ANO
Menu change kontrakt kompletní: ANO
A→B kontrakt kompletní: ANO

Category scope součástí write kontraktu: ANO
Locking model definován: ANO
Business failure vždy rollback: ANO
Post-write invariants definovány: ANO

Finance zůstávají v DB business logice: ANO
Finite/souhrnný finanční preflight definován: ANO

Audit návrh vytvořen: ANO
Audit historicky autoritativně potvrzen: NE

Připraveno pro LAB implementaci/test write služby: ANO
```

Toto `ANO` povoluje pouze implementaci a testování proti obnovitelné LAB DB.
Nepovoluje produkční write ani nasazení. Otevřené otázky 1–12 musí být
feature-gated; zejména první pilot nepodporuje hromadné účty, více
`poradiprihl`, nenulové dotace ani nedoložené rekurzivní `spolecnes`.

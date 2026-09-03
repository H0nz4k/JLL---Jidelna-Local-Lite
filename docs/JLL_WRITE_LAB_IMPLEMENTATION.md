# JLL – LAB implementace bezpečné objednávkové write služby

Stav: **FÁZE 1B – DONE**

Implementace je určena výhradně pro obnovitelnou lokální PostgreSQL LAB
databázi. Není schválena pro produkční legacy DB, GUI, installer ani release.

## 1. Implementovaný rozsah

Služba podporuje:

- `menu_add`: `N/S -> menu`;
- `menu_delete`: `menu -> N`;
- `menu_change`: `old_menu -> N -> new_menu` v jedné transakci;
- změnu Oběd-A na Oběd-B/C/D jako odstranění všech aktuálně
  objednaných přímých konfliktů a následné přidání cílového typu.

Finance a dotace zapisují pouze existující funkce
`public.objednavka_plus(...)` a `public.objednavka_minus(...)`. Python
počítá bezpečnostní preflight a postconditions, ale neprovádí přímý write do
`prihlas`, `penden` ani finančních sloupců `stravnik`.

## 2. Architektura a soubory

- `src/jll/orders/models.py` – typovaný command/result, plán, přechody,
  snapshoty a nastavení.
- `src/jll/orders/errors.py` – bezpečné `OrderBusinessError` kódy.
- `src/jll/orders/preflight.py` – `Decimal`, kredit, limit, deadline a
  porovnání finančních delta.
- `src/jll/orders/repository.py` – parametrizované SQL, locky, DB core,
  post-ready a auditní funkce.
- `src/jll/orders/audit.py` – auditní poznámka a převod ceny bez
  zaokrouhlování.
- `src/jll/orders/service.py` – autoritativní transakce, plán, orchestrace,
  revalidace, rollback a omezený retry.
- `tests/unit/test_orders.py` – čisté bezpečnostní a hraniční testy.
- `tests/integration/conftest.py` – izolovaný DB clone pro každý test.
- `tests/integration/test_orders_postgres.py` – skutečné PostgreSQL write,
  rollback, finance, audit, lock a concurrency testy.
- `tools/restore_demo_lab.ps1` – guardovaný fresh restore LAB dumpu.
- `tools/run_lab_tests.ps1` – guardovaný test runner.

`OrderService` přijímá samostatný `scope_provider`. Hodnota
`OrderCommand.allowed_categories` se před otevřením DB spojení musí přesně
shodovat s kategoriemi z důvěryhodné policy/session vrstvy. Command se tedy
nemůže autorizovat vlastním payloadem.

## 3. LAB guard

Před každou write transakcí musí současně platit:

- `environment == "lab"`;
- nakonfigurovaný host je `localhost`, `127.0.0.1` nebo `::1`;
- nakonfigurovaná i skutečná DB začíná `jll_` a názvy se přesně shodují;
- `inet_server_addr()` je loopback;
- `pg_control_system().system_identifier` přesně odpovídá předem schválenému
  lokálnímu PostgreSQL clusteru.

Poslední kontrola brání tomu, aby vzdálená `jll_*` DB dostupná přes lokální
SSH tunnel prošla pouze díky loopback adrese.

Negativní unit testy pokrývají jiné prostředí, non-local host/server,
neplatný DB prefix, jiný skutečný název DB, jiný PostgreSQL cluster a
podvržený category scope. Integrační fixture a oba PowerShell nástroje
používají stejné host/name/system-identifier podmínky.

## 4. Transakční kontrakt

Každá operace používá jednu `READ COMMITTED` transakci:

1. konečný `lock_timeout` a `statement_timeout`;
2. měsíční `pg_advisory_xact_lock(evidcislo + YYYYMM)`;
3. při výchozím `strict_config_lock=true` jednotný
   `LOCK TABLE ... IN SHARE MODE`;
4. scoped aktivní nehromadný `stravnik FOR UPDATE`;
5. config row preflight;
6. deterministicky seřazené `prihlas FOR UPDATE`;
7. čerstvý `clock_timestamp()` a celý deadline/`varnedny` přepočet;
8. sestavení jednoho finančního plánu;
9. před každým core write nový serverový čas, scope, stav, menu a cena;
10. po každém core write kontrola přesného `poradiprihl`, `dXX`, `cena`,
    `pocet` a scope;
11. finální per-type i souhrnná kontrola `prihlas`, `stravnik` a `penden`;
12. audit přes `public.insert_udalost(...)`;
13. poslední scope a vztahový invariant;
14. commit.

Business chyba je vždy exception. Návrat core funkce je pouze diagnostika.
SQLSTATE `40P01` a `55P03` lze omezeně zopakovat; každý retry používá nové
spojení, novou transakci a celý nový preflight.

## 5. Implementované invariants

- Žádný write mimo přesný trusted category scope.
- Hromadný účet, více `poradiprihl`, chybějící měsíční řádek a neznámý stav
  jsou fail closed.
- `UZAVERKA`, typ služby, `pouzivatpcbox`, termín, varný den, publikace
  konkrétního menu a přímé vztahy se ověřují uvnitř transakce.
- Deadline používá source algoritmus `objednavkaNG 1.8.0` a striktní `<`.
- Při `PouzivatCenik=false` se vyžaduje shoda `dej_sazbu` a
  `getcenamenuden` pod 0,01.
- `NULL`, NaN, nekonečná nebo záporná cena jsou odmítnuty.
- Kredit používá `Decimal`; pouze source-defined `NULL` finanční komponenta
  se normalizuje na nulu.
- Kredit se kontroluje nad čistým dopadem celého plánu. Vratka ani delete
  nejsou blokovány.
- Nenulová `dotace` nebo `fksp` je pro pilot odmítnuta.
- A→B/C/D nevolá `public.aplikujspolusvyloucenos` a rušené typy končí `N`.
- Finanční postconditions kontrolují částku i počet `penden` pohybů pro každý
  typ zvlášť, souhrnnou cenu, `pocet` a `platittm + platitpm`.
- Audit vzniká pouze pro skutečné business přechody a jeho `false` nebo SQL
  chyba rollbackne business, finance i dříve vložené eventy.

## 6. Reprodukovatelný restore a test

Po ručním ověření konkrétní lokální Windows PostgreSQL služby zjisti její
serverovou identitu read-only:

```powershell
psql -X -w -h 127.0.0.1 -p 5433 -U postgres -d postgres -Atc "SELECT current_database(), host(inet_server_addr()), inet_server_port(), system_identifier FROM pg_control_system();"
```

Fresh restore vyžaduje explicitní potvrzení a očekávaný system identifier:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\restore_demo_lab.ps1" `
  -HostName "127.0.0.1" `
  -Port 5433 `
  -UserName "postgres" `
  -DatabaseName "jll_demo_lab" `
  -ExpectedSystemIdentifier "<OVĚŘENÝ_SYSTEM_IDENTIFIER>" `
  -ConfirmFreshRestore
```

Skript dropne/recreate pouze jméno odpovídající `^jll_`, používá
`--no-owner --no-privileges`, ověří DB core signatury a nikdy nemění
`zdroje/demo.sql`.

Celá sada:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\tools\run_lab_tests.ps1" `
  -HostName "127.0.0.1" `
  -Port 5433 `
  -UserName "postgres" `
  -TemplateDatabase "jll_demo_lab" `
  -ExpectedSystemIdentifier "<OVĚŘENÝ_SYSTEM_IDENTIFIER>"
```

Každý integrační test vytvoří vlastní databázi `jll_test_*` příkazem
`CREATE DATABASE ... TEMPLATE jll_demo_lab`, po testu ukončí pouze její
sessions a clone odstraní. Testy proto nezačínají ze stavu předchozího testu.

## 7. Skutečně provedené testy

Finální běh dne 2026-09-03:

```text
59 passed in 160.50s
31 unit
28 PostgreSQL integration
```

Integračně prošly add z `N` i `S`, delete, no-op rollback, dražší
change pass/fail, levnější change, A→B, A→C, souběžné A→B proti A→C,
souběh dvou dnů stejného měsíce, souběh stejného dne, změna kategorie při
čekání, více `poradiprihl`, chybějící `prihlas`/`stravobv`, neúčinný core
return 1, rollback skutečného minus při selhání plus, rollback prvního
skutečně vloženého auditu při druhém audit failure, price NULL/mismatch,
credit NaN, jiné/nepublikované menu, nenulová dotace, skutečný lock timeout,
skutečný PostgreSQL deadlock s retry, chybějící config-lock oprávnění a
blokování admin DML strict lockem.

`python -m compileall -q src tests` prošel a editor diagnostics nehlásily
chyby.

## 8. Strict config lock – naměřené chování

Na lokálním PostgreSQL 16, na čistém izolovaném clone, jeden `menu_add`:

```text
advisory_lock_wait_ms=0.547
config_lock_wait_ms=0.596
transaction_ms=659.058
```

Předchozí teplý smoke vzorek stejné operace měl transakci přibližně 173 ms.
Jde o jednotlivé lokální vzorky, ne o produkční latency benchmark.

Integrační test držel strict `SHARE` lock a souběžný admin
`UPDATE public.signaly` po 150 ms skončil skutečným SQLSTATE `55P03`.
Lock tedy podle návrhu blokuje běžný config DML po celou write transakci.

Pro LAB je chování přijatelné a ochrana zůstává výchozí. Pro vzdálený
produkční provoz zatím nelze broad lock označit za provozně realistický:
je nutné samostatně změřit skutečnou latenci a admin workflow. Ochrana se
nesmí vypnout bez ekvivalentní jemnější revalidace.

## 9. Známé limity před produkcí

- Pouze LAB; žádná produkční connection konfigurace ani release.
- `scope_provider` je aplikační rozhraní. Produkční session/policy a ochrana
  instalační konfigurace ještě nejsou implementovány.
- Chybějící `prihlas` row je v pilotu bezpečně odmítnuta; automatické
  vytvoření přes `stravobv` není povoleno.
- Více `poradiprihl`, hromadné účty, nenulové dotace a rekurzivní
  `spolecnes` nejsou podporovány.
- Produkční souběh s legacy writery bez JLL advisory locku nebyl měřen.
- Broad config `SHARE` lock nebyl měřen proti vzdálené legacy latenci ani
  reálné administraci.
- Test fixture používá doložený LAB dump a LAB-only data setup. Do
  produkce se žádné fixture SQL nepřenáší.

Lokálně zůstává pouze obnovená šablona `jll_demo_lab`; všechny testovací
`jll_test_*` a měřicí databáze byly po běhu odstraněny.

## 10. Výsledek FÁZE 1B

```text
LAB write service implementována: ANO

LAB guard implementován: ANO
PŘIHLÁSIT implementováno: ANO
ODHLÁSIT implementováno: ANO
Menu change implementováno: ANO
A→B/C/D implementováno: ANO

Category scope implementován: ANO
Advisory locking implementován: ANO
Row locking implementován: ANO
Strict config lock implementován: ANO

Business failure rollback ověřen: ANO
Post-write revalidace ověřena: ANO
Financial delta ověřena: ANO
Audit rollback ověřen: ANO

Concurrency testy prošly: ANO
LAB integration testy: 28/28

Strict config lock – naměřené chování:
0.596 ms získání bez konkurence; admin DML blokován alespoň 150 ms;
lokální transakce 173–659 ms ve dvou smoke vzorcích.

Známé blokery:
žádné pro LAB review; produkční policy, mixed-writer souběh, nenulové dotace
a vzdálené config-lock měření zůstávají mimo rozsah FÁZE 1B.

Připraveno pro review před první GUI integrací: ANO
```

## 11. FÁZE 1C – CODE REVIEW

Stav review: **DONE** dne 2026-09-03.

### 11.1 Zkontrolovaný rozsah

Review nevyšlo pouze z tohoto dokumentu. Byly zkontrolovány:

- `docs/JLL_WRITE_CONTRACT_DEMO.md`;
- `docs/JLL_DB_ORDERING_RESEARCH_DEMO.md`, zejména FÁZE 0D;
- aktuální `objednavkaNG` 1.8.0 source pro deadline, menu a vztahy;
- `src/jll/orders/models.py`;
- `src/jll/orders/errors.py`;
- `src/jll/orders/preflight.py`;
- `src/jll/orders/repository.py`;
- `src/jll/orders/audit.py`;
- `src/jll/orders/service.py`;
- `tests/unit/test_orders.py`;
- `tests/integration/conftest.py`;
- `tests/integration/test_orders_postgres.py`;
- `tools/restore_demo_lab.ps1`;
- `tools/run_lab_tests.ps1`;
- relevantní funkce a tabulky v obnoveném `zdroje/demo.sql`.

Projekt stále nemá vlastní Git repository. Nebyl vytvořen commit v
nadřazeném `C:\Work\projects`.

### 11.2 Potvrzené vlastnosti skutečného kódu

- `OrderService.execute` porovnává caller scope s povinným trusted
  `scope_provider` ještě před otevřením DB. Provider se znovu vyhodnotí před
  každým retry; změna oprávnění tedy nepoužije starý scope.
- `_assert_lab_guard` před první business transakcí ověřuje LAB environment,
  nakonfigurovaný loopback host, prefix a přesnou shodu DB jmen, skutečnou
  loopback server address a PostgreSQL `system_identifier`.
- `_execute_once` drží core writes, postconditions, finance a všechny audity
  v jediném `connection.transaction()`.
- `_apply_transition` používá návrat plus/minus pouze diagnosticky.
  Rozhodující je přesný post-read stavu, `poradiprihl`, ceny a počtu.
- `_order_rows` nepoužívá neurčitý `LIMIT 1`; duplicita i chybějící pilotní
  row jsou fail closed.
- `monthly_advisory_key` je deterministický, bezkolizní pro podporované
  kombinace PostgreSQL integer `evidcislo` a `YYYYMM` a bezpečně se vejde do
  `bigint`.
- Strict config lock zůstává výchozí a skutečně blokuje config DML.
- `deadline_fields` odpovídá source mapování add/change/delete,
  `assert_deadline` zachovává minimální kalendářní offset, první varný den a
  strict `<`.
- `exact_menu_available` kontroluje konkrétní menu přes
  `jidelnicek -> menustravy -> typstrj.oznaceni`.
- `_price` používá `Decimal`, při `PouzivatCenik=0` porovnává `dej_sazbu`
  proti `getcenamenuden` a finanční postconditions ověřují per-type i
  souhrnnou realitu.
- A→B/C/D plánuje všechny skutečně objednané konflikty na `N`, po každém
  minusu ověří stav a teprve potom provede cílový plus. Funkce
  `public.aplikujspolusvyloucenos` se nevolá.
- Audit se provádí až po business a finanční revalidaci, ale před commit.
  A→B/C/D má dva eventy a menu change jeden `old->new` event.

Rozdíl proti `objednavkaNG`, že prosté `menu_delete` nemaže
`vyloucenos`, je záměrný podle schváleného kontraktu FÁZE 1A. Před produkcí
zůstává nutné toto business rozhodnutí potvrdit; review jej svévolně
nezměnilo.

### 11.3 Nalezené chyby a provedené opravy

1. Business timezone nebyla připnutá. `OrderServiceSettings` nyní povinně
   přijímá `business_timezone`; `configure_transaction` před business časem
   nastaví a ověří transakční `TimeZone`. LAB používá `Europe/Prague`.
2. `scope_provider` se původně vyhodnotil jen před retry smyčkou. Nyní se
   autorizace opakuje před každým novým pokusem.
3. `public.pouzivatcenik()` mapuje chybějící nebo neznámou hodnotu na
   `false`. Repository nyní vyžaduje právě jeden
   `BACKUP/PouzivatCenik` řádek, hodnotu přesně `0` nebo `1` a shodu s DB
   funkcí.
4. `prihlas.cena` a `prihlas.pocet` se při `NULL` normalizovaly na nulu.
   Obě hodnoty jsou nyní fail closed; source-defined NULL→0 zůstává jen u
   kreditních komponent.
5. `OrderResult` neodpovídal schválenému veřejnému kontraktu. Nyní obsahuje
   `success=true` a `committed_transitions`.
6. Přímý A→D integrační důkaz chyběl. Parametrizovaný test nyní pokrývá
   B, C i D.

Po opravách nezávislá statická kontrola nenašla další P1/P2 chybu v samotné
JLL write cestě.

### 11.4 Nové review testy

Byly přidány nebo zpřesněny testy:

- deadline 1 ms před limitem, přesně na limitu a 1 ms po limitu;
- action-specific deadline fields;
- advisory klíč na mezích PostgreSQL integer a roku 1/9999;
- změna trusted scope mezi retry pokusy;
- skutečné přepsání počáteční session timezone `UTC` na `Europe/Prague`;
- chybějící, NULL a neznámý `PouzivatCenik`;
- NULL `prihlas.cena` a `prihlas.pocet`;
- A→D a přesný počet auditních eventů pro variant change/menu change;
- audit 1 skutečně vložený, audit 2 vrátí false nebo vyhodí exception:
  business, finance i audit 1 se rollbacknou;
- tři deterministicky synchronizované JLL↔legacy mixed-writer scénáře.

Mixed-writer helper nečeká naslepo. Observer ověří, že legacy backend:

- skutečně čeká na `Lock`;
- je blokován přesným JLL backend PID;
- nedrží žádný advisory lock.

Teprve potom je JLL transakce uvolněna.

### 11.5 JLL↔legacy mixed-writer výsledek

Výsledek je **FAIL – PRODUKČNÍ BLOCKER**.

Session A používala normální JLL service. Session B nepoužila JLL service
ani advisory lock a volala přímo legacy core:

1. Stejný den, oba `objednavka_plus`: výsledný `prihlas` byl správně jen
   jednou `1`, cena 88 a počet 1, ale `platittm+platitpm` vzrostl na 176 a
   `penden` obsahoval dvě změny celkem -176.
2. Jiný den stejného měsíce: po JLL add dne 10 a legacy add dne 11 skončil
   měsíční řetězec `d10=S, d11=1`; JLL objednávka dne 10 byla ztracena.
   Finance přitom obsahovaly oba pohyby 176/-176.
3. JLL A→B proti legacy A→C skončilo
   `A=N, B=1, C=1, D=S`, tedy porušením exkluzivity.

Příčina je v legacy/core orchestrace: celý měsíční stav a finanční delta se
spočítají před blokujícím update. Standardní JLL row lock legacy writer
pozdrží, ale po odblokování ho nedonutí zopakovat preflight nad novým stavem.

Tento problém nelze spolehlivě opravit pouze klientskou změnou JLL. Před
produkčním souběhem je nutný společný serverový write protokol, úprava všech
writerů, nebo provozní vyloučení legacy objednávkových zápisů.

Tři bezpečnostní oracly zůstávají `strict XFAIL`. Jejich invariants musí být
po serverové/mixed-writer opravě splněny; neočekávaný `XPASS` proto shodí
test suite a vynutí nové vyhodnocení gate.

### 11.6 Finální nezávislý test run

Po fresh restore `zdroje/demo.sql -> jll_demo_lab` byly skutečně spuštěny:

```text
python -m compileall -q src tests
tools/run_lab_tests.ps1
```

Výsledek:

```text
78 collected
75 passed
3 strict xfailed – pouze potvrzené mixed-writer produkční blockery

Unit: 39/39 PASS
PostgreSQL integration: 36/39 PASS, 3/39 strict XFAIL
```

Strict config lock test znovu prošel s reálným SQLSTATE `55P03` souběžného
admin DML. Samostatný review smoke vzorek po všech opravách:

```text
advisory_lock_wait_ms=0.404
config_lock_wait_ms=0.556
transaction_ms=529.250
business_timezone=Europe/Prague
```

Měřicí DB i všechny `jll_test_*` databáze byly odstraněny. Zůstala pouze
čistě obnovená lokální šablona `jll_demo_lab`.

### 11.7 Produkční blokery a GUI gate

Produkční blockery:

1. JLL nesmí v produkci souběžně zapisovat objednávky s legacy writery,
   dokud nebude zaveden společný serverový lock/revalidation protokol nebo
   provozní vzájemné vyloučení.
2. Produkční GUI/session vrstva musí dodat skutečný trusted
   `scope_provider`; `OrderCommand.allowed_categories` je redundantní
   obranný údaj a v budoucím veřejném GUI API je vhodné jej vůbec
   nepřijímat.
3. Před produkcí potvrdit schválenou odchylku, že prostý `menu_delete`
   nemaže typy z `vyloucenos`.

Tyto body nebrání první **LAB GUI integraci** s jediným JLL writerem.
Produkční deployment ani smíšený provoz povolen není.

### 11.8 Závěrečný gate FÁZE 1C

```text
Code review skutečné implementace dokončen: ANO

LAB guard ověřen v kódu: ANO
Category scope bez bypassu: ANO
Transakční atomicita ověřena: ANO
Business failure rollback ověřen: ANO
Post-write revalidace ověřena: ANO
Locking ověřen: ANO
Finance ověřeny: ANO
Audit ověřen: ANO
A→B/C/D ověřeno: ANO

JLL↔JLL concurrency: PASS
JLL↔legacy mixed-writer concurrency: FAIL

Unit testy:
39/39

PostgreSQL integration:
36/39 PASS; 3/39 strict XFAIL potvrzují mixed-writer blocker

Nalezené kritické chyby:
časová zóna nebyla připnutá – OPRAVENO

Produkční blokery:
JLL↔legacy souběh po čekání používá stale měsíční stav a může způsobit
lost update, duplicitní finance nebo porušení exkluzivity.

Backend připraven pro první GUI integraci: ANO
```

Toto `ANO` platí pouze pro LAB GUI integraci bez legacy writeru. Není
souhlasem s produkčním připojením, release ani deploymentem.

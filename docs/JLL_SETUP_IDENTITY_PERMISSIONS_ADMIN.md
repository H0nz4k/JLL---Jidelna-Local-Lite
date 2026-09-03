# JLL – Setup, identita, permissions a administrace

## 1. Rozsah FÁZE 2B

Tato implementace vytváří LAB foundation pro:

- fail-closed first-run Setup Wizard;
- konkrétní JLL uživatele s Argon2id PIN hash;
- login a časově omezené pokusy;
- dynamickou session policy;
- jednoznačný `ActorContext`;
- administraci uživatelů a permissions po PIN reauth;
- lokální strukturovaný administrační audit.

Nejde ještě o produkční identity server. Produkční scope enforcement, centrální
policy/audit a recovery administrátora zůstávají otevřená architektonická
rozhodnutí.

## 2. Oddělené identity

Instalační konfigurace `config/lab.json` obsahuje:

```text
site_id
site_name
instance_id
DB host/port/name/user
expected_system_identifier
allowed_categories
```

Neobsahuje DB heslo, PIN hash ani user permissions.

Lokální identity jsou v runtime souboru `config/users.lab.json`, který je
ignorován Gitem. PIN je uložen pouze jako salted Argon2id hash. DB heslo
ukládá Setup Wizard přes systémový `keyring` (na Windows Credential Manager)
pod klíčem:

```text
JidelnaLocalLite / <instance_id>:<db_user>
```

Environment variable `JLL_LAB_DB_PASSWORD` zůstává LAB alternativou.

## 3. First-run Setup Wizard

Pokud chybí platný identity store, aplikace otevře sedm kroků:

1. databáze a read-only test spojení;
2. provozovna / stabilní instance;
3. DB-načtené povolené kategorie;
4. první administrátor;
5. volitelný běžný uživatel;
6. konkrétní permissions;
7. souhrn.

Wizard povoluje pouze loopback host, databázi `jll_*`, ověřenou skutečnou
loopback adresu a ukládá skutečný PostgreSQL `system_identifier`. Prázdný
scope, neověřená DB, chybějící admin nebo neplatný PIN znamenají fail closed.

Pokud identity již existují, ale instalační config je poškozený, wizard jej
automaticky nepřepíše. Aplikace se zablokuje, aby neztratila vazbu na
existující identity a audit.

## 4. Login a session

Po setupu se vždy zobrazí login:

```text
JidelnaLocalLite – <provozovna>
Uživatel: <konkrétní aktivní JLL uživatel>
PIN: ****
```

Pět neúspěšných pokusů během 60 sekund dočasně zablokuje další pokusy pro
dané user ID. Chyba je záměrně generická.

Aktivní session obsahuje:

```text
user_id
session_id
login_time
site_id
instance_id
short_code
client_version
```

Backend načítá aktuální user policy z identity store při každém aplikačním
volání. Deaktivace nebo změna permissions se proto projeví bez restartu.

## 5. ActorContext a objednávkový audit

`OrderApplicationService` již nepoužívá konstantního actora. Každý
`OrderCommand` dostává actor ze session:

```text
<instance_id>:<short_code>
```

Příklad:

```text
DEMO-LAB01:VED
```

Formát je validován vůči délce `public.udalosti.uzivatel`. Actor,
`allowed_categories` a `client_version` nevyrábí GUI.

## 6. Permissions

Implementované permission názvy zahrnují:

```text
diners.*
chips.*
orders.*
pickup_status.view
reports.*
admin.users
admin.permissions
admin.categories
admin.database
admin.instance
admin.audit
admin.reader
```

GUI podle policy akce skryje nebo deaktivuje, ale backendová service/session
vrstva permission znovu ověří. `orders.change` je ověřeno také v
`OrderService.scope_provider` před každým retry.

## 7. Administrace

Vstup do administrace vyžaduje:

```text
admin.users
+
opětovné zadání PINu aktuálního uživatele
```

Reauth platí maximálně pět minut. Funkční jsou:

- seznam aktivních i deaktivovaných uživatelů;
- vytvoření nového lokálního JLL uživatele;
- atomická změna active + permissions;
- ochrana posledního aktivního administrátora;
- lokální audit změn;
- read-only přehled provozovny, DB a scope.
- diagnostika explicitně nakonfigurované čtečky po kontrole `admin.reader`;
  poslední načtení je maskované.

Změna DB, instance nebo rozšíření `allowed_categories` není v této fázi
aktivní. UI ji výslovně označuje jako nedostupnou, protože vyžaduje další
ověřený bezpečnostní workflow.

Uživatelé se nemažou; pouze deaktivují.

## 8. Audit

Identity store obsahuje atomicky ukládané strukturované události:

```text
timestamp
actor
action
target
result
```

PIN ani hash se do auditní události nekopíruje. Tento lokální audit je pouze
LAB foundation. Produkce vyžaduje schválený centrální audit store.

## 9. Spuštění v Git Bash

Primární příkazy:

```bash
./tools/run_jll_lab.sh
./tools/run_lab_tests.sh
```

Pouze ověření GUI targetu:

```bash
./tools/run_jll_lab.sh --probe-only
```

Destruktivní restore je záměrně fail closed:

```bash
export JLL_LAB_SYSTEM_IDENTIFIER='<ověřená hodnota>'
export JLL_CONFIRM_FRESH_RESTORE=YES
./tools/restore_demo_lab.sh
```

Restore se nesmí spouštět bez předem ověřeného targetu a explicitního
potvrzení. PowerShell utility zůstávají pouze sekundární kompatibilní
varianta.

## 10. Známé produkční blokery

- lokální JSON není server-side security boundary;
- Windows ACL hardening a recovery admina potřebují instalační workflow;
- produkční users/permissions/admin audit nemají schválené centrální schema;
- změna DB/scope/instance v Admin UI je úmyslně read-only;
- technická konfigurace readeru je zatím read-only v `lab.json`; port se
  nesmí automaticky vybírat bez ověření fyzického zařízení;
- JLL↔legacy mixed-writer concurrency zůstává produkční write blocker;
- produkční připojení není povoleno.

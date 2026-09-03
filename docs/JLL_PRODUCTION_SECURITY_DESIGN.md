# JLL produkční security design

Stav: **NÁVRH – žádný production deploy ani write nebyl proveden**

## Autoritativní identity, policy a audit

Lokální JSON `IdentityStore` je vhodný pro LAB foundation, ne pro produkční
autoritu. Produkce potřebuje centrální store s:

- stabilní identitou uživatele, instance a provozovny;
- Argon2id/verifikovaným externím identity providerem;
- revokací session, lockoutem a rotací;
- serverově vydanou efektivní policy;
- append-only audit logem s actor, request/correlation ID, před/po stavem a
  DB transakcí;
- odděleným recovery administrátorem a auditovaným break-glass postupem.

GUI smí policy použít pro UX, ale nesmí být autoritou.

## Server-side `allowed_categories`

Preferovaný model je DB role pro konkrétní site bez přímého přístupu k
business tabulkám. Povolené kategorie jsou serverová data svázaná s
autentizovanou session/rolí.

Možné varianty:

1. security-definer API funkce s pevným `search_path`, explicitní validací
   site/actor/scope a revokovaným přímým DML;
2. security-barrier views pro reads a security-definer funkce pro writes;
3. RLS, pokud lze spolehlivě svázat každé spojení s nezfalšovatelným site
   kontextem a zabránit bypass rolím.

Pouhý parametr `allowed_categories` od klienta není bezpečnostní hranice.
Connection pool musí session kontext čistit a znovu nastavit při každém
checkoutu.

## Mixed-writer protokol

Stávající produkční blocker `JLL ↔ legacy mixed-writer concurrency = FAIL`
trvá. Advisory lock používaný pouze JLL nechrání před legacy writerem.

Řešení vyžaduje, aby všichni writeři používali společný serverový protokol:

- jednu autoritativní stored procedure pro každou business operaci;
- společný lock key a pořadí locků;
- preflight pod lockem;
- write a audit v jedné transakci;
- post-write revalidaci;
- idempotency/request ID;
- jednoznačný konfliktní výsledek.

Pokud legacy zůstane u přímých `INSERT/UPDATE`, musí kompatibilní pravidla
vynutit DB trigger/constraint. U pravidel, která trigger bezpečně vyjádřit
nemůže, nelze souběžný produkční write povolit. Strict XFAIL oracles se
nesmějí odstranit; odblokování vyžaduje jejich skutečný PASS proti oběma
writerům.

## Recovery a provoz

- oddělit per-site DB credentials a minimální grants;
- hesla ukládat v OS credential store, nikdy v config/logu;
- auditovat změny policy, kategorií, DB role i reader konfigurace;
- mít testovaný restore, revokaci kompromitované instance a obnovu posledního
  administrátora;
- release povolit až po kontraktních, concurrency, scope-leak a recovery
  testech.

Tento dokument neopravňuje production připojení. Aktuální aplikace zůstává
uzamčena na loopback `jll_*` LAB DB a ověřený lokální cluster.

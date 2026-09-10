# JLL – Jídelna Lokal Lite

**Verze `0.6.2` — první produkční Windows release** (Flet desktop, UNSIGNED).

Lokální Windows aplikace pro **hospodářku jídelny**.

Připojuje se k existující databázi **JídelnaSQL** (PostgreSQL) a slouží ke
správě strávníků, přihlášek / odhlášek, čipů, plateb a sestav na konkrétní
stanici.

**Není** výdejní terminál, web ani náhrada celého JídelnaSQL.

Aktuální instalátor:

```text
dist/release/0.6.2/JidelnaLocalLite-0.6.2-Setup.exe
```

Co ještě zbývá dodělat: [docs/TODO.md](docs/TODO.md)

---

## Co umí (stručně)

- najít strávníka (jméno, ev. číslo, čip / ELATEC čtečka)
- zobrazit kredit, kategorii a přihlášky
- měnit přihlášky a odhlášky
- spravovat čipy (záloha 0 Kč)
- manuální (ne-hotovostní) platby
- sestavy a základní administraci (kategorie, čtečka, typografie, reset)
- first-run setup wizard (DB → stanice → kategorie → SUP)

Výchozí provoz: po nastavení běží pod operátorem **VED** (bez PINu).
Administrace vyžaduje heslo **SUP**.

---

## Požadavky před instalací

1. Windows 10/11 (64bit)
2. Běžící PostgreSQL s databází JídelnaSQL (typicky na stejném PC)
3. Účet DB s právy pro čtení/zápis do provozních tabulek
4. Instalátor `JidelnaLocalLite-0.6.2-Setup.exe`

> Instalátor je **nepodepsaný** (UNSIGNED BY DESIGN). Windows / SmartScreen
> může zobrazit varování — při důvěryhodném zdroji pokračujte přes
> „Další informace“ → „Přesto spustit“.

---

## Instalace

1. Spusťte `JidelnaLocalLite-*-Setup.exe`.
2. Dokončete průvodce instalací.
3. Aplikace se nainstaluje do:
   ```text
   C:\Gastro\JidelnaLocalLite\
   ```
4. Spusťte **JLL** (Start menu / zástupce).

### První spuštění (setup wizard)

Při prvním startu (nebo po resetu nastavení) projděte kroky:

1. **Databáze** — host, port, název DB, heslo → *Otestovat spojení*
2. **Provozovna a stanice** — název provozovny + výběr stanice
3. **Povolené kategorie** — vyberte jen kategorie pro tuto stanici  
   (seznam jde scrollovat)
4. **SUP heslo** — heslo administrátora
5. **Souhrn** → *Dokončit*

Poté se otevře hlavní aplikace.

---

## Kde se ukládá nastavení

Nastavení **není** ve složce `C:\Gastro\...`, ale zde:

```text
C:\ProgramData\JidelnaLocalLite\
  config\     jll.json, users.json, …
  logs\       jll.log
  reset-backups\
```

Heslo k databázi je v **Windows Credential Manager** (služba `JidelnaLocalLite`).

> Odinstalace aplikace **defaultně nemaže** `ProgramData`.  
> Pro úplně čistý first-run smažte (nebo přejmenujte) složku
> `C:\ProgramData\JidelnaLocalLite` a případně související záznamy
> ve Správci pověření.

---

## Upgrade / přeinstalace

1. Nainstalujte novější Setup.exe (může přepsat `C:\Gastro\JidelnaLocalLite`).
2. Config v `ProgramData` zůstane — wizard se znovu nespustí.
3. V seznamu *Nainstalované aplikace* uvidíte např. **JLL 0.6.2**.

Čistý průchod wizardem znovu: smažte `ProgramData\JidelnaLocalLite`
(nebo použijte obnovení počátečního nastavení v administraci).

---

## Odinstalace

Ovládací panely / *Nainstalované aplikace* → položka **JLL** s číslem verze → Odinstalovat.
Nebo `unins000.exe` ve složce instalace.

Databáze JídelnaSQL se **nemaže**.

---

## Pro vývojáře

Technický přehled: [docs/JLL_KOLEGA_OVERVIEW.md](docs/JLL_KOLEGA_OVERVIEW.md)  
Zbývající práce: [docs/TODO.md](docs/TODO.md)  
Index dokumentace: [docs/README.md](docs/README.md)

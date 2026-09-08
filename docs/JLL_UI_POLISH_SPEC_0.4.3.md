# JLL UI Polish Spec 0.4.3

Stav: **IMPLEMENTACE**  
Primární shell: Flet desktop  
Business behavior: **NONE** (UI layout only; ruční odběr bez časového okna zůstává z předchozího explicitního požadavku v této větvi)

## Problémy

1. `expand=True` roztahuje krátké info/form bloky přes celý monitor.
2. Karta strávníka: jméno/kredit/akce/chip operace v nepřehledné šířce.
3. Chip lifecycle akce trvale na hlavním povrchu karty.
4. Empty detail = obrovský bordered panel s malým textem.
5. Administrace: full-width content card i pro Kategorie/Vzhled/Čtečka.
6. Uživatelé/Oprávnění: jméno vlevo, akce na pravém kraji okna.
7. Vzhled: interní názvy textových rolí v user-facing copy.

## Layout principles

- Default: **intrinsic / content-driven width**.
- Full-width jen u datových ploch (měsíční mřížka, dlouhé seznamy, pracovní tabulky).
- Prázdné místo kolem kompaktního bloku je OK.
- Zachovat barvy, font, 4 textové role, text scale 100/115/130/150 %.
- Content cards: preferovat 1px subtle border; silný 2px border jen u datových panelů (seznam strávníků, mřížka).

## Before → after

| Plocha | Before | After |
|--------|--------|-------|
| Diner header | jméno↔kredit daleko, chip row trvale | 3 řádky: jméno+kredit · meta+čip · hlavní tlačítka |
| Chip ops | Přidělit…Ztracený na kartě | jen v Detail čipu modalu |
| Empty detail | bordered expand panel | workspace bg + malý empty block |
| Admin body | bordered expand full width | left-aligned content width per sekce |
| Users/Perms | name expand → akce na pravém kraji | kompaktní sloupce |
| Appearance | „Role: PRIMARY…“ | procenta + neutrální popis |

## Diner 3-row header

```text
Row1: Jméno + Kredit (tight, gap ~24px, wrap)
Row2: třída · ev. N · Čip CODE | Bez čipu
Row3: [Upravit] [Detail čipu] [Ruční odběr] [+ Nový]
```

- Ruční odběr = Filled; ostatní Outlined.
- Chip action row odstraněn z hlavní karty.
- Month grid / menu / payments beze změny business logiky, grid zůstává full-width.

## Chip modal

Šířka cca 560–640 px.

```text
Čip / Stav / Držitel / Historie (scroll)
Relevantní akce dle status_code + permission + write gate:
  bez čipu → Přidělit
  P → Vrátit, Blokovat, Ztracený
  B → Odblokovat
```

Deposit>0 fail-closed zůstává ve službě.

## Empty state

Detail Column bez silného bordered expand panelu. Levý seznam zůstává panel.

## Admin width matrix

| Sekce | Cílová šířka |
|-------|----------------|
| Kategorie | 560 |
| Vzhled | 680 |
| Čtečka | 720 |
| Info | 760 |
| Uživatelé | 980 |
| Oprávnění | 980 |

Na úzkém okně shrink na dostupnou šířku (`min(target, available)` prakticky přes fixed width + scroll parent).

Active nav: `accent_soft` background + left accent marker.

## `expand=True` audit (Flet UI)

| Výskyt | Verdikt |
|--------|---------|
| `app_shell` body/header brand | NECESSARY |
| diner `ListView` / root Row / detail scroll area | NECESSARY (workspace) |
| diner header name `expand=True` | UNNECESSARY → remove |
| diner detail `_panel(expand=True)` empty | UNNECESSARY → soft empty |
| admin body `Container(expand=True)` full card | UNNECESSARY → content width |
| admin users/perms name `expand=True` | UNNECESSARY → column widths |
| reports/serving content expand scroll | NECESSARY (scroll host); content already width-capped |
| setup body | NECESSARY (wizard host) |

## Typography follow-up (0.4.4)

Od 0.4.4 platí tvrdé 4-role API (`docs/JLL_TYPOGRAPHY_SYSTEM_0.4.4.md`):
size + weight + font family jen přes `theme.role_*`. Layout polish 0.4.3
zůstává; typografie je oddělený kontrakt.

## Out of scope

- Redesign Stav výdeje / Sestavy (už kompaktní).
- Shell/navigation redesign.
- Business/payment/ELATEC/order/serving write contracts (mimo dříve schválené UI/odběr změny).

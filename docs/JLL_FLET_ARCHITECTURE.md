# JLL Flet Architecture

Cílová prezentační vrstva JidelnaLocalLite je **Flet** (Flutter-rendered desktop).

```text
PostgreSQL / legacy JídelnaSQL DB
            │
            ▼
JLL repositories / services / policies / write gates
            │
            ├── PySide6 GUI (referenční / fallback)  → tools/run_jll_lab.sh
            │
            └── Flet GUI (cíl)                       → tools/run_jll_flet_lab.sh
```

## Principy

- Flet UI neobsahuje SQL, finance, order/chip rules ani obcházení permissions/write gates.
- Business identita = `public.uzivatel.uzivatel` (VED, KUCH, …).
- Default start = **VED** bez PINu/loginu.
- **SUP** admin heslo se nastavuje při prvním spuštění (JLL secret ≠ DB `heslo`).
- Nový běžný uživatel: insert do `public.uzivatel` s `heslo=''`, unikátní
  `id` (`test_new_user_id`), `prava`/`prava1`/`typ` + `user_role` z VED;
  JLL permissions = kopie VED. Zvolený operátor ≠ strong-auth identity.
- Kalendář: `today` ze serveru; AM z `TentoMesic`/`TentoRok` (ne `denobjednavky`).
- Flet provozní `BusinessSession`: `bypass_order_deadlines` — standardní
  termíny přihlášek neplatí (ne jen kód VED).

## Balík

```text
src/jll/flet_ui/
  app.py            – entrypoint + wiring + SUP modal pro Administraci
  theme.py          – 4 typography roles + scale + block borders
  state.py          – AppState + permission/gate helpers
  routes.py
  components/       – shell (top nav), dialogs, badges
  screens/          – diners, serving, reports, admin, setup
  viewmodels/       – tenké adaptéry nad services
```

## UX poznámky (0.2.1)

- Horní menu; Strávníci: search autofocus, ↑/↓/Enter, čtečka na pozadí.
- Sestavy: záložky + filtr dne + Náhled/Export.
- Stav výdeje: velké počty v kartách.
- Administrace: nejdřív SUP modal, pak obsah; Info = DB+Stanice+Audit.
- Velikost textu přes `role_size`/`scaled` (ne zoom okna); sloupec „dnes“
  jen u skutečného serverového dneška; typy stravy bez sazby kategorie
  se v mřížce nezobrazují.

## Setup / reset

1. `./tools/run_jll_flet_lab.sh` – desktop window
2. Setup: DB → provozovna/stanice → kategorie → SUP heslo → souhrn
3. `./tools/reset_jll_first_run.sh --dry-run` / `--yes` – maže jen lokální first-run artefakty

## Identity

- `jll.legacy_users` – read/list + bezpečný create kontrakt
- `jll.sup_secret` – Argon2id SUP secret (keyring + file fallback)
- `jll.business_session` – VED bootstrap, switch user, SUP unlock, create user

## Package

Experimentální `flet pack` / `flet build windows` může chybět toolchain →
`PACKAGE=PARTIAL`. Primární běh je vývojový desktop přes `run_jll_flet_lab.sh`.

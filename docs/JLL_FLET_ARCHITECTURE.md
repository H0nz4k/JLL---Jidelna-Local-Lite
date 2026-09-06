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
- **SUP** admin heslo se nastavuje při prvním spuštění (JLL secret ≠ DB `heslo`, pokud není doložena kompatibilita).
- Nový běžný uživatel: insert do `public.uzivatel` s `heslo=''`, `prava`/`prava1`/`typ` z VED; JLL permissions = kopie VED.

## Balík

```text
src/jll/flet_ui/
  app.py            – entrypoint + wiring services
  theme.py          – 4 typography roles + scale
  state.py          – AppState + permission/gate helpers
  routes.py
  components/       – shell, nav, dialogs, badges
  screens/          – diners, serving, reports, admin, setup
  viewmodels/       – tenké adaptéry nad services
```

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

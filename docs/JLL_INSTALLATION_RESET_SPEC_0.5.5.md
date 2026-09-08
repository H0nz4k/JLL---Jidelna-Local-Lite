# JLL Installation Reset / First-run restart (0.5.5)

> Prompt file targeted `0.5.4`, but canonical `0.5.4` already shipped the order
> relation applicability fix. This feature is released as **0.5.5**.

## Purpose

Administrace → Info → **Obnovit počáteční nastavení** safely forgets *local*
JLL install state and re-enters the **same** existing first-run wizard
(`SetupScreen` / `SetupViewModel`).

Info layout (0.5.6+): reset block stays near the top (after Databáze/Stanice);
changelog opens via **Zobrazit changelog** modal so growing version history
does not push the reset action down.

## Reset scope (local only)

May remove/clear:

- active `config_path` (default `config/lab.json`)
- active `identity_path` (default `config/users.lab.json`)
- typography/reader/categories embedded in that config
- keyring DB credential `JidelnaLocalLite` / `{instance_id}:{db_user}`
- SUP secret keyring `jll-sup:{instance_id}` and fallback `config/secrets/sup.{instance}.hash`
- in-memory pool/services/session/chip listener

## Explicit non-scope (never touched)

- PostgreSQL business data (`stravnik`, `prihlas`, `cipy`, `penden`, …)
- `public.uzivatel`
- application binaries / `.venv` / git checkout
- `logs/`

## Backup contract

Before deleting active files:

```text
{config_parent}/reset-backups/{YYYY-MM-DD_HH-MM-SS}/
  lab.json | custom config name
  users.lab.json | custom identity name
  manifest.json   # no plaintext secrets
  secrets/sup.*.hash  # hash file only, if present
```

Backup failure → abort, active files untouched.

## SUP reauth

Requires fresh SUP password verify (`SupSecretStore.verify`), not merely
`sup_unlocked()` session flag.

## Runtime quiesce

Stop chip listen, dispose diner screen, close pool, clear AppState services,
reset typography to `DEFAULT_TYPOGRAPHY`, then `_show_setup()`.

## First-run reuse

No second wizard. Post-reset uses `FletAppController.enter_first_run()` →
existing `SetupScreen`.

## Custom paths

Uses `state.config_path` / `state.identity_path` from CLI `--config` /
`--identity-store`.

## Rollback

If file removal/credential clear fails after backup, service attempts to copy
config/identity back from backup. Credential rollback is not always possible;
UI reports service-check message with backup path.

## Tests

- `tests/unit/test_installation_reset.py`
- `tests/unit/test_installation_reset_ui.py`

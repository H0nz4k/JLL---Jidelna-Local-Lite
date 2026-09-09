# Production identity gap — 0.6.0

Stav: **PARTIAL** — VED+SUP first-run je funkční ve Flet setupu; create-user
production zůstává fail-closed přes write policy.

## Schválený model

- business users: `public.uzivatel`
- default operator: `VED`
- admin: `SUP` + JLL re-auth secret (`SupSecretStore`)
- žádná PIN product terminology v aktivním Flet UI
- JLL permissions = vlastní policy vrstva

## Co setup nyní dělá

| Krok | LAB | PRODUCTION |
| --- | --- | --- |
| Mode výběr | loopback + `jll_` | hostname/IP |
| System ID pin | ano | ano |
| Password | keyring (env LAB fallback) | keyring only, fail-closed |
| VED | musí existovat v `uzivatel` | stejně; jinak fail-closed |
| SUP | Argon2 secret | stejně |
| environment | `lab` | `production` |

## Zbývající mezery

- Production create business user: write policy BLOCKED, dokud není dedicated
  production PROVEN kontrakt.
- PySide legacy dialogy stále obsahují PIN texty (reference only).
- Installation reset SUP reauth: existuje ve Flet Admin flow.

# Production identity gap — 0.6.0

Stav: **PARTIAL / audit only** (neblokuje Flet runtime switch, blokuje
podepsaný production DONE).

## Schválený model (cíl)

- business uživatelé: `public.uzivatel`
- default operator: `VED`
- admin: `SUP` + vlastní JLL admin secret / re-auth
- žádná PIN product terminology
- JLL permissions = vlastní policy vrstva

## Aktuální Flet/PySide stav

| Oblast | Stav | Poznámka |
| --- | --- | --- |
| IdentityStore (lokální JSON) | existuje | setup wizard „první administrátor“ |
| SUP re-auth | částečně | Flet Admin SUP dialog |
| VED default session | částečně | BusinessSession |
| public.uzivatel create | LAB služby | production write policy zatím demotes |
| PIN terminology | audit potřeba | legacy UI texty |

Dokud VED/SUP model není end-to-end v production first-run, identity
contract zůstává **BLOCKED** pro finální signed release.

# JLL – zbývající TODO (po 0.6.2)

Stav k **0.6.2** = **první produkční Windows release** (Flet, UNSIGNED).  
Tento seznam je backlog po vydání; neblokuje základní provoz hospodářky.

Priorita: **P0** = brzy / provozní bolest · **P1** = důležité · **P2** = později

---

## P0 – provoz a release hygiena

- [ ] Ověřit 0.6.2 na reálné zákaznické DB (clean first-run + denní smoke: strávník, přihláška, čip, sestava)
- [ ] Zaznamenat výsledek do `docs/RELEASE_VALIDATION_*.md` (aktualizovat z 0.6.0 na 0.6.2)
- [ ] Rozhodnout o git tagu `v0.6.2` a merge release větve do `main` / `release/*`
- [ ] Volitelně: Authenticode signing (dnes **UNSIGNED BY DESIGN** → SmartScreen riziko)

## P1 – funkce stále BLOCKED / nedokončené

- [ ] **Změna kategorie strávníka** (`diner.category_change`) — dnes fail-closed
- [ ] **Hotovostní platba / doklad** (`cash_payment`, `uctenky_kasy`) — BLOCKED
- [ ] **Refund** — BLOCKED
- [ ] **Záloha za čip > 0 Kč** (hotovostní deposit path) — BLOCKED; 0 Kč funguje
- [ ] **Homebanking vazba** — BLOCKED
- [ ] **Převod čipu** (`chip transfer`) — BLOCKED
- [ ] **Výdej `record_pickup` v production** — mutual exclusion / coexistence; dnes doporučeně BLOCKED
- [ ] **Zakládání business uživatele v production** (`uzivatel` create) — identity gap, fail-closed

## P1 – multi-writer / bezpečnost dat

- [ ] Snížit residual riziko cizího stale month overwrite (plná prevence bez změny ostatních writerů **není možná**; zvážit provozní pravidla / dokumentaci pro kolegy)
- [ ] Doplnit coexistence oracles u diner create/edit a chip writes (dnes PARTIAL)

## P2 – UX / balení / provoz

- [ ] Auto-update / kanál distribuce nových Setup.exe
- [ ] Volba při odinstalaci: smazat i `ProgramData` (dnes zůstává záměrně)
- [ ] SmartScreen reputace / EV cert po nasazení
- [ ] Dočištění LAB vs production UI copy (bannery, texty)
- [ ] PySide6 legacy GUI: držet jen jako referenci, nebo explicitně označit deprecated
- [ ] PDF / kolegovský balíček release notes k 0.6.2

## Hotovo v 0.6.x (pro orientaci)

- Windows installer + ProgramData layout
- First-run wizard včetně výběru kategorií + scroll
- `UninstallDisplayName` = `JLL <verze>`
- Production write gates ve Flet UI
- Multi-writer detection u objednávek (intent, stale, settle)
- Installation reset (SUP reauth)
- ELATEC auto-detekce

---

Zdroje detailů:  
`docs/PRODUCTION_WRITE_READINESS_0.5.8.md`,  
`docs/PRODUCTION_IDENTITY_GAP_0.6.0.md`,  
`docs/MULTI_WRITER_COEXISTENCE_0.5.8.md`

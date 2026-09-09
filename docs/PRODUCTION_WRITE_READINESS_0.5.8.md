# Production write readiness (0.5.8)

Prostředí: coexistence s nemodifikovaným JidelnaSQL / e‑jídelníčkem.

`write_gates.py` „PROVEN“ historicky často znamená **LAB / JLL-only**.
Tato matice je **production multi-writer** pohled.

| Operace | LAB gate | Production coexistence | Poznámka |
| --- | --- | --- | --- |
| `orders.change` | (permission + LAB guard) | **PARTIAL** | stale-input prevention + post-commit detection PROVEN; cizí stale month overwrite nelze stopnout |
| diner `create` | PROVEN | **PARTIAL** | bez multi-writer oracles |
| diner `edit_personal` | PROVEN | **PARTIAL** | má `expected_updated_dt` |
| diner `category_change` | PARTIAL | **BLOCKED** | neimplementováno |
| chip assign/return/block/lost/unblock | PROVEN | **PARTIAL** | deposit>0 fail-closed |
| chip transfer | BLOCKED | **BLOCKED** | |
| payment `manual_payment` | PROVEN | **PARTIAL** | |
| payment cash/refund/chip deposit/HB | BLOCKED | **BLOCKED** | |
| serving `record_pickup` | PROVEN | **BLOCKED** (prod 0.6 doporučení) | chybí mutual exclusion |
| admin identity JSON | — | **PARTIAL** | lokální soubor |
| admin reader settings | — | **PARTIAL** | lokální config |
| legacy `uzivatel` create | — | **PARTIAL** | |

Pravidlo 0.6.0: operace **BLOCKED** zůstanou ve UI viditelné, ale fail-closed
s lidskou hláškou. Nikdy tiše nepovolovat write jen kvůli LAB PROVEN enumu.

# JLL Typography Editable 0.5.2

Přesně čtyři editovatelné typografické styly v celé Flet aplikaci.

## Role

| Interní | Česky (Vzhled) | Default size | Default bold |
|---------|----------------|-------------:|:------------:|
| PRIMARY | Hlavní nadpis | 28.6 | ano |
| BODY | Běžný text | 19.5 | ne |
| ACTION | Akce a sekce | 18.2 | ano |
| META | Doplňkový text | 16.25 | ne |

Defaulty = efektivní vzhled JLL **0.5.1** při legacy `TextScale.EXTRA_LARGE` (130 %).

Font family (needitable): `Segoe UI`.

Weight contract:

- `bold=false` → `W400`
- `bold=true` → `W700`
- zakázáno: `W500`, `W600` a další intermediate weights

## Persistence

Klíč v `lab.json`:

```json
{
  "typography": {
    "primary": {"size": 28.6, "bold": true},
    "body": {"size": 19.5, "bold": false},
    "action": {"size": 18.2, "bold": true},
    "meta": {"size": 16.25, "bold": false}
  }
}
```

- `typography` je optional; absence → `DEFAULT_TYPOGRAPHY`
- validace: `10.0 <= size <= 40.0`, finite number, `bold` bool
- save je atomic merge do existujícího configu (`jll.typography_settings.save_typography`)

## Migrace z TextScale

V 0.5.1 nebyl `text_scale` persistovaný (jen runtime `AppState`).

Proto:

- žádná fake migrace z disku
- UI presetů 100/115/130/150 % je odstraněno
- legacy enum `TextScale` zůstává jen jako helper `typography_from_legacy_scale` / `theme.role_size(..., scale=)`
- aktivní double scaling (`BASE × scale`) je zrušený: uložená velikost = výsledná velikost

## Administrace → Vzhled

- 4 řádky: velikost + Tučně + live náhled
- `Obnovit výchozí` jen draft
- `Uložit` → validace → persist → `set_typography` → rebuild shell, zůstane Vzhled

## Mapping (stručně)

- shell brand → PRIMARY, verze → META
- HOME: provozovna PRIMARY, datum META, „Dnešní objednávky“ ACTION, meal BODY/META
- buttons → ACTION přes `theme.button_style()`
- forms: value BODY, label/hint META
- dialogy: title PRIMARY, body BODY, actions ACTION

## Forbidden

- ad-hoc `size=` / `weight=` / `font_family=` mimo theme
- uppercase hierarchy hack (`DNEŠNÍ OBJEDNÁVKY`)
- brand-only font
- KPI numeric style mimo role
- badge-specific font size/weight

## Guards

- `tests/unit/test_ui_typography_contract.py` – AST static + button style + runtime signatures ≤ 4
- `tests/unit/test_typography_settings.py` – config/validation/migration helper

## BEFORE / AFTER census

### BEFORE (0.5.1)

- Flet UI `.py`: 28
- model: 4 roles + global TextScale multiplier
- ACTION weight: W600
- default scale: EXTRA_LARGE (130 %), not persisted
- ALL CAPS hierarchy: `DNEŠNÍ OBJEDNÁVKY`
- unique effective signatures at default: 4 (P28.6/W700, B19.5/W400, A18.2/W600, M16.25/W400)

### AFTER (0.5.2)

- Flet UI `.py`: 28 (+ typography_settings module mimo flet_ui)
- model: 4 editable absolute sizes + bold
- ACTION weight: W700 when bold
- no active scale multiplier
- unique signatures at default: 4
- max signatures ever: ≤ 4

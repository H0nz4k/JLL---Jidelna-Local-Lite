# JLL Typography System 0.4.4

Stav: **IMPLEMENTOVÁNO**  
Scope: `src/jll/flet_ui/**` (UI only)

## Proč jen 4 role

Uživatel má okamžitě číst hierarchii:

1. hlavní → PRIMARY  
2. data → BODY  
3. ovládání → ACTION  
4. pomocné → META  

Pátý styl vzniká hlavně ad-hoc `weight` / `size`. To je zakázáno.

## Role matrix

| Role | Size @100% | Weight | Použití |
|------|------------:|-------:|---------|
| PRIMARY | 22 | 700 | brand, název obrazovky, jméno strávníka, dominantní kredit, dialog title |
| BODY | 15 | 400 | seznamy, hodnoty, názvy jídel, řádky sestav |
| ACTION | 14 | 600 | navigace, tlačítka, tabs, sekční nadpisy |
| META | 12.5 | 400 | verze, labely, hinty, densní mřížka, diagnostika |

Font family: **Segoe UI** (globálně přes `theme.FONT_FAMILY`).

## Centrální API

```python
theme.role_size(role)
theme.role_weight(role)
theme.role_style(role, color=...)
theme.text(value, role, ...)
theme.button_style(...)
theme.field_text_size()
theme.field_label_style()
```

## Forbidden combinations

```text
BODY + W600 / W500 / W700
META + W600 / W700
ACTION + W700
numeric size=17 na Text
per-control font_family
```

Selected/active/danger = color / background / border, ne nový weight.

## Forms / dialogs

```text
value = BODY
label/hint/helper = META
dialog title = PRIMARY
dialog actions = ACTION
```

## Scaling

TextScale: 100 / 115 / 130 / 150 %. Default app scale: **130 %** (`EXTRA_LARGE`).

## BEFORE CENSUS

- UI Python files: 26  
- FontWeight-ish usages: 80  
- numeric size/text_size: 1  
- TextStyle/TextSpan constructs: 11  
- per-control font_family: 2 (theme)  
- největší drift: `screens/diners.py`, `screens/admin.py`

## AFTER CENSUS

- direct FontWeight mimo theme: **0**  
- numeric Text size mimo theme: **0**  
- allowlist: `components/navigation.py` `Icon(size=18)` – ikona, ne typografie  

## Static guard

`tests/unit/test_ui_typography_contract.py` – AST kontrola mimo `theme.py`.

# Vývoj JLL

## Prostředí

Primární shell je Git Bash / MINGW64. Utility se píší jako `*.sh`;
`.ps1` je jen sekundární obal.

```bash
py -3.11 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[test]"
```

## Před commitem

```bash
python -m compileall -q src tests
./tools/run_lab_tests.sh
```

Tři mixed-writer `strict xfail` testy musí zůstat xfail. Nový FAIL se
nekomituje, dokud není vysvětlený nebo opravený.

## Dokončená fáze

```text
1. testy
2. CHANGELOG
3. případný version bump
4. commit
5. push
```

## Release

```text
1. kompletní regression
2. version bump v pyproject.toml
3. CHANGELOG
4. commit
5. annotated tag vMAJOR.MINOR.PATCH
6. push main
7. push tag
```

## Pravidla

- Repozitář je veřejný. Necommituj osobní údaje strávníků, DB dumpy,
  logy, screenshoty s daty, hesla, tokeny, PIN hashe ani konkrétní
  zákaznické configy.
- Necommituj generovaná ani runtime data (`logs/`, `.venv/`, cache).
- Neprováděj produkční DB zápisy. Produkční write je blokovaný.
- Operace bez doloženého write kontraktu zůstávají fail-closed přes
  registr v `src/jll/write_gates.py`; změna oprávnění sama zápis nezapíná.
- Business logika patří do service vrstvy, ne do GUI. GUI mapuje pouze
  uživatelský záměr.
- Vzhled se mění jen v `src/jll/gui/theme.py`; žádné lokální
  `setStyleSheet` ani velikosti fontu.
- Chování popsané v `docs/` drž v souladu se skutečnou implementací a
  uváděj jen skutečně spuštěné kontroly.

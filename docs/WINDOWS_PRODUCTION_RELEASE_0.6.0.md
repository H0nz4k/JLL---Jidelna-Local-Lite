# Windows production release — JidelnaLocalLite 0.6.0 (architecture note)

Stav: **Flet production desktop candidate / UNSIGNED**. PySide6 GUI zůstává
v `src/jll/gui` jako referenční/legacy; **není** release target.

Produkt: `JidelnaLocalLite`  
Balení: PyInstaller **onedir** + Inno Setup installer (když je ISCC)  
Entrypoint: `python -m jll` → `jll.flet_ui.app:main` (Flet)

## Layout

```text
C:\Program Files\JidelnaLocalLite\
    JidelnaLocalLite.exe
    (PySide6 / runtime dependencies)

C:\ProgramData\JidelnaLocalLite\
    config\          jll.json, users.json, secrets\
    logs\            jll.log
    reset-backups\
```

Binárka **nesmí** zapisovat config/logy vedle EXE v Program Files.
Resolver: `src/jll/runtime_paths.py` (`resolve_runtime_paths`).

| Profil | Jak se aktivuje | Config | Identity | Log |
| --- | --- | --- | --- | --- |
| `lab` | source run (výchozí), `--lab` | `config/lab.json` | `config/users.lab.json` | `logs/jll-lab.log` |
| `production` | frozen EXE | `%PROGRAMDATA%\JidelnaLocalLite\config\jll.json` | `...\users.json` | `...\logs\jll.log` |

Přepisy: CLI `--config` / `--identity-store` / `--log`, případně
`JLL_CONFIG_PATH`, `JLL_IDENTITY_PATH`, `JLL_LOG_PATH`.

Installer vytvoří ProgramData adresáře s `users-modify`. Uninstall **defaultně
nemaže** ProgramData (config/logy/reset-backups zůstávají).

Reset installace (`installation_reset`) mapuje production config na
top-level `reset-backups` (sourozenec `config\`), LAB zůstává u
`config/reset-backups`.

## System Identifier pin

`expected_system_identifier` je fail-closed pin na PostgreSQL
`pg_control_system().system_identifier`. Production **nesmí** oslabit pin
ani přidat switch typu `--unsafe-production`.

`lab_guard` už rozlišuje:

- `assert_configured_lab` / `assert_lab_identity` — loopback + `jll_` prefix
- `assert_configured_production` / `assert_production_identity` — host/DB
  name + System ID pin **bez** loopback/`jll_` požadavku
- `assert_configured_environment` / `assert_runtime_identity` — dispatch

## Environment.LAB | Environment.PRODUCTION

Minimální production config guardy jsou v kódu. Zbývající follow-up mimo
čistý packaging scaffolding:

1. Dokončit UI copy oddělení (LAB banner vs production titles všude).
2. Credentials: production fail-closed bez `JLL_LAB_DB_PASSWORD`.
3. Setup wizard / first-run pro ProgramData production profile end-to-end.
4. Napojení write gates / coexistence policy na production runtime.
5. Explicitní `Environment` enum (volitelné zpřehlednění oproti stringům).

Do podepsaného release je Windows balíček stále **candidate packaging**.

## Žádné automatické DB migrace

Installer ani first-run **nesmí** při instalaci / startu spouštět
`ALTER` / `CREATE` / trigger migrace na zákaznické DB. Povolená je pouze
capability introspection; chybějící capability → fail-closed funkce.

## Unsigned candidate policy

- Build bez `JLL_SIGN_CERT` / bez funkčního `signtool` → artefakty
  **UNSIGNED**.
- `BUILD_INFO.json` musí mít `signature_status: "UNSIGNED"` a
  `signed_release_claim: false`.
- Nikdy neoznačovat unsigned artefakt jako signed release.
- Authenticode pomáhá reputaci, ale **nezaručuje** absenci SmartScreen /
  AV varování u nového publishera / nové binárky.

## Residual SmartScreen / AV risk

Unsigned nebo nově podepsané binárky mohou spustit SmartScreen, Defender
nebo jiný AV heuristický warning. PyInstaller onedir snižuje některé
onefile self-extract heuristiky, ale reputační riziko zůstává.

## Build entrypoint

```bash
./tools/build_windows_release.sh
```

Výstupy:

```text
dist/JidelnaLocalLite/                 # PyInstaller onedir
dist/release/0.6.0/
  JidelnaLocalLite/                    # staged onedir
  JidelnaLocalLite-0.6.0-Setup.exe     # pokud je ISCC dostupný
  BUILD_INFO.json
  SHA256SUMS.txt
```

| Proměnná | Význam |
| --- | --- |
| `JLL_RELEASE_VENV` | cesta k release venv (default `.venv-release`) |
| `JLL_CLEAN_VENV=0` | znovupoužít existující release venv |
| `JLL_SKIP_INNO=1` | přeskočit Inno Setup |
| `JLL_SIGN_CERT` | thumbprint certifikátu pro `signtool` (jinak UNSIGNED) |
| `JLL_RELEASE_VERSION` | label výstupní složky (default `0.6.0`) |

## Packaging notes

- Flet je v PyInstaller `excludes` — produkční runtime je PySide6.
- `reportlab` se instaluje přes extra `production` (fallback `pdf`).
- `AppPublisher` = product name `JidelnaLocalLite` (ne vymyšlená firma).
- Ikona: v repu zatím není legitimní `.ico`.

## Checklist (před tvrzením „signed production ready“)

- [ ] Production first-run / ProgramData ověřen end-to-end
- [ ] System ID pin ověřen na cílové DB
- [ ] Installer bez DB migrace
- [ ] Authenticode sign (pokud je cert) + `BUILD_INFO.signature_status`
- [ ] Dokumentovaný residual SmartScreen risk pro zákazníka
- [ ] Write coexistence policy pro 0.6.0 odsouhlasená

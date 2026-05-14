# Repository guide for automated agents (Cursor Cloud, CI, etc.)

Read this file first, then `README.md`, `docs/DEPENDENCIES.md`, and `docs/BUILD.md`.

## What this repo is

- **BKCurveTool**: Windows desktop app (Python + `pywebview` HTML UI + Win32 clipboard/tray).
- **Entry point**: `main.py`.
- **Packaging**: PyInstaller via `BKCurveTool.spec` → `BKCurveTool.exe`.

## Environment constraints

- **Target OS**: **Windows 10/11** for running the app and for producing the official `.exe`.
- **Python**: **3.10+** recommended; CI uses **3.11** (see `.github/workflows/build.yml`).
- **Do not** run `pyinstaller main.py` without the spec: `BKCurveTool.spec` bundles `src/`; a naked run yields empty `datas` and a broken UI (404 / missing `index.html`).

## Fast setup (development)

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

On non-Windows machines you can still edit Python/HTML, but **Win32 clipboard/tray paths will not execute**; use CI or a Windows VM for integration tests.

## Fast setup (packaging locally)

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --clean --noconfirm BKCurveTool.spec
```

Output: `dist/BKCurveTool.exe`. On Windows you can also run `build_exe.bat`.

## CI / prebuilt binary

- Workflow: **`.github/workflows/build.yml`** (GitHub Actions YAML — not Apache Ant `build.xml`).
- After a successful run: **Actions → latest workflow run → Artifacts → `BKCurveTool-win64`** (contains `BKCurveTool.exe`).

## Key paths

| Path | Role |
|------|------|
| `main.py` | Application logic, Win32 tray, `Api` for JS bridge |
| `src/index.html` | Primary UI loaded by pywebview |
| `src/splash.html`, `src/index_ref.html` | Extra/static assets |
| `data/` | Runtime JSON (`clipboard_data.json`, `app_settings.json`) — ignored by git except `.gitkeep` |
| `BKCurveTool.spec` | PyInstaller one-file, windowed, bundles `src` |

## Debug log (end users / QA)

On Windows, the app appends to `%USERPROFILE%\BKCurveTool_debug.log`. The log line `Tray build: ...` must match the build marker string in `main.py` when verifying a new packaged build.

## Cursor Cloud specific instructions

### Linux environment limitations

This is a **Windows-only desktop app**. On Linux Cloud Agent VMs:

- `main.py` **cannot start** — top-level `import winreg` and `import win32gui` fail immediately (`ModuleNotFoundError`). `pywin32` has no Linux wheels.
- Cross-platform deps (`pyperclip`, `xlwt`, `pywebview`) install and import fine.
- **Lint**: `ruff check main.py` works (2 pre-existing warnings: unused import `win32gui_struct`, unused variable `e` in `log()`).
- **Syntax check**: `python -m py_compile main.py` passes.
- **Core logic** (clipboard parsing, frequency generation, octave smoothing, XLS export) can be tested by extracting functions — they have no Win32 dependency.

### What you can do on Linux

| Task | Command | Works? |
|------|---------|--------|
| Lint | `source .venv/bin/activate && ruff check .` | Yes |
| Syntax check | `source .venv/bin/activate && python -m py_compile main.py` | Yes |
| Install cross-platform deps | `pip install pyperclip xlwt pywebview` | Yes |
| Install build deps | `pip install -r requirements-build.txt` | Yes |
| Run the app | `python main.py` | No — Win32 imports fail |
| Package EXE | `pyinstaller BKCurveTool.spec` | No — needs Windows + pywin32 |

### CI for integration testing

Push changes and rely on **GitHub Actions** (`.github/workflows/build.yml`) which runs on `windows-latest` with Python 3.11. It installs all deps including `pywin32`, builds the EXE via the spec, and uploads the artifact.

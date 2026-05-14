# Build guide — BKCurveTool

GitHub Actions workflow file: **`.github/workflows/build.yml`** (YAML). There is **no** Java Ant `build.xml` in this repo.

## What gets built

- **Output**: single Windows executable **`dist/BKCurveTool.exe`** (PyInstaller one-folder/one-file per `BKCurveTool.spec`).
- **Bundled data**: directory **`src/`** is embedded as `src` next to the frozen app (`datas=[('src', 'src')]` in the spec).

## Local build (Windows recommended)

### 1. Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt
```

### 2. Package

**Preferred (matches CI):**

```powershell
python -m PyInstaller --clean --noconfirm BKCurveTool.spec
```

**Alternative batch file** (checks tray marker string in `main.py`):

```powershell
.\build_exe.bat
```

### 3. Output

- Executable: **`dist\BKCurveTool.exe`**
- Avoid committing `build/` or `dist/` — they are listed in `.gitignore`.

## GitHub Actions (cloud build)

- Trigger: push or PR to `main` / `master`, or **Run workflow** manually (**workflow_dispatch**).
- Runner: **`windows-latest`**.
- Steps: checkout → setup Python **3.11** → `pip install -r requirements.txt -r requirements-build.txt` → `PyInstaller --clean --noconfirm BKCurveTool.spec` → upload artifact.

### Download the CI-built EXE

1. Open the repo on GitHub → **Actions**.
2. Select the **Build Windows EXE** workflow and the successful run.
3. Under **Artifacts**, download **`BKCurveTool-win64`** (zip contains `BKCurveTool.exe`).

Artifacts follow the repository/org **retention** settings (default finite lifetime).

## Common failures

| Symptom | Likely cause |
|---------|----------------|
| UI blank / 404 for HTML | Ran `pyinstaller main.py` without `BKCurveTool.spec`; `datas` empty — use the spec. |
| Import errors for `win32*` | Not on Windows or `pywin32` not installed. |
| CI upload missing exe | PyInstaller failed earlier in the log; check the **PyInstaller** step output. |

## Runtime data layout (after shipping exe)

- Beside `EXE`: **`data\clipboard_data.json`**, **`data\app_settings.json`** (created at runtime).
- User debug log: **`%USERPROFILE%\BKCurveTool_debug.log`**.

# Dependencies — BKCurveTool

This document is for humans and for **cloud agents** cloning the repo. Keep it in sync with `requirements.txt` and `requirements-build.txt`.

## Runtime (`requirements.txt`)

Install before `python main.py`:

| Package | Minimum (repo) | Role |
|---------|----------------|------|
| `pyperclip` | ≥ 1.8.2 | Pinned in `requirements.txt` (legacy/extra; core path uses `pywin32` in `main.py`) |
| `xlwt` | ≥ 1.3.0 | Write `.xls` exports |
| `pywin32` | ≥ 306 | Win32 clipboard, tray, registry |
| `pywebview` | ≥ 5.0 | Native window + embedded browser for `src/index.html` |

**Platform**: **`pywin32` is Windows-only.** The rest are cross-platform, but this application expects Windows for full functionality.

## Build-only (`requirements-build.txt`)

Install when packaging with PyInstaller (local or CI):

| Package | Role |
|---------|------|
| `pyinstaller` | ≥ 6.3.0 — freezes `main.py` + bundled `src/` per `BKCurveTool.spec` |

## System requirements

- **OS**: Windows 10 or 11 (tray, clipboard formats, registry Run key).
- **Python**: **3.10+**; continuous integration uses **3.11** (see `.github/workflows/build.yml`).
- **WebView2**: Usually present on Windows 10/11; `pywebview` on Edge/Chromium backend may need the WebView2 runtime on very old images (rare on desktop Windows).

## Optional developer tools (not pinned in repo)

- **Ruff** / **pytest**: If you add tests or lint jobs later, document versions here.

## Verify install

```powershell
python -c "import webview, win32clipboard, xlwt; print('ok')"
```

On non-Windows, `win32clipboard` import will fail — that is expected.

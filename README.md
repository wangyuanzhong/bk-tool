# BKCurveTool（B&K 曲线数据处理工具）

Windows 桌面小工具：从剪贴板捕获表格数据（大网格 / Excel HTML），按规则截取频段与行列，可选倍频程平滑，并导出为 `.xls`。界面为 **pywebview** 加载 `src/index.html`，系统托盘与剪贴板使用 **pywin32**。

**给自动化助手（Cursor Cloud / CI）**：请先读根目录 **[AGENTS.md](./AGENTS.md)**，再读 **[docs/DEPENDENCIES.md](./docs/DEPENDENCIES.md)** 与 **[docs/BUILD.md](./docs/BUILD.md)**。

---

## 功能概览

- 轮询剪贴板，解析 TSV / HTML 表 / Excel 复制的 HTML。
- 仅当行数足够（≥ 5000）等条件满足时入库；按固定行/列窗口截取（见 `main.py` 常量）。
- 列表中可改文件名；支持倍频程平滑后导出。
- 系统托盘：双击显示窗口，右键菜单；支持 `TaskbarCreated` 后重新挂载图标。
- 可选开机自启动（托盘模式，注册表 `Run` 项名称 `BKCurveTool`）。

---

## 环境要求

- **Windows 10 / 11**
- **Python 3.10+**（与 CI 对齐可使用 3.11）

依赖说明见 **[docs/DEPENDENCIES.md](./docs/DEPENDENCIES.md)**。

---

## 快速开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

---

## 本地打包为 EXE

详见 **[docs/BUILD.md](./docs/BUILD.md)**。摘要：

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --clean --noconfirm BKCurveTool.spec
```

或在仓库根目录执行 **`build_exe.bat`**。产物：**`dist\BKCurveTool.exe`**。

**勿**对 `main.py` 单独执行裸 `pyinstaller`（不含 spec）：将不会打包 `src/`，界面会失效。务必使用 **`BKCurveTool.spec`**。

---

## GitHub Actions 与 EXE 下载

- 工作流文件：**[`.github/workflows/build.yml`](.github/workflows/build.yml)**
- 成功后：GitHub → **Actions** → 对应运行 → **Artifacts** → 下载 **`BKCurveTool-win64`**（内含 `BKCurveTool.exe`）。

---

## 仓库布局

```
bk-tool/
├── main.py                 # 入口与业务逻辑
├── BKCurveTool.spec       # PyInstaller 配置（含 src 资源）
├── build_exe.bat          # Windows 一键打包脚本
├── requirements.txt       # 运行时依赖
├── requirements-build.txt # 打包用（PyInstaller）
├── src/                   # 前端 HTML/CSS/JS
│   ├── index.html
│   ├── splash.html
│   └── index_ref.html
├── data/                  # 运行时 JSON（仅 .gitkeep 入库）
├── docs/
│   ├── DEPENDENCIES.md
│   └── BUILD.md
├── AGENTS.md              # 面向 AI/CI 的快速说明
└── .github/workflows/build.yml
```

---

## 调试

运行后在用户目录查看 **`%USERPROFILE%\BKCurveTool_debug.log`**；新版本应包含与 `main.py` 中 `_TRAY_IMPL_BUILD` 一致的 `Tray build:` 行。

---

## 许可证

（若仓库尚未添加许可证文件，请在根目录补充 `LICENSE`。）

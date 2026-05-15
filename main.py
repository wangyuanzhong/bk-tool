import sys
import os
import re
import csv
import json
import time
import hashlib
import threading
import winreg
import webview
from io import StringIO
from html import unescape
from datetime import datetime

# Windows API for system tray
import ctypes
from ctypes import wintypes
import win32gui
import win32con
import win32api
import win32gui_struct

# Setup logging to file
LOG_FILE = os.path.join(os.path.expanduser("~"), "BKCurveTool_debug.log")

def log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception as e:
        pass

# 更新后必须重新打包；日志里没有这一行 = 仍在跑旧 exe
_TRAY_IMPL_BUILD = "tray-popup-taskbarcreated-20260429f"

log("=" * 50)
log("Application starting...")
log(f"[Main] Tray build: {_TRAY_IMPL_BUILD}")
log(f"[Main] Executable: {sys.executable}")



RUN_REGISTRY_NAME = "BKCurveTool"
TRAY_ARG = "--tray"
APP_DISPLAY_NAME = "BK 系统数据处理工具"

# ===== 行过滤：92～6485 行（从 20Hz 开始）=====
_CLIP_ROW_START_0 = 91  # 第92行（0-based index 91）
_CLIP_ROW_END_EX = 6485
_CLIP_COL_START_0 = 1
_CLIP_COL_END_EX = 3
FREQ_MIN_HZ = 20.0
FREQ_MAX_HZ = 20000.0
SMOOTH_NONE = "none"
SMOOTH_THIRD = "third"
SMOOTH_SIXTH = "sixth"
SMOOTH_TWELFTH = "twelfth"
_SMOOTHING_MODES = frozenset({SMOOTH_NONE, SMOOTH_THIRD, SMOOTH_SIXTH, SMOOTH_TWELFTH})

# 剪贴板条目「文件名」自动策略（设置存 app_settings.json）
FILENAME_MODE_DEFAULT = "default"
FILENAME_MODE_THREE_ANGLE = "three_angle"
FILENAME_MODE_ACCUMULATIVE = "accumulative"
_FILENAME_MODE_CHOICES = frozenset(
    {FILENAME_MODE_DEFAULT, FILENAME_MODE_THREE_ANGLE, FILENAME_MODE_ACCUMULATIVE}
)


def next_accumulative_filename(prev: str) -> str:
    """根据上一条文件名生成下一条（累加模式）。纯数字 +1；末尾数字段 +1；否则末尾无数字则先补 1 再累加。"""
    s = (prev or "").strip()
    if not s:
        return s
    if s.isdigit():
        return str(int(s) + 1)
    m = re.match(r"^(.*\D)(\d+)$", s)
    if m:
        return m.group(1) + str(int(m.group(2)) + 1)
    return s + "1"

# ===== 剪贴板解析函数 =====
def _decode_clipboard_html(raw):
    if raw is None:
        return None
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, bytes):
        for enc in ("utf-8", "gbk", "cp936", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)

def _extract_html_fragment(html):
    if not html:
        return ""
    start = html.find("<!--StartFragment-->")
    end = html.find("<!--EndFragment-->")
    if start != -1 and end != -1 and end > start:
        return html[start + len("<!--StartFragment-->"): end]
    lower = html.lower()
    i = lower.find("<body")
    if i != -1:
        j = lower.find("</body>", i)
        if j != -1:
            return html[i:j]
    return html

def _strip_td_inner_html(inner):
    s = inner.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\xa0", " ")
    return s

def _parse_td_opening_attrs(open_tag):
    colspan = 1
    rowspan = 1
    m = re.search(r"colspan\s*=\s*\"?(\d+)\"?", open_tag, re.I)
    if m:
        colspan = max(1, int(m.group(1)))
    m = re.search(r"rowspan\s*=\s*\"?(\d+)\"?", open_tag, re.I)
    if m:
        rowspan = max(1, int(m.group(1)))
    return colspan, rowspan

def parse_excel_html_table(html):
    fragment = _extract_html_fragment(html)
    if not fragment.strip():
        return None
    m = re.search(r"<table[^>]*>(.*)</table>", fragment, re.I | re.S)
    body = m.group(1) if m else fragment
    tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.I | re.S)
    if not tr_blocks:
        return None
    grid = []
    for tr in tr_blocks:
        row = []
        for td in re.finditer(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.I | re.S):
            attrs, inner = td.group(1), td.group(2)
            colspan, _ = _parse_td_opening_attrs(attrs)
            text = _strip_td_inner_html(inner)
            row.append(text)
            for _ in range(colspan - 1):
                row.append("")
        if row:
            grid.append(row)
    if not grid:
        return None
    max_cols = max(len(r) for r in grid)
    for r in grid:
        while len(r) < max_cols:
            r.append("")
    return grid

def parse_tab_delimited_quoted(text):
    if not text:
        return None
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    f = StringIO(normalized)
    try:
        reader = csv.reader(f, delimiter="\t", quotechar='"', doublequote=True, skipinitialspace=False, strict=False)
        rows = [list(row) for row in reader]
    except csv.Error:
        return None
    if not rows:
        return None
    max_cols = max((len(r) for r in rows), default=0)
    for r in rows:
        while len(r) < max_cols:
            r.append("")
    return rows

def _grid_has_content(grid):
    return any(any(str(c).strip() for c in row) for row in grid)

def parse_clipboard_table_best_effort(text, html):
    candidates = []
    if text and text.strip():
        g = parse_tab_delimited_quoted(text)
        if g and _grid_has_content(g):
            candidates.append(g)
    if html and html.strip():
        try:
            g = parse_excel_html_table(html)
            if g and len(g) >= 1 and _grid_has_content(g):
                candidates.append(g)
        except Exception:
            pass
    if text:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        grid = []
        for line in lines:
            grid.append(line.split("\t"))
        if grid:
            max_cols = max(len(r) for r in grid)
            for r in grid:
                while len(r) < max_cols:
                    r.append("")
            if _grid_has_content(grid):
                candidates.append(grid)
    if not candidates:
        return None
    return max(candidates, key=lambda g: (len(g), sum(len(r) for r in g)))

def apply_clip_range_filter(table_data):
    if not table_data:
        return []
    if len(table_data) < _CLIP_ROW_START_0 + 1:
        return []
    rows = table_data[_CLIP_ROW_START_0:_CLIP_ROW_END_EX]
    out = []
    for row in rows:
        r = list(row)
        while len(r) < _CLIP_COL_END_EX:
            r.append("")
        out.append(r[_CLIP_COL_START_0:_CLIP_COL_END_EX])
    return out


def _normalize_rectangular_grid(grid):
    """将任意行列表规范为矩形表，至少 2 列（与后续频率/幅度列逻辑一致）。"""
    if not grid:
        return []
    max_cols = max((len(r) if r else 0 for r in grid), default=0)
    max_cols = max(max_cols, 2)
    out = []
    for row in grid:
        r = list(row) if row is not None else [""]
        while len(r) < max_cols:
            r.append("")
        out.append(r[:max_cols])
    return out


def prepare_rows_for_clip_item(table_data):
    """优先 BK 大行数固定行窗；不足时整表入库（任意小表/非标准 Excel 复制）。"""
    filtered = apply_clip_range_filter(table_data)
    if filtered:
        return filtered
    if not table_data:
        return []
    return _normalize_rectangular_grid(table_data)


def clipboard_grid_from_snapshot(text, html):
    """解析 TSV/HTML 表；失败则用纯文本或去标签 HTML 作为逐行后备。"""
    grid = parse_clipboard_table_best_effort(text, html)
    if grid and _grid_has_content(grid):
        return grid
    raw = ""
    if text and text.strip():
        raw = text.strip()
    elif html and html.strip():
        frag = _extract_html_fragment(html)
        t = re.sub(r"<[^>]+>", " ", frag or html)
        raw = unescape(t)
        raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in normalized.split("\n") if str(ln).strip() != ""]
    if not lines:
        lines = [raw[:12000]]
    rows = [[ln] for ln in lines]
    return _normalize_rectangular_grid(rows)

def linear_freqs_20_to_20k(n):
    if n <= 0:
        return []
    if n == 1:
        return [FREQ_MIN_HZ]
    return [FREQ_MIN_HZ + (FREQ_MAX_HZ - FREQ_MIN_HZ) * i / (n - 1) for i in range(n)]

def _parse_float_cell(val):
    if val is None or (isinstance(val, str) and not val.strip()):
        return 0.0
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def octave_band_smooth(freqs, amps, octave_width):
    n = len(freqs)
    if n != len(amps) or n == 0:
        return list(amps)
    k_lo = 2 ** (-octave_width / 2)
    k_hi = 2 ** (octave_width / 2)
    out = [0.0] * n
    left = 0
    right = -1
    s = 0.0
    cnt = 0
    for i in range(n):
        fc = freqs[i]
        f_lo = fc * k_lo
        f_hi = fc * k_hi
        while left < n and freqs[left] < f_lo:
            if left <= right:
                s -= amps[left]
                cnt -= 1
            left += 1
        while right + 1 < n and freqs[right + 1] <= f_hi:
            right += 1
            s += amps[right]
            cnt += 1
        if cnt > 0:
            out[i] = s / cnt
        else:
            out[i] = amps[i]
    return out

def apply_octave_smoothing(freqs, amps, mode):
    if mode == SMOOTH_NONE or not mode:
        return list(amps)
    width = {SMOOTH_THIRD: 1/3, SMOOTH_SIXTH: 1/6, SMOOTH_TWELFTH: 1/12}.get(mode)
    if width is None:
        return list(amps)
    return octave_band_smooth(freqs, amps, width)

def clipboard_change_fingerprint(text, html):
    h = hashlib.sha256()
    if text is not None:
        h.update(text.encode("utf-8", errors="ignore"))
    h.update(b"\x1e")
    if html is not None:
        h.update(html.encode("utf-8", errors="ignore"))
    return h.digest()

# ===== 数据模型 =====
class ClipboardItem:
    def __init__(self, freqs, amps_raw, raw_bc_rows, filename, timestamp=None):
        self.freqs = freqs
        self.amps_raw = amps_raw
        self.raw_bc_rows = raw_bc_rows
        self.filename = filename
        self.timestamp = timestamp or datetime.now().isoformat()

    def get_table_data(self, smoothing_mode=SMOOTH_NONE):
        amps = apply_octave_smoothing(self.freqs, self.amps_raw, smoothing_mode)
        return [[round(f, 2), round(a, 2)] for f, a in zip(self.freqs, amps)]

    def to_dict(self):
        return {
            "v": 2,
            "freqs": self.freqs,
            "amps_raw": self.amps_raw,
            "raw_bc": self.raw_bc_rows,
            "filename": self.filename,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data):
        if data.get("v") == 2 and "freqs" in data and "amps_raw" in data:
            freqs = data["freqs"]
            amps_raw = data["amps_raw"]
            raw_bc = data.get("raw_bc")
            if not raw_bc:
                raw_bc = [[str(freqs[i]), str(amps_raw[i])] for i in range(len(freqs))]
            return cls(freqs, amps_raw, raw_bc, data.get("filename", "untitled"), data.get("timestamp"))
        td = data.get("table_data") or []
        n = len(td)
        freqs = linear_freqs_20_to_20k(n)
        amps_raw = [_parse_float_cell(row[1]) if len(row) > 1 else 0.0 for row in td]
        raw_bc = [list(row) for row in td] if td else []
        return cls(freqs, amps_raw, raw_bc, data.get("filename", "untitled"), data.get("timestamp"))

    def get_dimensions(self):
        n = len(self.freqs)
        return (n, 2) if n else (0, 0)

    def to_js_dict(self):
        rows, cols = self.get_dimensions()
        td = self.get_table_data()
        preview = ""
        if td:
            parts = []
            for row in td[:2]:
                parts.append("|".join([str(c)[:10] for c in row[:2]]))
            if len(td) > 2:
                parts.append(f"...({len(td)}行)")
            preview = "; ".join(parts)
        return {
            "filename": self.filename,
            "rows": rows,
            "cols": cols,
            "preview": preview,
        }

# ===== 剪贴板监控 =====
class ClipboardMonitor:
    def __init__(self, callback):
        self.callback = callback
        self.last_fp = None
        self.running = True
        self.first_check = True
        self.bypass = False
        self.thread = None

    def get_clipboard_snapshot(self):
        import win32clipboard
        text = None
        html = None
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
            if win32clipboard.IsClipboardFormatAvailable(cf_html):
                raw = win32clipboard.GetClipboardData(cf_html)
                html = _decode_clipboard_html(raw)
            win32clipboard.CloseClipboard()
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        return text, html

    def run(self):
        while self.running:
            try:
                text, html = self.get_clipboard_snapshot()
                fp = clipboard_change_fingerprint(text, html)

                if self.first_check:
                    self.first_check = False
                    self.last_fp = fp
                elif fp != self.last_fp:
                    if self.bypass:
                        self.last_fp = fp
                        continue
                    self.last_fp = fp
                    raw_grid = clipboard_grid_from_snapshot(text, html)
                    if not raw_grid or not _grid_has_content(raw_grid):
                        continue
                    self.callback(raw_grid)

                time.sleep(0.3)
            except Exception as e:
                print(f"监控错误: {e}")
                time.sleep(1)

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def set_bypass(self, enabled):
        self.bypass = enabled

_TRAY_HWND_MAP = {}


def _tray_wnd_proc(hwnd, msg, wparam, lparam):
    inst = _TRAY_HWND_MAP.get(int(hwnd))
    if inst is None:
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    return inst._dispatch_tray_wnd(hwnd, msg, wparam, lparam)


# ===== API 类 =====
class TrayIcon:
    """
    独立线程：隐藏 WS_POPUP 工具窗 + GetMessage 循环（与 PyWin32 官方 taskbar demo 同思路）；
    Shell_NotifyIcon 使用 pywin32 元组形式。注册 TaskbarCreated，Explorer/任务栏重载后重新 NIM_ADD。
    """
    _CALLBACK_MSG = win32con.WM_USER + 42
    _ICON_UID = 1

    def __init__(self, window, app_name="App"):
        self.window = window
        self.app_name = app_name or "App"
        self.hwnd = None
        self.hicon = None
        self.visible = False
        self.class_name = "BKCurveToolTrayMsgWnd"
        self._thread = None
        self._lock = threading.Lock()
        self._hwnd_ready = threading.Event()
        self._taskbar_created_msg = 0

    def _shell_add(self):
        if not self.hwnd or not self.hicon:
            log("[Tray] _shell_add skipped: missing hwnd or icon")
            return
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        nid = (
            self.hwnd,
            self._ICON_UID,
            flags,
            self._CALLBACK_MSG,
            self.hicon,
            self.app_name,
        )
        last_err = None
        for attempt in range(5):
            try:
                r = win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
                log(f"[Tray] Shell_NotifyIcon NIM_ADD -> {r!r} (attempt {attempt + 1})")
                return
            except win32gui.error as e:
                last_err = e
                log(f"[Tray] Shell_NotifyIcon NIM_ADD failed: {e} (attempt {attempt + 1})")
                time.sleep(0.4)
        if last_err:
            raise last_err

    def _shell_delete(self):
        if not self.hwnd:
            return
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, self._ICON_UID))
        except Exception as e:
            log(f"[Tray] NIM_DELETE: {e}")

    def _dispatch_tray_wnd(self, hwnd, msg, wparam, lparam):
        if self._taskbar_created_msg and msg == self._taskbar_created_msg:
            log("[Tray] TaskbarCreated -> re-adding tray icon")
            try:
                try:
                    win32gui.Shell_NotifyIcon(
                        win32gui.NIM_DELETE, (self.hwnd, self._ICON_UID)
                    )
                except win32gui.error:
                    pass
                self._shell_add()
            except Exception as e:
                log(f"[Tray] TaskbarCreated re-add failed: {e}")
            return 0
        if msg == win32con.WM_CLOSE:
            log("[Tray] WM_CLOSE: removing icon and destroying message window")
            self._shell_delete()
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            try:
                _TRAY_HWND_MAP.pop(int(hwnd), None)
            except Exception:
                pass
            self.visible = False
            win32gui.PostQuitMessage(0)
            return 0
        if msg == self._CALLBACK_MSG:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                log("[Tray] Double click -> show window")
                if self.window:
                    try:
                        self.window.show()
                    except Exception as e:
                        log(f"[Tray] window.show(): {e}")
            elif lparam == win32con.WM_RBUTTONUP:
                log("[Tray] Right click -> menu")
                self._show_menu()
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        try:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1000, "显示窗口")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1001, "退出")

            pos = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            cmd = win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_RETURNCMD | win32con.TPM_LEFTALIGN,
                pos[0], pos[1], 0, self.hwnd, None,
            )
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

            if cmd == 1000:
                log("[Tray] Menu: Show window")
                if self.window:
                    try:
                        self.window.show()
                    except Exception as e:
                        log(f"[Tray] window.show(): {e}")
            elif cmd == 1001:
                log("[Tray] Menu: Exit")
                if self.window:
                    try:
                        self.window.destroy()
                    except Exception as e:
                        log(f"[Tray] window.destroy(): {e}")
        except Exception as e:
            log(f"[Tray] Error showing menu: {e}")

    def _run_tray_thread(self):
        user32 = ctypes.windll.user32
        self._hwnd_ready.clear()
        self.hicon = None
        hinst = win32api.GetModuleHandle(None)
        hwnd_msg = None
        try:
            self._taskbar_created_msg = win32gui.RegisterWindowMessage("TaskbarCreated")
            log(f"[Tray] TaskbarCreated msg = {self._taskbar_created_msg}")

            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = _tray_wnd_proc
            wc.lpszClassName = self.class_name
            wc.hInstance = hinst
            try:
                win32gui.RegisterClass(wc)
            except Exception as e:
                err = getattr(e, "winerror", None)
                if err != 1410:
                    log(f"[Tray] RegisterClass failed: {e}")
                    return

            exstyle = win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
            wstyle = win32con.WS_POPUP
            hwnd_msg = win32gui.CreateWindowEx(
                exstyle,
                self.class_name,
                "",
                wstyle,
                -32000,
                -32000,
                1,
                1,
                0,
                0,
                hinst,
                None,
            )
            self.hwnd = hwnd_msg
            _TRAY_HWND_MAP[int(hwnd_msg)] = self

            try:
                self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            except Exception:
                self.hicon = None
            if not self.hicon:
                raise RuntimeError("LoadIcon failed")

            self._shell_add()
            self.visible = True
            self._hwnd_ready.set()
            log(f"[Tray] Icon added, entering message loop ({_TRAY_IMPL_BUILD} hwnd={self.hwnd})")

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            log("[Tray] Message loop exited")
        except Exception as e:
            log(f"[Tray] Tray thread error: {e}")
            import traceback
            log(traceback.format_exc())
            self.visible = False
        finally:
            self._shell_delete()
            if hwnd_msg is not None:
                try:
                    _TRAY_HWND_MAP.pop(int(hwnd_msg), None)
                except Exception:
                    pass
                try:
                    win32gui.DestroyWindow(hwnd_msg)
                except Exception:
                    pass
            self.hwnd = None
            self.hicon = None
            self.visible = False
            try:
                win32gui.UnregisterClass(self.class_name, hinst)
            except Exception:
                pass
            self._hwnd_ready.set()

    def show(self):
        log(
            f"[Tray] show() build={_TRAY_IMPL_BUILD} visible={self.visible} "
            f"thread_alive={self._thread.is_alive() if self._thread else False}"
        )
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                log("[Tray] Tray thread already running, skip")
                return
            self._hwnd_ready.clear()
            self._thread = threading.Thread(
                target=self._run_tray_thread,
                name="TrayMessageLoop",
                daemon=False,
            )
            self._thread.start()
        if not self._hwnd_ready.wait(timeout=20):
            log("[Tray] Timeout waiting for tray setup")
            return
        if not self.visible:
            log("[Tray] Setup finished without visible icon (check log above)")

    def hide(self):
        self.stop()

    def stop(self):
        log("[Tray] stop()")
        hwnd = self.hwnd
        if hwnd:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception as e:
                log(f"[Tray] PostMessage WM_CLOSE: {e}")
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=8)
        self._thread = None


class Api:
    def __init__(self):
        self.items = []
        self._window = None
        self.monitor = None
        self.data_file = None
        self.settings_file = None
        self.output_dir = os.path.join(os.path.expanduser("~"), "BKCurveExports")
        self.settings = {}
        self._initialized = False
        self._tray = None  # type: ignore
        self._items_lock = threading.RLock()
    
    def _ensure_initialized(self):
        """延迟初始化 - 只在需要时执行文件I/O"""
        if self._initialized:
            return
        
        # 使用正确的路径（支持打包后的exe）
        if getattr(sys, 'frozen', False):
            # 打包后的exe
            base_path = os.path.dirname(sys.executable)
        else:
            # 开发环境
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.data_file = os.path.join(base_path, "data", "clipboard_data.json")
        self.settings_file = os.path.join(base_path, "data", "app_settings.json")
        
        log(f"[Api] Initializing with base_path={base_path}")
        log(f"[Api] data_file={self.data_file}")
        log(f"[Api] settings_file={self.settings_file}")
        
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        self.load_data()
        self.settings = self._read_settings()
        log(f"[Api] Settings loaded: {self.settings}")
        saved_out = self.settings.get("output_dir")
        if isinstance(saved_out, str) and saved_out.strip():
            try:
                p = os.path.normpath(saved_out.strip())
                os.makedirs(p, exist_ok=True)
                self.output_dir = p
            except OSError:
                pass

        self._initialized = True

    def start_monitor(self):
        if self.monitor is None:
            self.monitor = ClipboardMonitor(self.on_new_clipboard_data)
            self.monitor.start()

    def on_new_clipboard_data(self, table_data):
        prepared = prepare_rows_for_clip_item(table_data)
        if not prepared:
            return
        n = len(prepared)
        # 使用原始频率，只修改第一个为20Hz
        freqs = [_parse_float_cell(row[0]) for row in prepared]
        if freqs:
            freqs[0] = 20.0  # 只修改第一个频率为20Hz
        amps_raw = [_parse_float_cell(row[1]) for row in prepared]
        raw_bc_rows = [list(row) for row in prepared]
        rows = n
        cols = 2
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = f"bk_curve_{timestamp}_{rows}行{cols}列"
        mode = self.settings.get("filename_mode", FILENAME_MODE_DEFAULT)
        if mode not in _FILENAME_MODE_CHOICES:
            mode = FILENAME_MODE_DEFAULT
        with self._items_lock:
            if mode == FILENAME_MODE_ACCUMULATIVE and self.items:
                prev_fn = (self.items[-1].filename or "").strip()
                # 上一条仍是自动时间戳名时，不累加（避免在整串后拼 "1"）
                if prev_fn.startswith("bk_curve_"):
                    default_name = fallback
                else:
                    default_name = next_accumulative_filename(prev_fn)
                    if not (default_name or "").strip():
                        default_name = fallback
            else:
                default_name = fallback
            item = ClipboardItem(freqs, amps_raw, raw_bc_rows, default_name)
            self.items.append(item)
        self.save_data()
        js_item = item.to_js_dict()
        js_item_json = json.dumps(js_item, ensure_ascii=False)
        self._evaluate_js(f"window.onNewClipboardItem({js_item_json})")
        self._maybe_auto_save_xls_for_autonamed_new_row(default_name)

    def _notify_status(self, message, duration_ms=6000):
        if not self._window:
            return
        try:
            msg_js = json.dumps(message, ensure_ascii=False)
            self._evaluate_js(f"window.showStatus({msg_js}, {int(duration_ms)})")
        except Exception as e:
            log(f"[Api] _notify_status failed: {e}")

    def _probe_output_dir(self):
        """检测当前保存目录是否可创建/删除文件（权限与只读盘等）。"""
        if not self.output_dir:
            return False, "未设置保存目录"
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            probe = os.path.join(self.output_dir, ".bkcurve_write_test.tmp")
            with open(probe, "wb") as f:
                f.write(b"ok")
            os.remove(probe)
            return True, None
        except Exception as e:
            return False, str(e)

    def _auto_save_xls_for_indices(self, indices, fail_prefix="自动导出 xls"):
        """按当前文件名与 smoothing_mode 将指定条目导出为 xls（需已开启 auto_save_xls）。"""
        self._ensure_initialized()
        if not self.settings.get("auto_save_xls"):
            return
        ok, err = self._probe_output_dir()
        if not ok:
            self._notify_status(
                f"{fail_prefix}失败：无法在「保存位置」创建文件。"
                f"（{err}）请点击「更改」选择可写文件夹；系统受保护目录需管理员权限，本程序无法代为申请。",
                14000,
            )
            return
        smo = self.settings.get("smoothing_mode", SMOOTH_NONE)
        if smo not in _SMOOTHING_MODES:
            smo = SMOOTH_NONE
        with self._items_lock:
            n = len(self.items)
        idxs = sorted({i for i in indices if isinstance(i, int) and 0 <= i < n})
        if not idxs:
            return
        ok_names = []
        for i in idxs:
            result = self.save_item(i, smo)
            if result.get("success"):
                ok_names.append(result.get("filename", ""))
            else:
                em = result.get("error", "未知错误")
                self._notify_status(f"{fail_prefix}失败（第{i + 1}条）：{em}", 12000)
                return
        if ok_names:
            self._notify_status("已自动导出 xls：" + "、".join(ok_names), 8000)

    def _maybe_auto_save_xls_for_autonamed_new_row(self, default_name):
        """累加等模式下新条目名已非默认 bk_curve_ 时间戳串，视为名称已确定，入库后同样导出 xls。"""
        dn = (default_name or "").strip()
        if not dn or dn.startswith("bk_curve_"):
            return
        with self._items_lock:
            idx = len(self.items) - 1
        if idx < 0:
            return
        self._auto_save_xls_for_indices([idx], fail_prefix="自动导出 xls")

    def _maybe_auto_save_xls_after_rename(self, index, filename_mode):
        """手动改名或三角度连带改名后导出。"""
        indices = [index]
        if filename_mode == FILENAME_MODE_THREE_ANGLE:
            indices.extend([index + 1, index + 2])
        self._auto_save_xls_for_indices(indices, fail_prefix="改名后自动导出 xls")

    def set_smoothing_mode(self, mode):
        self._ensure_initialized()
        if mode not in _SMOOTHING_MODES:
            mode = SMOOTH_NONE
        self.settings["smoothing_mode"] = mode
        self._save_settings()
        return {"success": True}

    def set_auto_save_xls(self, enabled):
        self._ensure_initialized()
        self.settings["auto_save_xls"] = bool(enabled)
        self._save_settings()
        out = {"success": True, "probe_ok": True}
        if bool(enabled):
            ok, err = self._probe_output_dir()
            out["probe_ok"] = ok
            if not ok:
                out["probe_error"] = err
        return out

    def set_window(self, window):
        self._window = window
    
    def on_window_loaded(self):
        """窗口加载完成后调用 - 完全避免阻塞UI"""
        import threading
        
        # 延迟所有初始化到后台线程
        def delayed_init():
            # 执行文件I/O初始化
            self._ensure_initialized()

            # 启动剪贴板监控
            self.start_monitor()
            if self.monitor:
                self.monitor.set_bypass(self.settings.get("bypass", False))
            path_js = json.dumps(self.output_dir, ensure_ascii=False)
            self._evaluate_js(f"window.setOutputDir({path_js})")
            bypass_js = "true" if self.settings.get("bypass") else "false"
            # 检查两个独立设置
            tray_startup = self.settings.get("tray_startup", False)
            tray_js = "true" if tray_startup else "false"
            self._evaluate_js(f"window.setBypassState({bypass_js})")
            self._evaluate_js(f"window.setTrayStartupState({tray_js})")
            as_js = "true" if self.settings.get("auto_save_xls") else "false"
            self._evaluate_js(f"window.setAutoSaveXlsState({as_js})")
            smo = self.settings.get("smoothing_mode", SMOOTH_NONE)
            if smo not in _SMOOTHING_MODES:
                smo = SMOOTH_NONE
            smo_json = json.dumps(smo, ensure_ascii=False)
            self._evaluate_js(f"window.setSmoothingModeState({smo_json})")
            fn_mode = self.settings.get("filename_mode", FILENAME_MODE_DEFAULT)
            if fn_mode not in _FILENAME_MODE_CHOICES:
                fn_mode = FILENAME_MODE_DEFAULT
            fn_mode_js = json.dumps(fn_mode, ensure_ascii=False)
            self._evaluate_js(f"window.setFilenameModeState({fn_mode_js})")
            self._update_ui_items()
        
        threading.Thread(target=delayed_init, daemon=True).start()

    def _evaluate_js(self, script):
        if self._window:
            try:
                self._window.evaluate_js(script)
            except Exception as e:
                print(f"JS evaluation error: {e}")

    def _read_settings(self):
        if not self.settings_file:
            return {}
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"读取设置失败: {e}")
        return {}

    def _save_settings(self):
        if not self.settings_file:
            return
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存设置失败: {e}")

    def _is_tray_startup(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, RUN_REGISTRY_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    def _update_ui_items(self):
        """更新UI项目列表"""
        with self._items_lock:
            if not self.items:
                empty = True
                js_items = None
            else:
                empty = False
                js_items = [item.to_js_dict() for item in self.items]
        if empty:
            self._evaluate_js("window.updateItems([])")
            return
        js_items_json = json.dumps(js_items, ensure_ascii=False)
        self._evaluate_js(f"window.updateItems({js_items_json})")

    def update_filename(self, index, filename):
        self._ensure_initialized()
        filename_mode = FILENAME_MODE_DEFAULT
        with self._items_lock:
            if not (0 <= index < len(self.items)):
                return {"success": False}
            self.items[index].filename = filename
            filename_mode = self.settings.get("filename_mode", FILENAME_MODE_DEFAULT)
            if filename_mode not in _FILENAME_MODE_CHOICES:
                filename_mode = FILENAME_MODE_DEFAULT
            if filename_mode == FILENAME_MODE_THREE_ANGLE:
                base = filename
                for off, suf in ((1, "180"), (2, "135")):
                    j = index + off
                    if j < len(self.items):
                        self.items[j].filename = base + suf
        self._update_ui_items()
        self.save_data()
        self._maybe_auto_save_xls_after_rename(index, filename_mode)
        return {"success": True}

    def set_filename_mode(self, mode):
        self._ensure_initialized()
        if mode not in _FILENAME_MODE_CHOICES:
            mode = FILENAME_MODE_DEFAULT
        self.settings["filename_mode"] = mode
        self._save_settings()
        return {"success": True}

    def delete_item(self, index):
        changed = False
        with self._items_lock:
            if 0 <= index < len(self.items):
                self.items.pop(index)
                changed = True
        if changed:
            self.save_data()
            self._update_ui_items()
        return {"success": True}

    def clear_all(self):
        with self._items_lock:
            self.items.clear()
        self.save_data()
        self._update_ui_items()
        return {"success": True}

    def save_item(self, index, mode):
        with self._items_lock:
            if index < 0 or index >= len(self.items):
                return {"success": False, "error": "无效索引"}
            item = self.items[index]
        if not item.freqs:
            return {"success": False, "error": "没有可保存的数据"}
        table_data = item.get_table_data(mode)
        safe_filename = re.sub(r'[\\/:*?"<>|]', "_", item.filename).strip(" .")
        if not safe_filename:
            safe_filename = "bk_curve"
        if len(safe_filename) > 180:
            safe_filename = safe_filename[:180]
        file_path = os.path.join(self.output_dir, f"{safe_filename}.xls")
        try:
            self._write_xls(table_data, file_path)
            return {"success": True, "path": file_path, "filename": f"{safe_filename}.xls"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_all(self, mode):
        with self._items_lock:
            if not self.items:
                return {"success": False, "error": "列表为空"}
            snapshot = list(enumerate(self.items))
        success_count = 0
        for i, item in snapshot:
            result = self.save_item(i, mode)
            if result["success"]:
                success_count += 1
        return {"success": True, "count": success_count}

    def _write_xls(self, table_data, file_path):
        import xlwt
        wb = xlwt.Workbook(encoding='utf-8')
        ws = wb.add_sheet('Data')
        header_style = xlwt.XFStyle()
        header_font = xlwt.Font()
        header_font.bold = True
        header_font.colour_index = 0x08
        header_font.height = 220
        header_style.font = header_font
        header_pattern = xlwt.Pattern()
        header_pattern.pattern = xlwt.Pattern.SOLID_PATTERN
        header_pattern.pattern_fore_colour = 0x2C
        header_style.pattern = header_pattern
        header_borders = xlwt.Borders()
        header_borders.left = xlwt.Borders.THIN
        header_borders.right = xlwt.Borders.THIN
        header_borders.top = xlwt.Borders.THIN
        header_borders.bottom = xlwt.Borders.THIN
        header_style.borders = header_borders
        data_style = xlwt.XFStyle()
        data_font = xlwt.Font()
        data_font.colour_index = 0x08
        data_font.height = 200
        data_style.font = data_font
        data_borders = xlwt.Borders()
        data_borders.left = xlwt.Borders.THIN
        data_borders.right = xlwt.Borders.THIN
        data_borders.top = xlwt.Borders.THIN
        data_borders.bottom = xlwt.Borders.THIN
        data_style.borders = data_borders
        if table_data and len(table_data) > 0:
            ws.write(0, 0, '频率 (Hz)', header_style)
            ws.write(0, 1, '幅度', header_style)
            for row_idx, row_data in enumerate(table_data, 1):
                for col_idx, cell_value in enumerate(row_data):
                    if cell_value is None or cell_value == "":
                        val = ""
                    else:
                        val = cell_value
                    ws.write(row_idx, col_idx, val, data_style)
            ws.col(0).width = 4000
            ws.col(1).width = 4000
        wb.save(file_path)

    def changeOutputDir(self):
        self._ensure_initialized()
        try:
            # 使用 webview.windows 获取窗口列表
            if webview.windows:
                window = webview.windows[0]
                result = window.create_file_dialog(
                    dialog_type=webview.FOLDER_DIALOG,
                    directory=self.output_dir
                )
                if result and len(result) > 0:
                    self.output_dir = result[0]
                    self.settings["output_dir"] = self.output_dir
                    self._save_settings()
                    ok, err = self._probe_output_dir()
                    return {
                        "path": self.output_dir,
                        "writable": ok,
                        "writable_error": err or "",
                    }
        except Exception as e:
            print(f"选择目录失败: {e}")
            import traceback
            traceback.print_exc()
        return {"path": None}

    def open_output_dir(self):
        try:
            os.startfile(self.output_dir)
        except Exception as e:
            print(f"打开目录失败: {e}")
        return {"success": True}

    def open_file(self, file_path):
        try:
            os.startfile(file_path)
        except Exception as e:
            print(f"打开文件失败: {e}")
        return {"success": True}

    def set_bypass(self, enabled):
        self.settings["bypass"] = enabled
        self._save_settings()
        if self.monitor:
            self.monitor.set_bypass(enabled)
        return {"success": True}

    def set_tray_startup(self, enabled):
        log(f"[Api] set_tray_startup called with enabled={enabled}")
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            try:
                if enabled:
                    # 开机自启动到托盘
                    if getattr(sys, "frozen", False):
                        cmd = f'"{sys.executable}" {TRAY_ARG}'
                    else:
                        script = os.path.abspath(__file__)
                        cmd = f'"{sys.executable}" "{script}" {TRAY_ARG}'
                    winreg.SetValueEx(key, RUN_REGISTRY_NAME, 0, winreg.REG_SZ, cmd)
                    log(f"[Api] Registry entry added: {cmd}")
                else:
                    # 删除开机启动项
                    try:
                        winreg.DeleteValue(key, RUN_REGISTRY_NAME)
                        log("[Api] Registry entry removed")
                    except FileNotFoundError:
                        log("[Api] Registry entry not found, nothing to remove")
            finally:
                winreg.CloseKey(key)
            
            # 保存设置
            self.settings["tray_startup"] = enabled
            self._save_settings()
            log(f"[Api] Settings saved, tray_startup={enabled}")
            
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_minimize_to_tray(self, enabled):
        log(f"[Api] set_minimize_to_tray called with enabled={enabled}")
        try:
            self.settings["minimize_to_tray"] = enabled
            self._save_settings()
            log(f"[Api] Settings saved, minimize_to_tray={enabled}")
            return {"success": True}
        except Exception as e:
            log(f"[Api] Error saving minimize_to_tray: {e}")
            return {"success": False, "error": str(e)}

    def minimize_to_tray(self):
        """最小化到托盘 - 由JS调用"""
        log("[Api] minimize_to_tray called")
        try:
            if self._window:
                self._window.hide()
                log("[Api] Window hidden")
            if self._tray:
                self._tray.show()
                log("[Api] Tray shown")
            return {"success": True}
        except Exception as e:
            log(f"[Api] Error minimizing to tray: {e}")
            return {"success": False, "error": str(e)}

    def save_data(self):
        if not self.data_file:
            log("[Api] save_data skipped: data_file not set")
            return
        try:
            with self._items_lock:
                data = [item.to_dict() for item in self.items]
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"[Api] save_data failed: {e}")
            print(f"保存数据失败: {e}")

    def load_data(self):
        if not self.data_file:
            return
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                with self._items_lock:
                    self.items = [ClipboardItem.from_dict(item) for item in data]
        except Exception as e:
            print(f"加载数据失败: {e}")
            with self._items_lock:
                self.items = []

    def stop(self):
        if self.monitor:
            self.monitor.stop()
        self.save_data()
        self._save_settings()


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def main():
    api = Api()
    
    # 同步加载设置，确保在创建窗口前配置已就绪
    log("[Main] Loading settings before creating window...")
    api._ensure_initialized()
    
    html_path = get_resource_path('src/index.html')
    
    # 检查是否以托盘模式启动（开机自启动）
    is_tray_mode = TRAY_ARG in sys.argv
    
    # 读取两个独立的设置项
    tray_startup = api.settings.get("tray_startup", False)
    minimize_to_tray = api.settings.get("minimize_to_tray", True)  # 默认开启
    
    log(f"[Main] Settings loaded: tray_startup={tray_startup}, minimize_to_tray={minimize_to_tray}")
    
    # 创建窗口
    window = webview.create_window(
        APP_DISPLAY_NAME,
        html_path,
        width=720,
        height=800,
        resizable=True,
        js_api=api
    )
    
    api.set_window(window)
    
    # 创建托盘图标
    tray = TrayIcon(window, APP_DISPLAY_NAME)
    api._tray = tray
    
    # 启动后初始化
    def on_loaded():
        log(f"[Main] on_loaded called, is_tray_mode={is_tray_mode}")
        api.on_window_loaded()
        # 如果是托盘模式启动，隐藏窗口并显示托盘图标
        if is_tray_mode and tray_startup:
            log("[Main] Tray mode startup: hiding window and showing tray...")
            window.hide()
            tray.show()
    
    # 设置关闭事件处理 - 点X直接退出，不拦截
    def on_closing():
        log("[Main] on_closing called - allowing close")
        return True  # 允许关闭
    
    window.events.closing += on_closing
    

    
    log("[Main] Starting webview...")
    webview.start(on_loaded, debug=True)
    log("[Main] Webview closed")
    api.stop()

    # 清理托盘
    if tray.visible:
        log("[Main] Stopping tray icon...")
        tray.stop()


if __name__ == '__main__':
    main()

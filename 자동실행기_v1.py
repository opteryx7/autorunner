import copy
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from difflib import SequenceMatcher

import pyautogui
import pyperclip

try:
    from pynput import keyboard as pynput_keyboard
    from pynput import mouse as pynput_mouse
except Exception:
    pynput_keyboard = None
    pynput_mouse = None


APP_NAME = "AutoRunnerV1"
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv else os.getcwd()
RUNTIME_STATE_FILE = os.path.join(APP_DIR, "runtime_state.json")
AUTO_SAVE_FILE = os.path.join(APP_DIR, "auto_save.json")
STARTUP_WAIT_IID = "__startup_wait__"
HOTKEY_STARTUP = "__startup__"


def format_hotkey(hotkey):
    if not hotkey:
        return "(없음)"
    if hotkey == HOTKEY_STARTUP:
        return "부팅시"
    parts = hotkey.split("+")
    display = []
    for p in parts:
        if p == "ctrl":
            display.append("Ctrl")
        elif p == "alt":
            display.append("Alt")
        elif p == "shift":
            display.append("Shift")
        elif p.startswith("mouse"):
            display.append(f"마우스{p[5:]}")
        elif len(p) <= 3:
            display.append(p.upper())
        else:
            display.append(p.capitalize())
    return "+".join(display)


class WindowPositionDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.result = None
        self.countdown_active = False
        self.remaining = 5

        self.title("창 위치")
        self.geometry("560x310")
        self.resizable(False, False)
        self.transient(master)

        self.var_title = tk.StringVar()
        self.var_x = tk.StringVar()
        self.var_y = tk.StringVar()
        self.var_w = tk.StringVar()
        self.var_h = tk.StringVar()
        self.status_var = tk.StringVar(value="대기 중")

        wrap = ttk.Frame(self, padding=12)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="창 이름").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(wrap, textvariable=self.var_title, width=58).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(wrap, text="X").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(wrap, textvariable=self.var_x, width=22).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(wrap, text="Y").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(wrap, textvariable=self.var_y, width=22).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(wrap, text="가로").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(wrap, textvariable=self.var_w, width=22).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(wrap, text="세로").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(wrap, textvariable=self.var_h, width=22).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Label(
            wrap,
            text="감지 시작을 누르면 이 창과 메인창을 최소화합니다.\n그 후 5초 뒤 활성 창의 이름 / 위치 / 크기를 자동으로 가져옵니다.",
            justify="left",
            foreground="#333333",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 4))

        ttk.Label(wrap, textvariable=self.status_var, foreground="#1a4d8f").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))

        btns = ttk.Frame(wrap)
        btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="감지 시작", command=self.start_capture_countdown, width=11).pack(side="left", padx=4)
        ttk.Button(btns, text="저장", command=self.on_save, width=11).pack(side="left", padx=4)
        ttk.Button(btns, text="취소", command=self.on_cancel, width=11).pack(side="left", padx=4)

        wrap.columnconfigure(1, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.center_on_screen()
        self.grab_set()

    def center_on_screen(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}")

    def minimize_own_windows(self):
        try: self.iconify()
        except Exception: pass
        try: self.app.root.iconify()
        except Exception: pass
        self.app.minimize_console_window()

    def restore_own_windows(self):
        try:
            self.app.root.deiconify()
            self.app.root.lift()
        except Exception: pass
        try:
            self.deiconify()
            self.center_on_screen()
            self.lift()
            self.focus_force()
        except Exception: pass

    def start_capture_countdown(self):
        if not self.app.is_windows():
            self.status_var.set("창 위치 기능은 Windows에서만 지원됩니다.")
            return
        self.countdown_active = True
        self.remaining = 5
        self.status_var.set(f"{self.remaining}초 뒤 활성 창 정보를 가져옵니다...")
        self.minimize_own_windows()
        self.after(1000, self._countdown_tick)

    def _countdown_tick(self):
        if not self.countdown_active:
            return
        self.remaining -= 1
        if self.remaining > 0:
            self.status_var.set(f"{self.remaining}초 뒤 활성 창 정보를 가져옵니다...")
            self.after(1000, self._countdown_tick)
            return
        info = self.app.get_foreground_window_info()
        self.countdown_active = False
        self.restore_own_windows()
        if info and (info.get("title") or "").strip():
            self.fill_from_window_info(info)
            self.status_var.set("활성 창 정보를 가져왔습니다. 필요하면 수정 후 저장하세요.")
        else:
            self.status_var.set("활성 창 정보를 가져오지 못했습니다. 다시 시도하세요.")

    def fill_from_window_info(self, info):
        self.var_title.set(info.get("title", ""))
        self.var_x.set(str(info.get("x", "")))
        self.var_y.set(str(info.get("y", "")))
        self.var_w.set(str(info.get("w", "")))
        self.var_h.set(str(info.get("h", "")))

    def on_save(self):
        title = self.var_title.get().strip()
        if not title:
            messagebox.showwarning("알림", "창 이름을 입력하세요.", parent=self)
            return
        try:
            x = int(float(self.var_x.get().strip()))
            y = int(float(self.var_y.get().strip()))
            w = int(float(self.var_w.get().strip()))
            h = int(float(self.var_h.get().strip()))
        except Exception:
            messagebox.showwarning("알림", "위치와 크기는 숫자로 입력하세요.", parent=self)
            return
        if w <= 0 or h <= 0:
            messagebox.showwarning("알림", "가로/세로는 1 이상이어야 합니다.", parent=self)
            return
        self.result = {"title": title, "x": x, "y": y, "w": w, "h": h}
        self.destroy()

    def on_cancel(self):
        self.countdown_active = False
        self.restore_own_windows()
        self.result = None
        self.destroy()


class TextInputDialog(tk.Toplevel):
    def __init__(self, master, initial=""):
        super().__init__(master)
        self.result = None
        self.title("텍스트 입력")
        self.resizable(True, True)
        self.transient(master)

        wrap = ttk.Frame(self, padding=12)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="입력할 텍스트를 작성하세요.\nEnter: 줄바꿈  /  Ctrl+Enter: 확인", justify="left").pack(anchor="w", pady=(0, 6))

        self.text_widget = tk.Text(wrap, height=6, wrap="word", undo=True)
        self.text_widget.pack(fill="both", expand=True)
        if initial:
            self.text_widget.insert("1.0", initial)
            self.text_widget.mark_set("insert", "end")

        btns = ttk.Frame(wrap)
        btns.pack(anchor="e", pady=(8, 0))
        ttk.Button(btns, text="확인", command=self.on_ok, width=8).pack(side="left", padx=4)
        ttk.Button(btns, text="취소", command=self.on_cancel, width=8).pack(side="left", padx=4)

        self.text_widget.bind("<Control-Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.update_idletasks()
        w, h = 420, 220
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.grab_set()
        self.text_widget.focus_set()

    def on_ok(self):
        self.result = self.text_widget.get("1.0", "end-1c")
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class HotkeyCaptureDialog(tk.Toplevel):
    """단축키 입력 캡처 다이얼로그 — 열리면 바로 캡처 시작"""
    _KEY_MAP = {
        'f1':'f1','f2':'f2','f3':'f3','f4':'f4','f5':'f5','f6':'f6',
        'f7':'f7','f8':'f8','f9':'f9','f10':'f10','f11':'f11','f12':'f12',
        'home':'home','end':'end','page_up':'pgup','page_down':'pgdn',
        'insert':'insert','delete':'delete','space':'space',
        'enter':'enter','tab':'tab','esc':'esc','backspace':'backspace',
        'up':'up','down':'down','left':'left','right':'right',
        'caps_lock':'capslock','num_lock':'numlock','scroll_lock':'scrolllock',
        'print_screen':'printscreen','pause':'pause','menu':'menu',
    }

    def __init__(self, master, current_hotkey=""):
        super().__init__(master)
        self.result = None  # None=취소, ""=없음, 그 외=단축키 문자열
        self._captured = current_hotkey
        self._pressed_mods = set()
        self._kb_listener = None

        self.title("단축키 설정")
        self.resizable(False, False)
        self.transient(master)

        wrap = ttk.Frame(self, padding=16)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="키를 입력하세요", font=("Malgun Gothic", 10)).pack(anchor="w")

        disp_frame = tk.Frame(wrap, bg="#e8eef7", relief="flat", bd=1)
        disp_frame.pack(fill="x", pady=(6, 10))
        self._display_var = tk.StringVar(value=format_hotkey(self._captured) if self._captured else "")
        tk.Label(
            disp_frame, textvariable=self._display_var,
            font=("Malgun Gothic", 16, "bold"), fg="#1a4d8f", bg="#e8eef7",
            anchor="center", height=2,
        ).pack(fill="x", padx=12)

        sep_row = ttk.Frame(wrap)
        sep_row.pack(fill="x", pady=(0, 6))
        ttk.Label(sep_row, text="마우스:", foreground="#555").pack(side="left")
        ttk.Button(sep_row, text="버튼4", command=lambda: self._set("mouse4"), width=7).pack(side="left", padx=(4, 2))
        ttk.Button(sep_row, text="버튼5", command=lambda: self._set("mouse5"), width=7).pack(side="left", padx=2)
        ttk.Button(sep_row, text="★ 부팅시 자동실행", command=lambda: self._set(HOTKEY_STARTUP)).pack(side="left", padx=(10, 0))

        btns = ttk.Frame(wrap)
        btns.pack(anchor="e", pady=(4, 0))
        ttk.Button(btns, text="없음", command=self._clear, width=6).pack(side="left", padx=3)
        ttk.Button(btns, text="확인", command=self._ok, width=8).pack(side="left", padx=3)
        ttk.Button(btns, text="취소", command=self._cancel, width=8).pack(side="left", padx=3)

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.update_idletasks()
        w, h = max(self.winfo_reqwidth(), 380), max(self.winfo_reqheight(), 180)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.grab_set()

        # 열리자마자 바로 캡처 시작
        self.after(80, self._start_capture)

    def _start_capture(self):
        if pynput_keyboard is None:
            return
        self._stop_listener()
        self._pressed_mods.clear()
        if not self._captured:
            self._display_var.set("...")
        self._kb_listener = pynput_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        self._kb_listener.start()

    def _on_press(self, key):
        mod = self._to_mod(key)
        if mod:
            self._pressed_mods.add(mod)
            return
        try:
            key_str = self._key_to_str(key)
            if not key_str or key_str == "esc":
                return
            mods = sorted(self._pressed_mods)
            combo = "+".join(mods + [key_str])
            self._stop_listener()
            self.after(0, lambda c=combo: self._set(c))
        except Exception:
            pass

    def _on_release(self, key):
        mod = self._to_mod(key)
        if mod:
            self._pressed_mods.discard(mod)

    def _to_mod(self, key):
        try:
            if key in (pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r):
                return "ctrl"
            if key in (pynput_keyboard.Key.alt, pynput_keyboard.Key.alt_l, pynput_keyboard.Key.alt_r, pynput_keyboard.Key.alt_gr):
                return "alt"
            if key in (pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r):
                return "shift"
        except Exception:
            pass
        return None

    def _key_to_str(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                return key.char.lower()
            if hasattr(key, 'name') and key.name:
                return self._KEY_MAP.get(key.name, key.name)
        except Exception:
            pass
        return ""

    def _stop_listener(self):
        if self._kb_listener:
            try: self._kb_listener.stop()
            except Exception: pass
            self._kb_listener = None

    def _set(self, hotkey):
        self._captured = hotkey
        self._display_var.set(format_hotkey(hotkey))
        # 키 등록 후 다시 캡처 대기 (다른 키로 바꾸고 싶을 때)
        self.after(50, self._start_capture)

    def _clear(self):
        self._captured = ""
        self._display_var.set("")
        self.after(50, self._start_capture)

    def _ok(self):
        self._stop_listener()
        self.result = self._captured
        self.destroy()

    def _cancel(self):
        self._stop_listener()
        self.result = None
        self.destroy()


class AutomationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("자동실행기 V1.1")
        self.root.geometry("900x980")

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.03

        # Macro storage
        self.macros = []
        self._selected_macro_id = None
        self._next_macro_id = 1

        self.current_file = None
        self.running = False
        self.worker = None
        self.current_position = None
        self._next_id = 1
        self.auto_run_after_launch = False
        self.auto_run_after_id = None
        self.runtime_state = self.load_runtime_state()
        self._startup_wait_last_toggle = 0.0

        self.recording = False
        self.recorded_steps = []
        self.record_keyboard_listener = None
        self.record_mouse_listener = None
        self.record_text_buffer = ""
        self.record_ignore_until = 0.0
        self.record_last_event_time = None
        self.record_last_move_time = 0.0
        self.record_last_move_pos = None
        self.record_last_click = None
        self.record_move_min_interval = 0.1
        self.record_move_min_distance = 8
        self.record_text_flush_gap = 1.8
        self.record_double_click_window = 0.35
        self.record_wait_min_gap = 0.04

        self.stop_hotkey = self.runtime_state.get("stop_hotkey", "f11")
        self.hotkey_listener = None
        self.mouse_hotkey_listener = None
        self._global_mods = set()
        self._hotkey_capture_active = False
        self._stop_key_label_var = None
        self.stop_event = threading.Event()
        self.drag_anchor_iid = None

        self.side_button_width = 14
        self.side_panel_width = 230

        self.synthetic_group_ids = set()
        self.context_target_iid = None

        self.btn_save = None
        self.btn_run = None
        self.btn_stop = None
        self.btn_clear = None
        self.btn_rec_start = None
        self.btn_rec_stop = None
        self._recording_overlay = None
        self._step_btns = []
        self._other_btns = []
        self._macro_edit_btns = []
        self._admin_warned = False

        self._build_ui()
        self.bind_shortcuts()
        self.start_global_hotkey_listener()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_runtime_state_on_launch()

    # ── steps property ──────────────────────────────────────────────
    @property
    def steps(self):
        m = self._get_current_macro()
        return m["steps"] if m else []

    @steps.setter
    def steps(self, value):
        m = self._get_current_macro()
        if m is not None:
            m["steps"] = value

    # ── Macro helpers ────────────────────────────────────────────────
    def _get_current_macro(self):
        for m in self.macros:
            if m["id"] == self._selected_macro_id:
                return m
        return None

    def _find_macro_by_hotkey(self, hotkey):
        for m in self.macros:
            if m.get("hotkey") == hotkey:
                return m
        return None

    def _init_default_macros(self):
        self.macros = []
        self._selected_macro_id = None

    def next_macro_id(self):
        val = f"macro_{self._next_macro_id}"
        self._next_macro_id += 1
        return val

    def _migrate_v1_data(self, data):
        steps = data.get("steps", [])
        macro = {
            "id": self.next_macro_id(),
            "name": "시작 자동",
            "hotkey": HOTKEY_STARTUP,
            "startup_wait_enabled": True,
            "steps": steps,
        }
        return {"version": 2, "macros": [macro]}

    # ── UI build ─────────────────────────────────────────────────────
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        top = ttk.Frame(main)
        top.pack(fill="x", pady=(0, 8))

        self.btn_save = ttk.Button(top, text="저장", command=self.save_steps, width=8)
        self.btn_save.pack(side="left", padx=3)
        btn_load = ttk.Button(top, text="불러오기", command=self.load_steps, width=8)
        btn_load.pack(side="left", padx=3)
        self.btn_run = ttk.Button(top, text="실행(F7)", command=self.start_run, width=10)
        self.btn_run.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(top, text="중지(F8)", command=self.stop_run, width=10)
        self.btn_stop.pack(side="left", padx=3)
        self.btn_clear = ttk.Button(top, text="목록초기화", command=self.clear_all_steps, width=10)
        self.btn_clear.pack(side="left", padx=3)
        self._step_btns = [self.btn_save, self.btn_run, self.btn_stop, self.btn_clear]

        self.startup_var = tk.BooleanVar(value=False)
        startup_cb = ttk.Checkbutton(top, text="컴퓨터 시작시 자동실행", variable=self.startup_var, command=self.toggle_startup)
        startup_cb.pack(side="left", padx=12)
        self._other_btns = [btn_load, startup_cb]

        body = ttk.Frame(main)
        body.pack(fill="both", expand=True)

        # ── Left: macro list panel ───────────────────────────────────
        macro_outer = ttk.LabelFrame(body, text="매크로 목록", padding=8)
        macro_outer.pack(side="left", fill="y", padx=(0, 8))
        macro_outer.pack_propagate(False)
        macro_outer.configure(width=178)

        lb_wrap = ttk.Frame(macro_outer)
        lb_wrap.pack(fill="both", expand=True)

        self.macro_listbox = tk.Listbox(
            lb_wrap, selectmode="single", font=("Malgun Gothic", 9),
            activestyle="dotbox", width=20,
        )
        lb_scroll = ttk.Scrollbar(lb_wrap, orient="vertical", command=self.macro_listbox.yview)
        self.macro_listbox.configure(yscrollcommand=lb_scroll.set)
        self.macro_listbox.pack(side="left", fill="both", expand=True)
        lb_scroll.pack(side="right", fill="y")
        self.macro_listbox.bind("<<ListboxSelect>>", self.on_macro_select)

        mb = ttk.Frame(macro_outer)
        mb.pack(fill="x", pady=(6, 0))
        btn_add_macro = ttk.Button(mb, text="+ 추가", command=self.add_macro, width=8)
        btn_add_macro.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        btn_del_macro = ttk.Button(mb, text="× 삭제", command=self.delete_macro, width=8)
        btn_del_macro.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        btn_ren_macro = ttk.Button(mb, text="✏ 이름", command=self.rename_macro, width=8)
        btn_ren_macro.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        btn_key_macro = ttk.Button(mb, text="⌨ 단축키", command=self.assign_hotkey, width=8)
        btn_key_macro.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        mb.columnconfigure(0, weight=1)
        mb.columnconfigure(1, weight=1)
        self._macro_edit_btns = [btn_del_macro, btn_ren_macro, btn_key_macro]

        # ── Center: step tree ────────────────────────────────────────
        center = ttk.Frame(body)
        center.pack(side="left", fill="both", expand=True, padx=(0, 10))

        ttk.Label(center, text="동작 리스트").pack(anchor="w")

        tree_wrap = ttk.Frame(center)
        tree_wrap.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_wrap, columns=("label",), show="tree", selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.bind("<ButtonPress-1>", self.on_tree_press, add="+")
        self.tree.bind("<B1-Motion>", self.on_tree_drag_select, add="+")
        self.tree.bind("<Double-1>", self.on_tree_double_click, add="+")
        self.tree.bind("<Button-3>", self.on_tree_right_click, add="+")

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="수정", command=self.context_edit_selected)
        self.context_menu.add_command(label="삭제", command=self.context_delete_selected)

        # ── Right: add/edit buttons ──────────────────────────────────
        right = ttk.Frame(body, width=self.side_panel_width)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        button_box = ttk.LabelFrame(right, text="추가", padding=10)
        button_box.pack(fill="x")

        rec_style = ttk.Style()
        rec_style.configure("RecStart.TButton", foreground="#cc2222")

        self.btn_rec_start = ttk.Button(
            button_box, text="● 녹화시작  F9",
            command=self.start_recording,
            style="RecStart.TButton",
            width=self.side_button_width,
        )
        self.btn_rec_start.grid(row=0, column=0, sticky="ew", pady=3)

        self.btn_rec_stop = ttk.Button(
            button_box, text="■ 녹화종료  F10",
            command=self.stop_recording,
            state="disabled",
            width=self.side_button_width,
        )
        self.btn_rec_stop.grid(row=1, column=0, sticky="ew", pady=3)

        add_buttons = [
            ("마우스 이동", self.add_move),
            ("좌클릭", self.add_left_click),
            ("우클릭", self.add_right_click),
            ("더블클릭", self.add_double_click),
            ("텍스트입력", self.add_text_input),
            ("대기", self.add_wait),
            ("창위치 변경", self.add_window_position),
            ("종료", self.add_exit),
            ("반복", self.add_repeat),
        ]
        for i, (label, cmd) in enumerate(add_buttons):
            btn = ttk.Button(button_box, text=label, command=cmd, width=self.side_button_width)
            btn.grid(row=i + 2, column=0, sticky="ew", pady=3)
            self._other_btns.append(btn)
        button_box.columnconfigure(0, weight=1)

        stop_key_box = ttk.LabelFrame(right, text="매크로 종료 키", padding=8)
        stop_key_box.pack(fill="x", pady=(8, 0))
        sk_row = ttk.Frame(stop_key_box)
        sk_row.pack(fill="x")
        self._stop_key_label_var = tk.StringVar(value=format_hotkey(self.stop_hotkey))
        ttk.Label(sk_row, textvariable=self._stop_key_label_var,
                  foreground="#1a4d8f", font=("Malgun Gothic", 9, "bold"), width=10).pack(side="left")
        ttk.Button(sk_row, text="변경", command=self.change_stop_hotkey, width=5).pack(side="right")
        ttk.Label(stop_key_box, text="F8도 항상 중지", foreground="#888",
                  font=("Malgun Gothic", 8)).pack(anchor="w")

        edit_box = ttk.LabelFrame(right, text="편집", padding=10)
        edit_box.pack(fill="x", pady=(8, 0))
        for label, cmd in [("↑", self.move_up), ("↓", self.move_down), ("복제", self.duplicate_selected), ("삭제(Del)", self.delete_selected)]:
            btn = ttk.Button(edit_box, text=label, command=cmd, width=self.side_button_width)
            btn.pack(fill="x", pady=3)
            self._other_btns.append(btn)

        tip_box = ttk.LabelFrame(right, text="사용 방법", padding=10)
        tip_box.pack(fill="both", expand=True, pady=(10, 0))
        tip_scroll = ttk.Scrollbar(tip_box, orient="vertical")
        tip_scroll.pack(side="right", fill="y")
        self.tip = tk.Text(tip_box, height=26, wrap="word", yscrollcommand=tip_scroll.set)
        self.tip.pack(side="left", fill="both", expand=True)
        tip_scroll.config(command=self.tip.yview)
        self.tip.insert(
            "1.0",
            "1) 왼쪽 매크로 목록에서 매크로를 선택하세요.\n\n"
            "2) [+ 추가]로 새 매크로를 만들고 [⌨ 단축키]로 키를 지정하세요.\n\n"
            "3) 부팅시 자동실행은 단축키 설정에서 '부팅시' 옵션을 선택하세요.\n\n"
            "4) 실행 F7 / 중지 F8 또는 종료키 / 녹화 F9~F10 / 삭제 Del\n\n"
            "5) 대기 / 마우스이동 / 텍스트입력은 더블클릭으로 수정 가능합니다.\n\n"
            "6) 종료 항목에 도달하면 자동실행기 프로그램 자체가 종료됩니다.\n\n"
            "7) 반복: 지정 횟수만큼 처음으로 돌아갑니다.\n   횟수 0 = 무한 반복 (종료 키로만 중단).\n\n"
            "8) 단축키로 매크로 실행 시 이미 실행 중이면 무시됩니다."
        )
        self.tip.configure(state="disabled")

        log_box = ttk.LabelFrame(main, text="로그", padding=10)
        log_box.pack(fill="x", pady=(10, 0))
        self.log_text = tk.Text(log_box, height=10)
        self.log_text.pack(fill="x")

    # ── Macro management ─────────────────────────────────────────────
    def refresh_macro_list(self):
        self.macro_listbox.delete(0, tk.END)
        sel_idx = 0
        for i, macro in enumerate(self.macros):
            name = macro.get("name", f"매크로 {i+1}")
            hk = format_hotkey(macro.get("hotkey", ""))
            self.macro_listbox.insert(tk.END, f"{name}  [{hk}]")
            if macro["id"] == self._selected_macro_id:
                sel_idx = i
        if self.macros:
            self.macro_listbox.selection_clear(0, tk.END)
            self.macro_listbox.selection_set(sel_idx)
            self.macro_listbox.see(sel_idx)
        self._update_macro_btn_states()

    def _update_macro_btn_states(self):
        has = self._get_current_macro() is not None and not self.recording
        for b in self._macro_edit_btns:
            b.config(state="normal" if has else "disabled")

    def on_macro_select(self, event):
        sel = self.macro_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.macros):
            self._selected_macro_id = self.macros[idx]["id"]
            self.refresh_tree()
            self.update_button_states()

    def add_macro(self):
        name = simpledialog.askstring("새 매크로", "매크로 이름:", initialvalue="새 매크로", parent=self.root)
        if name is None:
            return
        macro = {
            "id": self.next_macro_id(),
            "name": name.strip() or "새 매크로",
            "hotkey": "",
            "steps": [],
        }
        self.macros.append(macro)
        self._selected_macro_id = macro["id"]
        self.refresh_macro_list()
        self.refresh_tree()
        self.log(f"매크로 추가: {macro['name']}")

    def delete_macro(self):
        macro = self._get_current_macro()
        if not macro:
            return
        name = macro.get("name", "")
        if not messagebox.askyesno("확인", f"'{name}' 매크로를 삭제할까요?"):
            return
        self.macros.remove(macro)
        if self.macros:
            self._selected_macro_id = self.macros[0]["id"]
        else:
            self._selected_macro_id = None
        self.refresh_macro_list()
        self.refresh_tree()
        self.log(f"매크로 삭제: {name}")

    def rename_macro(self):
        macro = self._get_current_macro()
        if not macro:
            return
        name = simpledialog.askstring("이름 변경", "새 이름:", initialvalue=macro.get("name", ""), parent=self.root)
        if name is None:
            return
        macro["name"] = name.strip() or macro.get("name", "")
        self.refresh_macro_list()
        self.log(f"이름 변경: {macro['name']}")

    def assign_hotkey(self):
        macro = self._get_current_macro()
        if not macro:
            return
        self._hotkey_capture_active = True
        try:
            dialog = HotkeyCaptureDialog(self.root, current_hotkey=macro.get("hotkey", ""))
            self.root.wait_window(dialog)
        finally:
            self._hotkey_capture_active = False

        if dialog.result is None:
            return  # 취소

        new_hk = dialog.result

        # 중복 체크
        if new_hk:
            for m in self.macros:
                if m["id"] != macro["id"] and m.get("hotkey") == new_hk:
                    messagebox.showwarning(
                        "중복",
                        f"'{format_hotkey(new_hk)}'는 이미 '{m.get('name','')}' 매크로에 할당되어 있습니다.",
                        parent=self.root,
                    )
                    return

        macro["hotkey"] = new_hk
        if new_hk == HOTKEY_STARTUP and "startup_wait_enabled" not in macro:
            macro["startup_wait_enabled"] = True

        self.refresh_macro_list()
        self.refresh_tree()
        self.log(f"단축키 설정: {macro['name']} → {format_hotkey(new_hk)}")

    def change_stop_hotkey(self):
        self._hotkey_capture_active = True
        try:
            dialog = HotkeyCaptureDialog(self.root, current_hotkey=self.stop_hotkey)
            self.root.wait_window(dialog)
        finally:
            self._hotkey_capture_active = False
        if dialog.result is None or not dialog.result:
            return
        if dialog.result == HOTKEY_STARTUP:
            messagebox.showwarning("알림", "부팅시는 종료 키로 설정할 수 없습니다.", parent=self.root)
            return
        self.stop_hotkey = dialog.result
        self.save_runtime_state()
        if self._stop_key_label_var:
            self._stop_key_label_var.set(format_hotkey(self.stop_hotkey))
        self.log(f"종료 키 변경: {format_hotkey(self.stop_hotkey)}")

    def trigger_macro(self, macro):
        if self.running or self.recording:
            return
        if not macro.get("steps"):
            return
        self.start_run(macro=macro)

    # ── Global hotkey listener ───────────────────────────────────────
    def bind_shortcuts(self):
        self.root.bind("<F7>", lambda e: self.start_run())
        self.root.bind("<F8>", lambda e: self.stop_run())
        self.root.bind("<F9>", lambda e: self.start_recording())
        self.root.bind("<F10>", lambda e: self.stop_recording())
        self.root.bind("<Delete>", lambda e: self.delete_selected())

    def start_global_hotkey_listener(self):
        if pynput_keyboard is None:
            return
        try:
            self._global_mods = set()
            self.hotkey_listener = pynput_keyboard.Listener(
                on_press=self.on_global_key_press,
                on_release=self.on_global_key_release,
            )
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
        except Exception:
            self.hotkey_listener = None

        if pynput_mouse is None:
            return
        try:
            self.mouse_hotkey_listener = pynput_mouse.Listener(
                on_click=self.on_global_mouse_click,
            )
            self.mouse_hotkey_listener.daemon = True
            self.mouse_hotkey_listener.start()
        except Exception:
            self.mouse_hotkey_listener = None

    def _pynput_key_to_mod(self, key):
        try:
            if key in (pynput_keyboard.Key.ctrl, pynput_keyboard.Key.ctrl_l, pynput_keyboard.Key.ctrl_r):
                return "ctrl"
            if key in (pynput_keyboard.Key.alt, pynput_keyboard.Key.alt_l, pynput_keyboard.Key.alt_r, pynput_keyboard.Key.alt_gr):
                return "alt"
            if key in (pynput_keyboard.Key.shift, pynput_keyboard.Key.shift_l, pynput_keyboard.Key.shift_r):
                return "shift"
        except Exception:
            pass
        return None

    def _build_pynput_combo(self, key):
        _NAME_MAP = {
            'f1':'f1','f2':'f2','f3':'f3','f4':'f4','f5':'f5','f6':'f6',
            'f7':'f7','f8':'f8','f9':'f9','f10':'f10','f11':'f11','f12':'f12',
            'home':'home','end':'end','page_up':'pgup','page_down':'pgdn',
            'insert':'insert','delete':'delete','space':'space',
            'enter':'enter','tab':'tab','esc':'esc','backspace':'backspace',
            'up':'up','down':'down','left':'left','right':'right',
            'caps_lock':'capslock','num_lock':'numlock','scroll_lock':'scrolllock',
            'print_screen':'printscreen','pause':'pause','menu':'menu',
        }
        try:
            if hasattr(key, 'char') and key.char:
                key_str = key.char.lower()
            elif hasattr(key, 'name') and key.name:
                key_str = _NAME_MAP.get(key.name, key.name)
            else:
                return ""
            mods = sorted(self._global_mods)
            return "+".join(mods + [key_str]) if mods else key_str
        except Exception:
            return ""

    def on_global_key_press(self, key):
        if self._hotkey_capture_active:
            return
        try:
            mod = self._pynput_key_to_mod(key)
            if mod:
                self._global_mods.add(mod)
                return

            combo = self._build_pynput_combo(key)

            # F8 항상 중지 + 사용자 지정 종료 키
            if key == pynput_keyboard.Key.f8 or (combo and combo == self.stop_hotkey):
                self.root.after(0, self.stop_run)
                return

            if key == pynput_keyboard.Key.f9:
                self.root.after(0, self.start_recording)
                return
            elif key == pynput_keyboard.Key.f10:
                self.root.after(0, self.stop_recording)
                return

            # 실행 중이거나 녹화 중이면 큐 자체를 쌓지 않음
            # (큐에 쌓아두면 실행 종료 직후 남은 콜백이 다시 트리거됨)
            if self.running or self.recording:
                return

            if combo:
                macro = self._find_macro_by_hotkey(combo)
                if macro and macro.get("hotkey") != HOTKEY_STARTUP:
                    self.root.after(0, lambda m=macro: self.trigger_macro(m))
        except Exception:
            pass

    def on_global_key_release(self, key):
        mod = self._pynput_key_to_mod(key)
        if mod:
            self._global_mods.discard(mod)

    def on_global_mouse_click(self, x, y, button, pressed):
        if not pressed or self.running or self.recording or self._hotkey_capture_active:
            return
        try:
            button_str = str(button)
            if "x1" in button_str:
                hotkey = "mouse4"
            elif "x2" in button_str:
                hotkey = "mouse5"
            else:
                return
            mods = sorted(self._global_mods)
            if mods:
                hotkey = "+".join(mods) + "+" + hotkey
            macro = self._find_macro_by_hotkey(hotkey)
            if macro and macro.get("hotkey") != HOTKEY_STARTUP:
                self.root.after(0, lambda m=macro: self.trigger_macro(m))
        except Exception:
            pass

    # ── Tree helpers ─────────────────────────────────────────────────
    def visible_items(self):
        result = []
        def walk(parent=""):
            for iid in self.tree.get_children(parent):
                result.append(iid)
                if self.tree.item(iid, "open"):
                    walk(iid)
        walk("")
        return result

    def is_synthetic_group(self, iid):
        return iid in self.synthetic_group_ids

    def on_tree_press(self, event):
        iid = self.tree.identify_row(event.y)
        if iid == STARTUP_WAIT_IID:
            now = time.time()
            if now - self._startup_wait_last_toggle < 0.3:
                return
            self._startup_wait_last_toggle = now
            macro = self._get_current_macro()
            if macro:
                macro["startup_wait_enabled"] = not macro.get("startup_wait_enabled", True)
                self.save_runtime_state()
                check = "[✓]" if macro["startup_wait_enabled"] else "[ ]"
                self.tree.item(STARTUP_WAIT_IID, text=f"{check} 윈도우 시작 대기 1분")
            return
        if iid:
            self.drag_anchor_iid = iid

    def on_tree_drag_select(self, event):
        if not self.drag_anchor_iid:
            return
        current = self.tree.identify_row(event.y)
        if not current:
            return
        visible = self.visible_items()
        if self.drag_anchor_iid in visible and current in visible:
            a, b = visible.index(self.drag_anchor_iid), visible.index(current)
            lo, hi = sorted([a, b])
            self.tree.selection_set(visible[lo:hi + 1])

    def on_tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or self.is_synthetic_group(iid):
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.edit_selected_item()

    def on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.context_target_iid = iid
        if self.is_synthetic_group(iid):
            return
        found = self.find_container(iid)
        if not found:
            return
        _, _, item = found
        can_edit = item["type"] in ("WAIT", "MOVE", "TEXT_INPUT")
        self.context_menu.entryconfig("수정", state="normal" if can_edit else "disabled")
        self.context_menu.entryconfig("삭제", state="normal")
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def context_edit_selected(self):
        self.edit_selected_item()

    def context_delete_selected(self):
        self.delete_selected()

    def edit_selected_item(self):
        selected_id = self.get_selected_id()
        if not selected_id or self.is_synthetic_group(selected_id):
            return
        found = self.find_container(selected_id)
        if not found:
            return
        _, _, item = found
        if item["type"] == "WAIT":
            val = simpledialog.askfloat("대기 수정", "대기 시간(초):", initialvalue=float(item.get("seconds", 1.0)), minvalue=0.0, parent=self.root)
            if val is None:
                return
            item["seconds"] = float(val)
            self.refresh_tree(select_id=selected_id)
            self.log(f"대기 수정: {item['seconds']}초")
            return
        if item["type"] == "MOVE":
            nx = simpledialog.askinteger("이동 수정", "X 좌표:", initialvalue=int(item.get("x", 0)), parent=self.root)
            if nx is None:
                return
            ny = simpledialog.askinteger("이동 수정", "Y 좌표:", initialvalue=int(item.get("y", 0)), parent=self.root)
            if ny is None:
                return
            item["x"], item["y"] = int(nx), int(ny)
            self.refresh_tree(select_id=selected_id)
            self.log(f"이동 수정: ({item['x']}, {item['y']})")
            return
        if item["type"] == "TEXT_INPUT":
            new_text = self.ask_input_text(initial=item.get("text", ""))
            if new_text is None:
                return
            item["text"] = new_text
            self.refresh_tree(select_id=selected_id)
            self.log("텍스트입력 수정")
            return

    # ── Log ──────────────────────────────────────────────────────────
    def log(self, msg):
        self.root.after(0, lambda m=msg: self._append_log(m))

    def _append_log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")

    # ── Runtime state ────────────────────────────────────────────────
    def default_runtime_state(self):
        return {
            "last_file": None,
            "auto_run_on_launch": True,
            "startup_enabled": True,
            "launch_delay_sec": 0.0,
            "startup_wait_enabled": True,
            "stop_hotkey": "f11",
        }

    def load_runtime_state(self):
        state = self.default_runtime_state()
        try:
            if os.path.exists(RUNTIME_STATE_FILE):
                with open(RUNTIME_STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    state.update(loaded)
        except Exception:
            pass
        return state

    def save_runtime_state(self):
        startup_macro = self._find_macro_by_hotkey(HOTKEY_STARTUP)
        state = {
            "last_file": self.current_file,
            "auto_run_on_launch": bool(startup_macro and startup_macro.get("steps")),
            "startup_enabled": bool(self.startup_var.get()),
            "launch_delay_sec": 0.0,
            "startup_wait_enabled": startup_macro.get("startup_wait_enabled", True) if startup_macro else True,
            "stop_hotkey": self.stop_hotkey,
        }
        self.runtime_state = state
        try:
            with open(RUNTIME_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── Admin / startup registration ─────────────────────────────────
    def is_admin(self):
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def apply_runtime_state_on_launch(self):
        startup_enabled = bool(self.runtime_state.get("startup_enabled", True))
        if sys.platform == "win32":
            if startup_enabled:
                self.register_startup()
            else:
                self.unregister_startup()
        self.startup_var.set(startup_enabled)

        last_file = self.runtime_state.get("last_file")
        if not last_file and os.path.exists(AUTO_SAVE_FILE):
            last_file = AUTO_SAVE_FILE
        if last_file and os.path.exists(last_file):
            try:
                self.load_steps_from_path(last_file, silent=True)
                self.log(f"자동 불러오기: {last_file}")
            except Exception as e:
                self.log(f"자동 불러오기 실패: {e}")
                self._init_default_macros()
                self.refresh_macro_list()
                self.refresh_tree()
        else:
            self._init_default_macros()
            self.refresh_macro_list()
            self.refresh_tree()

        startup_macro = self._find_macro_by_hotkey(HOTKEY_STARTUP)
        if startup_macro and startup_macro.get("steps"):
            self.auto_run_after_launch = True
            self.log("자동 실행 예약")
            self.auto_run_after_id = self.root.after(100, self.auto_start_if_needed)

    def auto_start_if_needed(self):
        self.auto_run_after_id = None
        startup_macro = self._find_macro_by_hotkey(HOTKEY_STARTUP)
        if (self.auto_run_after_launch and not self.running
                and startup_macro and startup_macro.get("steps")
                and not self.stop_event.is_set()):
            self.log("자동 실행 시작")
            self.start_run(macro=startup_macro)

    # ── ID helpers ───────────────────────────────────────────────────
    def next_id(self):
        val = f"node_{self._next_id}"
        self._next_id += 1
        return val

    def next_group_id(self):
        val = f"group_{self._next_id}"
        self._next_id += 1
        return val

    def ensure_ids(self, items):
        for item in items:
            if "id" not in item:
                item["id"] = self.next_id()
            else:
                self._sync_next_id_for(item["id"])

    def _sync_next_id_for(self, iid):
        for prefix in ("node_", "group_"):
            if iid.startswith(prefix):
                try:
                    num = int(iid[len(prefix):])
                    if num >= self._next_id:
                        self._next_id = num + 1
                except ValueError:
                    pass

    # ── Dialogs ──────────────────────────────────────────────────────
    def ask_wait_seconds(self, default=1.0):
        val = simpledialog.askfloat("대기", "대기 시간(초):", initialvalue=default, minvalue=0.0, parent=self.root)
        return None if val is None else float(val)

    def ask_input_text(self, initial=""):
        dialog = TextInputDialog(self.root, initial=initial)
        self.root.wait_window(dialog)
        return dialog.result

    # ── Utilities ────────────────────────────────────────────────────
    def distance(self, a, b):
        return ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5

    def is_flow_step(self, step):
        return step["type"] in ("MOVE", "WAIT")

    def minimize_console_window(self):
        if sys.platform != "win32":
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32.GetConsoleWindow.argtypes = []
            kernel32.GetConsoleWindow.restype = ctypes.c_void_p
            user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.ShowWindow.restype = ctypes.c_bool
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 6)
        except Exception:
            pass

    def minimize_app_windows(self):
        try: self.root.after(0, self.root.iconify)
        except Exception: pass
        self.minimize_console_window()

    def is_windows(self):
        return sys.platform == "win32"

    def get_user32(self):
        return ctypes.WinDLL("user32", use_last_error=True)

    def get_foreground_window_info(self):
        if not self.is_windows():
            return None
        try:
            user32 = self.get_user32()
            HWND = ctypes.c_void_p
            BOOL = ctypes.c_bool

            class RECT(ctypes.Structure):
                _fields_ = [("left",ctypes.c_long),("top",ctypes.c_long),("right",ctypes.c_long),("bottom",ctypes.c_long)]

            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = HWND
            user32.GetWindowTextLengthW.argtypes = [HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
            user32.GetWindowRect.restype = BOOL

            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(max(1, length+1))
            user32.GetWindowTextW(hwnd, buf, max(1, length+1))
            title = buf.value.strip()
            rect = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            hwnd_value = ctypes.cast(hwnd, ctypes.c_void_p).value or 0
            return {"hwnd": int(hwnd_value), "title": title, "x": int(rect.left), "y": int(rect.top), "w": int(rect.right-rect.left), "h": int(rect.bottom-rect.top)}
        except Exception as e:
            self.log(f"전경 창 정보 읽기 실패: {e}")
            return None

    def enum_windows(self):
        if not self.is_windows():
            return []
        try:
            user32 = self.get_user32()
            BOOL = ctypes.c_bool
            HWND = ctypes.c_void_p
            LPARAM = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

            class RECT(ctypes.Structure):
                _fields_ = [("left",ctypes.c_long),("top",ctypes.c_long),("right",ctypes.c_long),("bottom",ctypes.c_long)]

            EnumWindowsProc = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
            user32.EnumWindows.argtypes = [EnumWindowsProc, LPARAM]
            user32.EnumWindows.restype = BOOL
            user32.IsWindowVisible.argtypes = [HWND]
            user32.IsWindowVisible.restype = BOOL
            user32.GetWindowTextLengthW.argtypes = [HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
            user32.GetWindowRect.restype = BOOL
            windows = []

            @EnumWindowsProc
            def callback(hwnd, lparam):
                try:
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    rect = RECT()
                    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        return True
                    length = user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(max(1, length+1))
                    user32.GetWindowTextW(hwnd, buf, max(1, length+1))
                    title = buf.value.strip()
                    hwnd_value = ctypes.cast(hwnd, ctypes.c_void_p).value or 0
                    windows.append({"hwnd": int(hwnd_value), "title": title, "x": int(rect.left), "y": int(rect.top), "w": int(rect.right-rect.left), "h": int(rect.bottom-rect.top)})
                except Exception:
                    pass
                return True

            user32.EnumWindows(callback, 0)
            return windows
        except Exception as e:
            self.log(f"창 열거 실패: {e}")
            return []

    def normalize_title(self, text):
        text = (text or "").strip().lower()
        return re.sub(r"\s+", " ", text)

    def compress_title(self, text):
        text = self.normalize_title(text)
        return re.sub(r"[\s\\/|_\-\[\]\(\)\.:]+", "", text)

    def split_title_parts(self, text):
        raw = re.split(r"[\\/|_\-\[\]\(\)\.:]+", (text or "").strip())
        parts = [i.strip() for i in raw if i.strip()]
        parts.sort(key=len, reverse=True)
        return parts

    def title_match_score(self, saved_title, actual_title):
        saved_raw = (saved_title or "").strip()
        actual_raw = (actual_title or "").strip()
        if not saved_raw or not actual_raw:
            return 0.0
        saved_norm = self.normalize_title(saved_raw)
        actual_norm = self.normalize_title(actual_raw)
        saved_comp = self.compress_title(saved_raw)
        actual_comp = self.compress_title(actual_raw)
        if saved_norm == actual_norm or saved_comp == actual_comp:
            return 1.0
        if saved_norm in actual_norm or actual_norm in saved_norm:
            return 0.9
        for part in self.split_title_parts(saved_raw):
            pn = self.normalize_title(part)
            pc = self.compress_title(part)
            if not pn:
                continue
            if pn in actual_norm or (pc and pc in actual_comp):
                return 0.8
        r1 = SequenceMatcher(None, saved_norm, actual_norm).ratio()
        r2 = SequenceMatcher(None, saved_comp, actual_comp).ratio() if saved_comp and actual_comp else 0.0
        return max(r1, r2)

    def find_window_by_title_once(self, title):
        target = (title or "").strip()
        if not target:
            return None
        windows = self.enum_windows()
        candidates = [w for w in windows if (w.get("title") or "").strip()]
        if not candidates:
            return None
        best, best_score = None, 0.0
        for win in candidates:
            score = self.title_match_score(target, win["title"])
            if score > best_score:
                best_score = score
                best = win
        return best if best and best_score >= 0.5 else None

    def find_window_by_title_retry(self, title, retries=5, interval=0.2):
        last_titles = []
        for attempt in range(retries):
            if self.stop_event.is_set():
                return None, ""
            found = self.find_window_by_title_once(title)
            if found:
                return found, None
            windows = self.enum_windows()
            last_titles = [w["title"] for w in windows if (w.get("title") or "").strip()]
            if attempt < retries - 1:
                time.sleep(interval)
        return None, ", ".join(last_titles[:10])

    def move_resize_window(self, title, x, y, w, h):
        if self.stop_event.is_set():
            return False, "중지됨"
        if not self.is_windows():
            return False, "Windows에서만 지원합니다."
        win, preview = self.find_window_by_title_retry(title, retries=5, interval=0.2)
        if not win:
            return False, f"대상 창을 찾지 못했습니다: {title} / 현재창예시: {preview or ''}"
        try:
            user32 = self.get_user32()
            HWND = ctypes.c_void_p
            BOOL = ctypes.c_bool
            user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
            user32.ShowWindow.restype = BOOL
            user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetWindowPos.restype = BOOL
            user32.SetForegroundWindow.argtypes = [HWND]
            user32.SetForegroundWindow.restype = BOOL
            hwnd = HWND(win["hwnd"])
            user32.ShowWindow(hwnd, 9)
            time.sleep(0.03)
            if self.stop_event.is_set():
                return False, "중지됨"
            ok = user32.SetWindowPos(hwnd, HWND(0), int(x), int(y), int(w), int(h), 0x0004 | 0x0040)
            time.sleep(0.03)
            user32.SetForegroundWindow(hwnd)
            if not ok:
                return False, f"창 위치/크기 변경 실패: {win['title']}"
            return True, f"{win['title']} -> ({x}, {y}, {w}, {h})"
        except Exception as e:
            return False, str(e)

    # ── Step list operations ─────────────────────────────────────────
    def clone_step(self, step):
        copied = copy.deepcopy(step)
        copied["id"] = self.next_id()
        return copied

    def find_container(self, target_id, items=None):
        if items is None:
            items = self.steps
        for index, item in enumerate(items):
            if item["id"] == target_id:
                return items, index, item
        return None

    def selected_ids(self):
        return [iid for iid in self.tree.selection() if not self.is_synthetic_group(iid)]

    def get_selected_id(self):
        focus = self.tree.focus()
        if focus and not self.is_synthetic_group(focus):
            return focus
        sel = self.selected_ids()
        return sel[-1] if sel else None

    def insert_step(self, step):
        selected_id = self.get_selected_id()
        if not selected_id:
            self.steps.append(step)
            self.refresh_tree(select_id=step["id"])
            return
        found = self.find_container(selected_id)
        if not found:
            self.steps.append(step)
            self.refresh_tree(select_id=step["id"])
            return
        container, index, item = found
        if item["type"] == "EXIT":
            container.insert(index, step)
        else:
            container.insert(index + 1, step)
        self.refresh_tree(select_id=step["id"])

    def clear_all_steps(self):
        macro = self._get_current_macro()
        if not macro or not macro.get("steps"):
            return
        if not messagebox.askyesno("확인", "이 매크로의 동작 리스트 전체를 초기화할까요?"):
            return
        macro["steps"] = []
        self.refresh_tree()
        self.log("동작 리스트 초기화 완료")

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        deleted = 0
        for selected_id in sorted(ids, key=lambda x: len(self.tree.get_children(x)), reverse=True):
            found = self.find_container(selected_id)
            if not found:
                continue
            container, index, item = found
            del container[index]
            deleted += 1
        self.refresh_tree()
        if deleted:
            self.log(f"{deleted}개 항목 삭제")

    def duplicate_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        for selected_id in reversed(ids):
            found = self.find_container(selected_id)
            if not found:
                continue
            container, index, item = found
            container.insert(index + 1, self.clone_step(item))
        self.refresh_tree()
        self.log(f"{len(ids)}개 항목 복제")

    def move_up(self):
        selected_id = self.get_selected_id()
        if not selected_id:
            return
        found = self.find_container(selected_id)
        if not found:
            return
        container, index, item = found
        if index == 0:
            return
        container[index-1], container[index] = container[index], container[index-1]
        self.refresh_tree(select_id=selected_id)

    def move_down(self):
        selected_id = self.get_selected_id()
        if not selected_id:
            return
        found = self.find_container(selected_id)
        if not found:
            return
        container, index, item = found
        if index >= len(container) - 1:
            return
        container[index+1], container[index] = container[index], container[index+1]
        self.refresh_tree(select_id=selected_id)

    def step_label(self, step):
        t = step["type"]
        if t == "MOVE":
            return f"마우스 이동 ({step['x']}, {step['y']})"
        if t == "CLICK_LEFT":
            return "좌클릭"
        if t == "CLICK_RIGHT":
            return "우클릭"
        if t == "DOUBLE_CLICK":
            return "더블클릭"
        if t == "TEXT_INPUT":
            preview = step.get("text", "").replace("\n", " ")
            preview = preview[:20] + ("..." if len(preview) > 20 else "")
            return f"텍스트입력 [{preview}]"
        if t == "KEY_PRESS":
            return f"키입력 [{step.get('key', '')}]"
        if t == "WAIT":
            return f"대기 {step['seconds']}초"
        if t == "WINDOW_POSITION":
            return f"창 위치 [{step.get('title','')}] ({step.get('x')}, {step.get('y')}, {step.get('w')}, {step.get('h')})"
        if t == "EXIT":
            return "종료"
        if t == "LOOP":
            count = step.get("count", 0)
            return f"↩ 반복 {'무한' if count == 0 else f'{count}회'}"
        return t

    def refresh_tree(self, select_id=None):
        self.tree.delete(*self.tree.get_children())
        self.synthetic_group_ids = set()

        macro = self._get_current_macro()
        is_startup = macro and macro.get("hotkey") == HOTKEY_STARTUP

        if is_startup:
            self.tree.tag_configure("startup_wait", foreground="#1a4d8f")
            check = "[✓]" if macro.get("startup_wait_enabled", True) else "[ ]"
            try:
                self.tree.insert("", "end", iid=STARTUP_WAIT_IID, text=f"{check} 윈도우 시작 대기 1분", tags=("startup_wait",))
            except Exception:
                pass

        steps = macro["steps"] if macro else []
        for idx, item in enumerate(steps, 1):
            iid = item["id"]
            self._sync_next_id_for(iid)
            try:
                self.tree.insert("", "end", iid=iid, text=f"{idx}. {self.step_label(item)}", open=True)
            except Exception:
                new_id = self.next_id()
                item["id"] = new_id
                self.tree.insert("", "end", iid=new_id, text=f"{idx}. {self.step_label(item)}", open=True)

        if select_id and self.tree.exists(select_id):
            self.tree.selection_set(select_id)
            self.tree.focus(select_id)

        self.update_button_states()

    def update_button_states(self):
        if self.recording:
            for b in self._step_btns + self._other_btns:
                if b is not None:
                    b.config(state="disabled")
            if self.btn_rec_start:
                self.btn_rec_start.config(state="disabled")
            if self.btn_rec_stop:
                self.btn_rec_stop.config(state="normal")
            for b in self._macro_edit_btns:
                b.config(state="disabled")
        else:
            has_steps = bool(self.steps)
            for b in self._step_btns:
                if b is not None:
                    b.config(state="normal" if has_steps else "disabled")
            for b in self._other_btns:
                if b is not None:
                    b.config(state="normal" if self._get_current_macro() else "disabled")
            if self.btn_rec_start:
                self.btn_rec_start.config(state="normal" if self._get_current_macro() else "disabled")
            if self.btn_rec_stop:
                self.btn_rec_stop.config(state="disabled")
            self._update_macro_btn_states()

    # ── Add step buttons ─────────────────────────────────────────────
    def add_move(self):
        self.pick_point_for_move()

    def pick_point_for_move(self):
        self.root.withdraw()
        self.minimize_console_window()
        self.root.after(250, self._open_pick_dialog)

    def _open_pick_dialog(self):
        try:
            overlay = tk.Toplevel(self.root)
            overlay.attributes("-fullscreen", True)
            overlay.attributes("-alpha", 0.2)
            overlay.attributes("-topmost", True)
            overlay.overrideredirect(True)
            overlay.configure(bg="black")
            canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="cross")
            canvas.pack(fill="both", expand=True)
            label = tk.Label(overlay, text="위치를 지정하세요. 좌클릭 선택 / ESC 취소",
                             bg="#1f1f1f", fg="white", padx=12, pady=7, font=("Malgun Gothic", 11, "bold"))
            label.place(x=20, y=20)

            def finish(data=None):
                try: overlay.destroy()
                except Exception: pass
                self.root.deiconify()
                self.root.lift()
                if data:
                    self._add_move_after_pick(data)

            canvas.bind("<Button-1>", lambda e: finish({"x": e.x_root, "y": e.y_root}))
            overlay.bind("<Escape>", lambda e: finish(None))
            overlay.focus_force()
        except Exception:
            self.root.deiconify()

    def _add_move_after_pick(self, data):
        step = {"id": self.next_id(), "type": "MOVE", "x": data["x"], "y": data["y"]}
        self.insert_step(step)
        self.log(f"이동 추가: ({data['x']}, {data['y']})")

    def add_left_click(self):
        step = {"id": self.next_id(), "type": "CLICK_LEFT"}
        self.insert_step(step)
        self.log("좌클릭 추가")

    def add_right_click(self):
        step = {"id": self.next_id(), "type": "CLICK_RIGHT"}
        self.insert_step(step)
        self.log("우클릭 추가")

    def add_double_click(self):
        step = {"id": self.next_id(), "type": "DOUBLE_CLICK"}
        self.insert_step(step)
        self.log("더블클릭 추가")

    def add_text_input(self):
        text = self.ask_input_text()
        if text is None:
            return
        step = {"id": self.next_id(), "type": "TEXT_INPUT", "text": text}
        self.insert_step(step)
        self.log("텍스트입력 추가")

    def add_wait(self):
        seconds = self.ask_wait_seconds()
        if seconds is None:
            return
        step = {"id": self.next_id(), "type": "WAIT", "seconds": seconds}
        self.insert_step(step)
        self.log(f"대기 추가: {seconds}초")

    def add_window_position(self):
        if not self.is_windows():
            messagebox.showwarning("알림", "창 위치 기능은 Windows에서만 지원합니다.")
            return
        dialog = WindowPositionDialog(self.root, self)
        self.root.wait_window(dialog)
        if not dialog.result:
            self.log("창 위치 추가 취소")
            return
        step = {"id": self.next_id(), "type": "WINDOW_POSITION", **dialog.result}
        self.insert_step(step)
        self.log(f"창 위치 추가: {step['title']} -> ({step['x']}, {step['y']}, {step['w']}, {step['h']})")

    def add_exit(self):
        step = {"id": self.next_id(), "type": "EXIT"}
        self.insert_step(step)
        self.log("종료 추가")

    def add_repeat(self):
        count = simpledialog.askinteger(
            "반복",
            "반복 횟수를 입력하세요.\n(0 = 무한 반복, 종료 키로만 중단)",
            initialvalue=0, minvalue=0, parent=self.root,
        )
        if count is None:
            return
        step = {"id": self.next_id(), "type": "LOOP", "count": count}
        self.insert_step(step)
        self.log(f"반복 추가: {'무한' if count == 0 else f'{count}회'}")

    # ── Recording ────────────────────────────────────────────────────
    def start_recording(self):
        if self.recording:
            self.log("이미 녹화 중입니다")
            return
        if not self._get_current_macro():
            self.log("매크로를 먼저 선택하세요")
            return
        if pynput_keyboard is None or pynput_mouse is None:
            messagebox.showerror("오류", "녹화 기능을 쓰려면 pynput 설치가 필요합니다.\npy -m pip install pynput")
            return
        self.recording = True
        self.recorded_steps = []
        self.record_text_buffer = ""
        self.record_ignore_until = time.time() + 0.35
        self.record_last_event_time = None
        self.record_last_move_time = 0.0
        self.record_last_move_pos = None
        self.record_last_click = None
        self.record_mouse_listener = pynput_mouse.Listener(on_click=self.record_mouse_click)
        self.record_keyboard_listener = pynput_keyboard.Listener(on_press=self.record_key_press)
        self.record_mouse_listener.start()
        self.record_keyboard_listener.start()
        self.log("녹화 시작")
        self.update_button_states()
        self.root.after(0, self.root.iconify)
        self.root.after(100, self._show_recording_overlay)

    def stop_recording(self):
        if not self.recording:
            self.log("녹화 중이 아닙니다")
            return
        self.recording = False
        self._hide_recording_overlay()
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass
        self.flush_record_text_buffer()
        try:
            if self.record_mouse_listener:
                self.record_mouse_listener.stop()
            if self.record_keyboard_listener:
                self.record_keyboard_listener.stop()
        except Exception:
            pass
        self.record_mouse_listener = None
        self.record_keyboard_listener = None
        inserted = 0
        for step in self.recorded_steps:
            self.insert_step(step)
            inserted += 1
        self.recorded_steps = []
        self.log(f"녹화 종료: {inserted}개 항목 추가")
        self.update_button_states()

    def _show_recording_overlay(self):
        try:
            overlay = tk.Toplevel(self.root)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.wm_attributes("-transparentcolor", "#010101")
            overlay.configure(bg="#010101")
            text = "마우스 및 키보드 동작 녹화중\n녹화종료는 F10"
            font_spec = ("맑은 고딕", 18, "bold")
            w, h = 560, 100
            canvas = tk.Canvas(overlay, bg="#010101", highlightthickness=0, bd=0, width=w, height=h)
            canvas.pack()
            cx, cy = w // 2, h // 2
            for dx, dy in [(-2,-2),(-2,-1),(-2,0),(-2,1),(-2,2),(-1,-2),(-1,2),(0,-2),(0,2),(1,-2),(1,2),(2,-2),(2,-1),(2,0),(2,1),(2,2)]:
                canvas.create_text(cx+dx, cy+dy, text=text, fill="#1a1a1a", font=font_spec, justify="center")
            canvas.create_text(cx, cy, text=text, fill="white", font=font_spec, justify="center")
            sw, sh = overlay.winfo_screenwidth(), overlay.winfo_screenheight()
            overlay.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

            def set_click_through():
                try:
                    hwnd = overlay.winfo_id()
                    ex = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                    ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex | 0x00000020)
                except Exception:
                    pass

            overlay.after(100, set_click_through)
            self._recording_overlay = overlay
        except Exception as e:
            self.log(f"오버레이 표시 실패: {e}")

    def _hide_recording_overlay(self):
        try:
            if self._recording_overlay:
                self._recording_overlay.destroy()
        except Exception:
            pass
        self._recording_overlay = None

    def record_add_wait_if_needed(self, now_ts):
        if self.record_last_event_time is None:
            self.record_last_event_time = now_ts
            return
        gap = now_ts - self.record_last_event_time
        if gap >= self.record_wait_min_gap:
            self.recorded_steps.append({"id": self.next_id(), "type": "WAIT", "seconds": round(gap, 2)})
        self.record_last_event_time = now_ts

    def flush_record_text_buffer(self):
        if self.record_text_buffer:
            self.recorded_steps.append({"id": self.next_id(), "type": "TEXT_INPUT", "text": self.record_text_buffer})
            self.record_text_buffer = ""

    def record_mouse_move(self, x, y):
        if not self.recording or time.time() < self.record_ignore_until:
            return
        now = time.time()
        pos = (int(x), int(y))
        if self.record_last_move_pos is None:
            self.record_last_move_pos = pos
            self.record_last_move_time = now
            return
        if now - self.record_last_move_time < self.record_move_min_interval:
            return
        if self.distance(pos, self.record_last_move_pos) < self.record_move_min_distance:
            return
        if self.record_text_buffer:
            self.flush_record_text_buffer()
            self.record_add_wait_if_needed(now)
        else:
            self.record_add_wait_if_needed(now)
        self.recorded_steps.append({"id": self.next_id(), "type": "MOVE", "x": pos[0], "y": pos[1]})
        self.record_last_move_pos = pos
        self.record_last_move_time = now

    def record_mouse_click(self, x, y, button, pressed):
        if not self.recording or not pressed or time.time() < self.record_ignore_until:
            return
        now = time.time()
        self.flush_record_text_buffer()
        pos = (int(x), int(y))
        steps_before = len(self.recorded_steps)
        if self.record_last_move_pos != pos:
            self.record_add_wait_if_needed(now)
            self.recorded_steps.append({"id": self.next_id(), "type": "MOVE", "x": pos[0], "y": pos[1]})
            self.record_last_move_pos = pos
        else:
            self.record_add_wait_if_needed(now)
        button_name = str(button)
        click_type = "CLICK_RIGHT" if "right" in button_name else "CLICK_LEFT"
        if self.record_last_click:
            last_time, last_pos, last_button, last_idx = self.record_last_click
            if (click_type == "CLICK_LEFT" and last_button == "CLICK_LEFT"
                    and now - last_time <= self.record_double_click_window
                    and self.distance(pos, last_pos) <= 6):
                if 0 <= last_idx < len(self.recorded_steps) and self.recorded_steps[last_idx]["type"] == "CLICK_LEFT":
                    del self.recorded_steps[steps_before:]
                    self.record_last_move_pos = last_pos
                    self.recorded_steps[last_idx]["type"] = "DOUBLE_CLICK"
                    self.record_last_click = None
                    self.record_last_event_time = now
                    return
        self.recorded_steps.append({"id": self.next_id(), "type": click_type})
        self.record_last_click = (now, pos, click_type, len(self.recorded_steps) - 1)
        self.record_last_event_time = now

    def record_key_press(self, key):
        if not self.recording or time.time() < self.record_ignore_until:
            return
        now = time.time()
        if self.record_last_event_time is not None and now - self.record_last_event_time >= self.record_text_flush_gap and self.record_text_buffer:
            self.flush_record_text_buffer()
        if self.record_last_event_time is None:
            self.record_last_event_time = now
        try:
            char = key.char
        except Exception:
            char = None
        if char is None and hasattr(key, 'vk') and key.vk is not None:
            vk = key.vk
            if 48 <= vk <= 57:
                char = chr(vk)
            elif 96 <= vk <= 105:
                char = str(vk - 96)
        if char:
            if not self.record_text_buffer:
                self.record_add_wait_if_needed(now)
            self.record_text_buffer += char
            self.record_last_event_time = now
            return
        if key == pynput_keyboard.Key.space:
            if not self.record_text_buffer:
                self.record_add_wait_if_needed(now)
            self.record_text_buffer += " "
            self.record_last_event_time = now
            return
        if key == pynput_keyboard.Key.backspace:
            if self.record_text_buffer:
                self.record_text_buffer = self.record_text_buffer[:-1]
                self.record_last_event_time = now
            else:
                self.record_add_wait_if_needed(now)
                self.recorded_steps.append({"id": self.next_id(), "type": "KEY_PRESS", "key": "backspace"})
                self.record_last_event_time = now
            return
        if key in (pynput_keyboard.Key.enter, pynput_keyboard.Key.tab, pynput_keyboard.Key.esc):
            last_text_time = self.record_last_event_time if self.record_text_buffer else None
            self.flush_record_text_buffer()
            if last_text_time is not None:
                gap = round(now - last_text_time, 2)
                if gap >= self.record_wait_min_gap:
                    self.recorded_steps.append({"id": self.next_id(), "type": "WAIT", "seconds": gap})
                self.record_last_event_time = now
            else:
                self.record_add_wait_if_needed(now)
            key_name = "enter" if key == pynput_keyboard.Key.enter else "tab" if key == pynput_keyboard.Key.tab else "esc"
            self.recorded_steps.append({"id": self.next_id(), "type": "KEY_PRESS", "key": key_name})
            self.record_last_event_time = now
            return

    # ── Save / Load ──────────────────────────────────────────────────
    def save_steps(self):
        path = self.current_file
        if not path:
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 파일", "*.json")])
            if not path:
                return
        data = {"version": 2, "macros": self.macros}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.current_file = path
        self.save_runtime_state()
        self.log(f"저장 완료: {path}")

    def load_steps_from_path(self, path, silent=False):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("version", 1) < 2:
            data = self._migrate_v1_data(data)

        self.macros = data.get("macros", [])
        if not self.macros:
            self._init_default_macros()

        for macro in self.macros:
            if "id" not in macro:
                macro["id"] = self.next_macro_id()
            else:
                try:
                    num = int(macro["id"].split("_")[-1])
                    if num >= self._next_macro_id:
                        self._next_macro_id = num + 1
                except Exception:
                    pass
            if "steps" not in macro:
                macro["steps"] = []
            self.ensure_ids(macro["steps"])

        self._selected_macro_id = self.macros[0]["id"] if self.macros else None
        self.current_file = path

        startup_macro = self._find_macro_by_hotkey(HOTKEY_STARTUP)
        self.startup_var.set(bool(startup_macro) and bool(self.runtime_state.get("startup_enabled", True)))

        self.runtime_state["last_file"] = path
        self.save_runtime_state()
        self.refresh_macro_list()
        self.refresh_tree()
        if not silent:
            self.log(f"불러오기 완료: {path}")

    def load_steps(self):
        path = filedialog.askopenfilename(filetypes=[("JSON 파일", "*.json")])
        if not path:
            return
        self.load_steps_from_path(path, silent=False)

    def _auto_save_steps(self):
        if not self.macros:
            return
        if not any(m.get("steps") for m in self.macros):
            return
        path = self.current_file or AUTO_SAVE_FILE
        try:
            data = {"version": 2, "macros": self.macros}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if not self.current_file:
                self.current_file = AUTO_SAVE_FILE
        except Exception:
            pass

    # ── Startup registration ─────────────────────────────────────────
    def toggle_startup(self):
        if sys.platform != "win32":
            messagebox.showwarning("알림", "Windows에서만 지원합니다.")
            self.startup_var.set(False)
            return
        enabled = bool(self.startup_var.get())
        self.runtime_state["startup_enabled"] = enabled
        self.save_runtime_state()
        if enabled:
            self.register_startup()
        else:
            self.unregister_startup()

    def register_startup(self):
        if self.is_admin():
            self._register_startup_task_scheduler()
        else:
            self._register_startup_registry()

    def _register_startup_registry(self):
        self._delete_task_scheduler()
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}"'
            else:
                command = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)
            self.log("자동실행 등록 완료")
        except Exception as e:
            self.startup_var.set(False)
            self.runtime_state["startup_enabled"] = False
            self.save_runtime_state()
            messagebox.showerror("오류", str(e))

    def _register_startup_task_scheduler(self):
        self._delete_registry_startup()
        try:
            if getattr(sys, "frozen", False):
                tr_value = f'"{sys.executable}"'
            else:
                tr_value = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            result = subprocess.run(
                ['schtasks', '/create', '/tn', APP_NAME, '/tr', tr_value, '/sc', 'onlogon', '/rl', 'highest', '/f'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                self.log("관리자 권한 자동실행 등록 완료 (작업 스케줄러)")
            else:
                raise Exception(f"작업 스케줄러 등록 실패 (오류 코드: {result.returncode})")
        except Exception as e:
            self.startup_var.set(False)
            self.runtime_state["startup_enabled"] = False
            self.save_runtime_state()
            messagebox.showerror("오류", str(e))

    def unregister_startup(self):
        self._delete_registry_startup()
        self._delete_task_scheduler()
        self.log("자동실행 해제 완료")

    def _delete_registry_startup(self):
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            try: winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError: pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _delete_task_scheduler(self):
        try:
            subprocess.run(['schtasks', '/delete', '/tn', APP_NAME, '/f'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # ── Execution ────────────────────────────────────────────────────
    def wake_mouse(self):
        try:
            x, y = pyautogui.position()
            pyautogui.moveTo(x+1, y+1, duration=0.03)
            pyautogui.moveTo(x, y, duration=0.03)
            self.log("시작시 마우스 깨우기 실행")
        except Exception as e:
            self.log(f"마우스 깨우기 실패: {e}")

    def start_run(self, macro=None):
        if self.running:
            self.log("이미 실행 중입니다")
            return
        if macro is None:
            macro = self._get_current_macro()
        if not macro or not macro.get("steps"):
            self.log("실행할 동작이 없습니다")
            return
        if not self.is_admin() and not self._admin_warned:
            proceed = messagebox.askyesno(
                "권한 경고",
                "현재 관리자 권한으로 실행 중이 아닙니다.\n\n"
                "관리자 권한이 필요한 프로그램은 제어할 수 없습니다.\n"
                "자동실행기를 종료 후 관리자 권한으로 실행해야 합니다.\n\n"
                "그래도 실행하시겠습니까?",
                icon="warning", parent=self.root,
            )
            if not proceed:
                return
            self._admin_warned = True
        self.stop_event.clear()
        self.auto_run_after_launch = False
        if self.auto_run_after_id is not None:
            try: self.root.after_cancel(self.auto_run_after_id)
            except Exception: pass
            self.auto_run_after_id = None
        self.running = True
        self.minimize_app_windows()
        self.worker = threading.Thread(target=self.run_steps, args=(macro,), daemon=True)
        self.worker.start()
        self.log(f"실행 시작: {macro.get('name', '')}")

    def stop_run(self):
        self.stop_event.set()
        self.auto_run_after_launch = False
        if self.auto_run_after_id is not None:
            try: self.root.after_cancel(self.auto_run_after_id)
            except Exception: pass
            self.auto_run_after_id = None
        self.running = False
        self.log("중지 요청")

    def wait_interruptible(self, seconds):
        end = time.time() + seconds
        while not self.stop_event.is_set() and time.time() < end:
            time.sleep(0.02)

    def execute_step_list(self, items):
        idx = 0
        loop_count = 0
        while not self.stop_event.is_set() and idx < len(items):
            step = items[idx]
            result = self.execute_step(step)
            if result == "EXIT":
                return "EXIT"
            if isinstance(result, tuple) and result[0] == "LOOP":
                target = result[1]  # 0 = 무한
                if target == 0 or loop_count < target - 1:
                    loop_count += 1
                    idx = 0
                    continue
                else:
                    loop_count = 0
                    idx += 1
                    continue
            idx += 1
        return None

    def execute_step(self, step):
        if self.stop_event.is_set():
            return None
        t = step["type"]
        if t == "MOVE":
            self.current_position = (step["x"], step["y"])
            pyautogui.moveTo(step["x"], step["y"], duration=0.08)
            self.log(f"이동 -> ({step['x']}, {step['y']})")
            return None
        if t in ("CLICK_LEFT", "CLICK_RIGHT", "DOUBLE_CLICK"):
            if self.stop_event.is_set():
                return None
            if not self.current_position:
                self.log("이동 좌표가 없어서 클릭 생략")
                return None
            x, y = self.current_position
            pyautogui.moveTo(x, y, duration=0.08)
            if self.stop_event.is_set():
                return None
            if t == "CLICK_LEFT":
                pyautogui.click(button="left")
                self.log(f"좌클릭 -> ({x}, {y})")
            elif t == "CLICK_RIGHT":
                pyautogui.click(button="right")
                self.log(f"우클릭 -> ({x}, {y})")
            else:
                pyautogui.doubleClick()
                self.log(f"더블클릭 -> ({x}, {y})")
            return None
        if t == "TEXT_INPUT":
            if self.stop_event.is_set():
                return None
            text = step.get("text", "")
            pyperclip.copy(text)
            time.sleep(0.08)
            if self.stop_event.is_set():
                return None
            pyautogui.keyDown("ctrl")
            time.sleep(0.03)
            pyautogui.press("v")
            time.sleep(0.03)
            pyautogui.keyUp("ctrl")
            time.sleep(0.05)
            self.log(f"텍스트입력 -> {text[:30]!r}")
            return None
        if t == "KEY_PRESS":
            key_name = step.get("key", "")
            if key_name and not self.stop_event.is_set():
                pyautogui.press(key_name)
                self.log(f"키입력 -> {key_name}")
            return None
        if t == "WAIT":
            self.log(f"대기 -> {step['seconds']}초")
            self.wait_interruptible(step["seconds"])
            return None
        if t == "WINDOW_POSITION":
            ok, msg = self.move_resize_window(
                step.get("title", ""),
                int(step.get("x", 0)), int(step.get("y", 0)),
                int(step.get("w", 0)), int(step.get("h", 0)),
            )
            self.log(f"창 위치 {'완료' if ok else '실패'} -> {msg}")
            return None
        if t == "EXIT":
            self.log("종료")
            return "EXIT"
        if t == "LOOP":
            count = step.get("count", 0)
            label = "무한" if count == 0 else f"{count}회"
            self.log(f"반복 ({label}) - 처음으로")
            return ("LOOP", count)
        return None

    def run_steps(self, macro):
        steps = macro["steps"]
        is_startup = macro.get("hotkey") == HOTKEY_STARTUP
        do_startup_wait = is_startup and macro.get("startup_wait_enabled", True)
        self.current_position = None
        try:
            self.wake_mouse()
            time.sleep(0.15)
            if self.stop_event.is_set():
                return
            if do_startup_wait:
                self.log("윈도우 시작 대기: 60초")
                self.wait_interruptible(60)
                if self.stop_event.is_set():
                    return
            result = self.execute_step_list(steps)
            if result == "EXIT":
                self.log("실행 종료 후 프로그램 종료")
                self.root.after(0, self.force_close_program)
        except pyautogui.FailSafeException:
            self.log("화면 좌상단 FailSafe 감지로 중지")
        except Exception as e:
            self.log(f"오류: {e}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.running = False
            self.log("중지 완료" if self.stop_event.is_set() else "완료")

    def force_close_program(self):
        try: self.stop_event.set()
        except Exception: pass
        try:
            if self.recording:
                self.stop_recording()
        except Exception: pass
        try:
            if self.hotkey_listener:
                self.hotkey_listener.stop()
        except Exception: pass
        try:
            if self.mouse_hotkey_listener:
                self.mouse_hotkey_listener.stop()
        except Exception: pass
        try: self.root.destroy()
        except Exception: pass

    def on_close(self):
        try:
            self.stop_event.set()
            self.auto_run_after_launch = False
            if self.auto_run_after_id is not None:
                try: self.root.after_cancel(self.auto_run_after_id)
                except Exception: pass
                self.auto_run_after_id = None
            if self.recording:
                self.stop_recording()
            if self.hotkey_listener:
                self.hotkey_listener.stop()
            if self.mouse_hotkey_listener:
                self.mouse_hotkey_listener.stop()
            self._auto_save_steps()
            self.save_runtime_state()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = AutomationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

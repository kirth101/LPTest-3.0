"""
LPTest (Kivy rebuild) — entry point with full UI matching, offline quiz save/load,
custom TTS Engine selection, sound effects, and enhanced haptic touch feedback.

"""
from __future__ import annotations

import json
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, StringProperty, BooleanProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, NoTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.utils import platform

from file_parser import extract_text
from question_generator import (
    detect_existing_qa,
    chunk_text,
    generate_questions_with_gemini,
    generate_questions_offline,
)
import quiz_history

# ---------------------------------------------------------------------------
# Palette — Purple / Cyan / Dark Theme (Matching Reference UI)
# ---------------------------------------------------------------------------
BG = (0.02, 0.02, 0.04, 1)                  
PANEL_BG = (0.086, 0.078, 0.129, 1)
PURPLE = (0.482, 0.235, 0.898, 1)           
PURPLE_DARK = (0.34, 0.11, 0.74, 1)         
PURPLE_LIGHT = (0.65, 0.35, 0.98, 1)        
CYAN_ACCENT = (0.22, 0.74, 0.97, 1)         
BLUE_ACCENT = (0.38, 0.52, 0.98, 1)         
PINK_ACCENT = (0.92, 0.35, 0.65, 1)         
FG = (0.961, 0.961, 0.961, 1)
GREEN = (0.184, 0.682, 0.306, 1)
RED = (0.851, 0.263, 0.184, 1)
MUTED = (0.659, 0.659, 0.659, 1)

DEVELOPER_NAME = "Direk Allan"

SUPPORTED_EXT = [".pdf", ".docx", ".doc", ".txt", ".json"]
PRESET_COUNTS = (10, 20, 50, 100)

Window.clearcolor = BG

KV = """
<PanelButton>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    canvas.before:
        Color:
            rgba: self.bg_color
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
    color: 1, 1, 1, 1
    bold: True
    size_hint_y: None
    height: dp(54)

<CapsuleButton>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    canvas.before:
        Color:
            rgba: (0.12, 0.1, 0.18, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(22)]
        Color:
            rgba: (0.7, 0.6, 0.8, 0.8)
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(22))
            width: dp(1.5)
    color: 1, 1, 1, 1
    bold: True
    size_hint_y: None
    height: dp(48)

<OptionButton>:
    canvas.before:
        Color:
            rgba: self.bg_color
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    color: 1, 1, 1, 1
    bold: True
    halign: 'left'
    valign: 'middle'
    padding: dp(18), dp(14)
    size_hint_y: None

<HistoryRow>:
    size_hint_y: None
    height: dp(64)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.07, 0.06, 0.1, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
"""
Builder.load_string(KV)


class PanelButton(Button):
    bg_color = ListProperty(PURPLE)

class CapsuleButton(Button):
    pass

class _RoundIconButton(ButtonBehavior, Widget):
    bg_color = ListProperty(PURPLE)

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(44), dp(44)))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg_color_instr = Color(rgba=self.bg_color)
            self._bg_ellipse = Ellipse(pos=self.pos, size=self.size)
        with self.canvas.after:
            Color(1, 1, 1, 1)
            self._lines = self._build_lines()
        self.bind(pos=self._redraw, size=self._redraw, bg_color=self._recolor)
        self._redraw()

    def _build_lines(self):
        raise NotImplementedError

    def _recolor(self, *_a):
        self._bg_color_instr.rgba = self.bg_color

    def _redraw(self, *_a):
        self._bg_ellipse.pos = self.pos
        self._bg_ellipse.size = self.size

class HomeIconButton(_RoundIconButton):
    def _build_lines(self):
        self._roof = Line(width=dp(1.8), cap="round", joint="round")
        self._base = Line(width=dp(1.8), cap="round", joint="round")
        self._door = Line(width=dp(1.5), cap="round", joint="round")
        return [self._roof, self._base, self._door]

    def _redraw(self, *_a):
        super()._redraw()
        cx, cy = self.center_x, self.center_y
        s = min(self.width, self.height) * 0.30
        self._roof.points = [cx - s, cy - s * 0.05, cx, cy + s * 0.95, cx + s, cy - s * 0.05]
        self._base.points = [
            cx - s * 0.65, cy - s * 0.05, cx - s * 0.65, cy - s * 0.95,
            cx + s * 0.65, cy - s * 0.95, cx + s * 0.65, cy - s * 0.05,
        ]
        self._door.points = [
            cx - s * 0.18, cy - s * 0.95, cx - s * 0.18, cy - s * 0.30,
            cx + s * 0.18, cy - s * 0.30, cx + s * 0.18, cy - s * 0.95,
        ]

class SpeakIconButton(_RoundIconButton):
    def _build_lines(self):
        self._body = Line(width=dp(1.8), cap="round", joint="round", close=True)
        self._wave1 = Line(width=dp(1.5), cap="round")
        self._wave2 = Line(width=dp(1.5), cap="round")
        return [self._body, self._wave1, self._wave2]

    def _redraw(self, *_a):
        super()._redraw()
        cx, cy = self.center_x, self.center_y
        s = min(self.width, self.height) * 0.30
        self._body.points = [
            cx - s, cy - s * 0.35,
            cx - s * 0.4, cy - s * 0.35,
            cx, cy - s * 0.9,
            cx, cy + s * 0.9,
            cx - s * 0.4, cy + s * 0.35,
            cx - s, cy + s * 0.35,
        ]
        self._wave1.circle = (cx + s * 0.15, cy, s * 0.55, -45, 45)
        self._wave2.circle = (cx + s * 0.15, cy, s * 0.95, -45, 45)

class GearIconButton(ButtonBehavior, Widget):
    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(44), dp(44)))
        super().__init__(**kwargs)
        with self.canvas.after:
            Color(0.85, 0.85, 0.88, 1)
            self._ring = Line(width=dp(1.8))
            self._hub = Line(width=dp(1.5))
            self._teeth = [Line(width=dp(1.8), cap="round") for _ in range(8)]
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def _redraw(self, *_a):
        import math
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) * 0.24
        self._ring.circle = (cx, cy, r)
        self._hub.circle = (cx, cy, r * 0.4)
        for i, line in enumerate(self._teeth):
            angle = math.radians(i * 45)
            x1 = cx + math.cos(angle) * r * 1.15
            y1 = cy + math.sin(angle) * r * 1.15
            x2 = cx + math.cos(angle) * r * 1.55
            y2 = cy + math.sin(angle) * r * 1.55
            line.points = [x1, y1, x2, y2]

class OptionButton(ButtonBehavior, Label):
    bg_color = ListProperty(PURPLE_DARK)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(width=self._retext, texture_size=self._reheight)

    def _retext(self, *_a):
        self.text_size = (self.width - dp(32), None)

    def _reheight(self, *_a):
        self.height = max(dp(54), self.texture_size[1] + dp(28))

class HistoryRow(BoxLayout):
    pass

def option_font_size(options: list[str]) -> int:
    longest = max((len(o) for o in options), default=0)
    total = sum(len(o) for o in options)
    if longest <= 30 and total <= 140:
        return 17
    elif longest <= 55 and total <= 220:
        return 16
    elif longest <= 90 and total <= 320:
        return 15
    return 14

# ---------------------------------------------------------------------------
# Android TextToSpeech Wrapper
# ---------------------------------------------------------------------------
class _AndroidTTS:
    _engine = None
    _engine_pkg = None

    @classmethod
    def get_available_engines(cls) -> list[tuple[str, str]]:
        if platform != "android":
            return [("Default System Engine", "default")]
        try:
            from jnius import autoclass
            engine = cls._get_engine()
            engines_list = engine.getEngines()
            result = []
            for i in range(engines_list.size()):
                item = engines_list.get(i)
                result.append((str(item.label), str(item.name)))
            return result if result else [("Default System Engine", "default")]
        except Exception as e:
            print(f"LPTest: Failed to query TTS engines: {e}")
            return [("Default System Engine", "default")]

    @classmethod
    def set_engine(cls, pkg_name: str):
        if platform != "android" or pkg_name == "default":
            return
        try:
            from jnius import autoclass
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            if cls._engine is not None:
                try:
                    cls._engine.shutdown()
                except Exception:
                    pass
            cls._engine_pkg = pkg_name
            cls._engine = TextToSpeech(PythonActivity.mActivity, None, pkg_name)
        except Exception as e:
            print(f"LPTest: Could not set TTS engine {pkg_name}: {e}")

    @classmethod
    def _get_engine(cls):
        if cls._engine is None:
            from jnius import autoclass
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            if cls._engine_pkg:
                cls._engine = TextToSpeech(PythonActivity.mActivity, None, cls._engine_pkg)
            else:
                cls._engine = TextToSpeech(PythonActivity.mActivity, None)
        return cls._engine

    @classmethod
    def speak(cls, message: str, rate: float = 1.0):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            Locale = autoclass("java.util.Locale")
            engine = cls._get_engine()
            engine.setLanguage(Locale.US)
            engine.setSpeechRate(max(0.1, rate))
            engine.speak(message, 0, None)
        except Exception as e:
            print(f"LPTest: TTS Speak error: {e}")

def _android_vibrate(seconds: float):
    if platform != "android":
        return
    try:
        from jnius import autoclass, cast
        Context = autoclass("android.content.Context")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Build_VERSION = autoclass("android.os.Build$VERSION")
        service = PythonActivity.mActivity.getSystemService(Context.VIBRATOR_SERVICE)
        vibrator = cast("android.os.Vibrator", service)
        if vibrator is None:
            return
        ms = max(1, int(seconds * 1000))
        if Build_VERSION.SDK_INT >= 26:
            VibrationEffect = autoclass("android.os.VibrationEffect")
            vibrator.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        else:
            vibrator.vibrate(ms)
    except Exception as e:
        print(f"LPTest: Vibrator error: {e}")

def guarded_release(action):
    def handler(*_a):
        app = App.get_running_app()
        app.play_swipe_sound()
        app.voice_guard(action)(app)
    return handler

def build_icon_bar(show_home: bool = True):
    width = dp(44) * (2 if show_home else 1) + (dp(8) if show_home else 0)
    bar = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint=(None, None), size=(width, dp(44)))
    home_btn = None
    if show_home:
        home_btn = HomeIconButton()
        home_btn.bind(on_release=guarded_release(lambda app: app.confirm_go_home()))
        bar.add_widget(home_btn)
    speak_btn = SpeakIconButton()
    speak_btn.bind(on_release=lambda *_: (
        App.get_running_app().play_swipe_sound(),
        App.get_running_app().force_repeat_current()
    ))
    bar.add_widget(speak_btn)
    return bar, home_btn, speak_btn

class VoiceNavMixin:
    _SWIPE_THRESHOLD = dp(24)
    _DOUBLE_TAP_WINDOW = 0.35
    _DOUBLE_TAP_RADIUS = dp(60)

    def _voice_nav_init(self):
        self._voice_nav_items: list[tuple[str, object, object]] = []
        self._voice_nav_index = 0
        self._swipe_start = None
        self._last_tap_time = 0.0
        self._last_tap_pos = (0.0, 0.0)

    def _set_voice_nav_items(self, items: list[tuple], reset_index: bool = True):
        normalized = []
        for it in items:
            if len(it) == 2:
                normalized.append((it[0], it[1], None))
            else:
                normalized.append(it)
        self._voice_nav_items = normalized
        if reset_index or self._voice_nav_index >= len(normalized):
            self._voice_nav_index = 0

    def _haptic(self, short: bool = True):
        _android_vibrate(0.02 if short else 0.045)

    def _voice_nav_focus(self, index: int, *, haptic: bool = True):
        if not self._voice_nav_items:
            return
        if index != self._voice_nav_index or haptic:
            self._voice_nav_index = index
            if haptic:
                self._haptic(short=True)
            label, _callback, _widget = self._voice_nav_items[index]
            App.get_running_app().speak(label)

    def _voice_nav_move(self, delta: int):
        if not self._voice_nav_items:
            return
        new_index = (self._voice_nav_index + delta) % len(self._voice_nav_items)
        self._voice_nav_focus(new_index, haptic=True)

    def _voice_nav_activate(self):
        if not self._voice_nav_items:
            return
        self._haptic(short=False)
        App.get_running_app().play_swipe_sound()
        _label, callback, _widget = self._voice_nav_items[self._voice_nav_index]
        if callback:
            callback()

    def _voice_nav_hit_test(self, window_pos) -> int | None:
        for idx, (_label, _callback, widget) in enumerate(self._voice_nav_items):
            if widget is None or widget.parent is None:
                continue
            try:
                local = widget.to_widget(*window_pos)
                if widget.collide_point(*local):
                    return idx
            except Exception:
                continue
        return None

    def on_touch_down(self, touch):
        app = App.get_running_app()
        if self.collide_point(*touch.pos):
            app.play_swipe_sound()
            if app.voice_enabled:
                self._swipe_start = touch.pos
                hit = self._voice_nav_hit_test(touch.pos)
                if hit is not None:
                    self._voice_nav_focus(hit, haptic=True)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            hit = self._voice_nav_hit_test(touch.pos)
            if hit is not None and hit != self._voice_nav_index:
                self._voice_nav_focus(hit, haptic=True)
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            dx = touch.pos[0] - self._swipe_start[0]
            dy = touch.pos[1] - self._swipe_start[1]
            import time as _time
            now = _time.time()

            if abs(dx) > self._SWIPE_THRESHOLD and abs(dx) > abs(dy):
                self._haptic(short=True)
                self._voice_nav_move(1 if dx > 0 else -1)
                self._swipe_start = None
                return True
            else:
                same_spot = (abs(touch.pos[0] - self._last_tap_pos[0]) < self._DOUBLE_TAP_RADIUS and
                             abs(touch.pos[1] - self._last_tap_pos[1]) < self._DOUBLE_TAP_RADIUS)
                if now - self._last_tap_time < self._DOUBLE_TAP_WINDOW and same_spot:
                    self._voice_nav_activate()
                    self._last_tap_time = 0.0
                    self._swipe_start = None
                    return True
                self._last_tap_time = now
                self._last_tap_pos = touch.pos
        self._swipe_start = None
        return super().on_touch_up(touch)

class VoiceNavBoxLayout(VoiceNavMixin, BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()

# ---------------------------------------------------------------------------
# Landing Screen
# ---------------------------------------------------------------------------
class LandingScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=[dp(24), dp(40), dp(24), dp(20)], spacing=dp(20))
        self.add_widget(root)

        title_box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(70), spacing=dp(4))
        
        t1 = Label(text="Welcome to ", font_size=sp(26), bold=True, color=PURPLE_LIGHT, size_hint_x=None, width=dp(145))
        t2 = Label(text="LPTest", font_size=sp(26), bold=True, color=CYAN_ACCENT, size_hint_x=None, width=dp(95))
        
        header_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36))
        header_row.add_widget(Widget())  
        header_row.add_widget(t1)
        header_row.add_widget(t2)
        header_row.add_widget(Widget())  
        
        subtitle = Label(text=f"Developed by {DEVELOPER_NAME}", font_size=sp(15),
                         color=PURPLE_LIGHT, size_hint_y=None, height=dp(24), halign="center")
        
        title_box.add_widget(header_row)
        title_box.add_widget(subtitle)
        root.add_widget(title_box)

        root.add_widget(Widget(size_hint_y=None, height=dp(10)))

        instructions = Label(
            text="Upload a file to start the quiz\nYou can turn On/Off the\nvoice assistant below",
            font_size=sp(17), color=FG, size_hint_y=None, height=dp(80),
            halign="center", valign="middle", line_height=1.3
        )
        root.add_widget(instructions)

        self.upload_btn = PanelButton(text="Upload a file", bg_color=PURPLE, height=dp(56), font_size=sp(19))
        self.upload_btn.bind(on_release=lambda *_: (
            App.get_running_app().play_swipe_sound(),
            App.get_running_app().browse_file()
        ))
        root.add_widget(self.upload_btn)

        toggle_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(16))
        toggle_row.add_widget(Widget())  
        
        self.voice_btn = CapsuleButton(text="Voice Guidance On", size_hint_x=None, width=dp(220), font_size=sp(16))
        self.voice_btn.bind(on_release=lambda *_: (
            App.get_running_app().play_swipe_sound(),
            App.get_running_app().toggle_voice()
        ))
        toggle_row.add_widget(self.voice_btn)
        
        self.gear_btn = GearIconButton()
        self.gear_btn.bind(on_release=lambda *_: (
            App.get_running_app().play_swipe_sound(),
            App.get_running_app().open_settings()
        ))
        toggle_row.add_widget(self.gear_btn)
        toggle_row.add_widget(Widget())  
        root.add_widget(toggle_row)

        self.status_label = Label(text="", font_size=sp(14), color=MUTED, size_hint_y=None, height=dp(20))
        root.add_widget(self.status_label)

        prev_box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(44), spacing=dp(6))
        prev_title = Label(text="Your Previous Quizzes", font_size=sp(19), bold=True,
                           color=PINK_ACCENT, halign="center")
        prev_box.add_widget(prev_title)
        
        divider = Widget(size_hint_y=None, height=dp(2))
        with divider.canvas:
            Color(0.8, 0.8, 0.85, 0.4)
            Line(points=[dp(30), divider.y, Window.width - dp(30), divider.y], width=dp(1))
        prev_box.add_widget(divider)
        root.add_widget(prev_box)

        self.history_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.history_list)
        root.add_widget(scroller)

        app = App.get_running_app
        self._set_voice_nav_items([
            ("Upload a file button", lambda: app().browse_file(), self.upload_btn),
            ("Voice Guidance toggle button", lambda: app().toggle_voice(), self.voice_btn),
            ("Settings button", lambda: app().open_settings(), self.gear_btn),
        ])

    def on_pre_enter(self, *_a):
        self.refresh_history()

    def refresh_history(self):
        self.history_list.clear_widgets()
        history = list(reversed(quiz_history.load_history()))
        base_items = [
            ("Upload a file button", lambda: App.get_running_app().browse_file(), self.upload_btn),
            ("Voice Guidance toggle button", lambda: App.get_running_app().toggle_voice(), self.voice_btn),
            ("Settings button", lambda: App.get_running_app().open_settings(), self.gear_btn),
        ]
        if not history:
            self.history_list.add_widget(Label(
                text="No previous quizzes found.", color=MUTED, font_size=sp(14),
                size_hint_y=None, height=dp(32)
            ))
            self._set_voice_nav_items(base_items)
            return
        app = App.get_running_app()
        nav_items = list(base_items)
        for entry in history[:20]:
            row = HistoryRow(orientation="horizontal", padding=dp(10))
            info = BoxLayout(orientation="vertical")
            info.add_widget(Label(text=entry.get("filename", "Untitled"), bold=True,
                                  color=FG, font_size=sp(14), halign="left", valign="middle",
                                  text_size=(dp(150), None)))
            info.add_widget(Label(
                text=f"{entry.get('score', 0)}/{entry.get('total', 0)} correct",
                color=MUTED, font_size=sp(12), halign="left", valign="middle",
                text_size=(dp(150), None)
            ))
            row.add_widget(info)
            retake_btn = PanelButton(text="Retake", bg_color=PURPLE, size_hint=(None, None),
                                     width=dp(80), height=dp(40), font_size=sp(12))
            retake_btn.bind(on_release=guarded_release(lambda app, e=entry: app.retake_entry(e)))
            review_btn = PanelButton(text="Review", bg_color=PANEL_BG, size_hint=(None, None),
                                     width=dp(80), height=dp(40), font_size=sp(12))
            review_btn.bind(on_release=guarded_release(lambda app, e=entry: app.review_entry(e)))
            row.add_widget(retake_btn)
            row.add_widget(review_btn)
            self.history_list.add_widget(row)
            name = entry.get("filename", "Untitled quiz")
            nav_items.append((f"Retake {name} button", (lambda e=entry: app.retake_entry(e)), retake_btn))
            nav_items.append((f"Review {name} button", (lambda e=entry: app.review_entry(e)), review_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Count Selection Screen
# ---------------------------------------------------------------------------
class CountSelectScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(14))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(44))
        title = Label(text="How many questions?", font_size=sp(22), bold=True,
                      color=PURPLE_LIGHT, halign="left", valign="middle")
        title.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(title)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        self.desc = Label(text="", font_size=sp(13), color=MUTED, size_hint_y=None,
                          height=dp(50))
        root.add_widget(self.desc)
        self.btns_box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.btns_box.bind(minimum_height=self.btns_box.setter("height"))
        root.add_widget(self.btns_box)
        root.add_widget(BoxLayout())

    def show_choices(self, choices: list[tuple[str, int]], total: int, mode_note: str):
        self.desc.text = mode_note or f"{total} questions available."
        self.btns_box.clear_widgets()
        app = App.get_running_app()
        nav_items = []
        for label, n in choices:
            btn = PanelButton(text=label, bg_color=PURPLE_DARK, height=dp(52), font_size=sp(15))
            btn.bind(on_release=guarded_release(lambda app, count=n: app.start_quiz_with_count(count)))
            self.btns_box.add_widget(btn)
            nav_items.append((f"{label} button", (lambda count=n: app.start_quiz_with_count(count)), btn))
        nav_items.append(("Home button", lambda: app.confirm_go_home(), self._home_btn))
        nav_items.append(("Speak button", lambda: app.force_repeat_current(), self._speak_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Quiz Screen
# ---------------------------------------------------------------------------
class QuizScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=[dp(18), dp(16), dp(18), dp(16)],
                         spacing=dp(12))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(44))
        self.progress_label = Label(text="", font_size=sp(18), bold=True, color=BLUE_ACCENT,
                                    halign="left", valign="middle")
        self.progress_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(self.progress_label)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        question_card = BoxLayout(padding=dp(16), size_hint=(1, 0.38))
        with question_card.canvas.before:
            Color(0.7, 0.7, 0.72, 1)
            self._question_border = Line(width=dp(1.6))
        question_card.bind(pos=self._redraw_question_border, size=self._redraw_question_border)
        
        self.question_label = Label(text="", font_size=sp(19), bold=True, color=FG,
                                    halign="center", valign="middle", line_height=1.2)
        self.question_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        
        q_scroller = ScrollView(size_hint=(1, 1))
        q_scroller.add_widget(self.question_label)
        question_card.add_widget(q_scroller)
        root.add_widget(question_card)

        self.options_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12))
        self.options_box.bind(minimum_height=self.options_box.setter("height"))
        opt_scroller = ScrollView(size_hint=(1, 1))
        opt_scroller.add_widget(self.options_box)
        root.add_widget(opt_scroller)

        self.status_label = Label(text="", font_size=sp(14), bold=True, color=FG,
                                  size_hint_y=None, height=dp(0), halign="left", valign="top")
        self.status_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        self.status_label.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1] + dp(4)))
        root.add_widget(self.status_label)

        self.explanation_label = Label(text="", font_size=sp(13), color=CYAN_ACCENT,
                                       size_hint_y=None, height=dp(0), halign="left", valign="top")
        self.explanation_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        self.explanation_label.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1] + dp(4)))
        root.add_widget(self.explanation_label)

        action_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.next_btn = Button(text="Next Question", font_size=sp(16), color=MUTED,
                               background_normal="", background_down="", background_color=(0, 0, 0, 0),
                               size_hint_x=1.0, halign="center", valign="middle")
        self.next_btn.bind(on_release=lambda *_: App.get_running_app().next_question())
        action_row.add_widget(self.next_btn)
        root.add_widget(action_row)

        self.option_widgets: list[OptionButton] = []

    def _redraw_question_border(self, widget, *_a):
        self._question_border.rectangle = (widget.x, widget.y, widget.width, widget.height)

    def render(self, q: dict, index: int, total: int, mode_note: str, locked: bool,
               chosen: int | None):
        letters = ["a.", "b.", "c.", "d."]
        spoken_letters = ["A", "B", "C", "D"]
        self.progress_label.text = f"Question {index + 1} of {total}"
        self.question_label.text = q["question"]

        size = option_font_size(q["options"])
        self.options_box.clear_widgets()
        self.option_widgets = []
        correct_idx = q.get("correctIndex")
        for i in range(4):
            text = q["options"][i] if i < len(q["options"]) else ""
            label = f"{letters[i]} {text}"
            btn = OptionButton(text=label, font_size=sp(size))
            if locked:
                if i == correct_idx:
                    btn.text = f"{label}  (Correct)"
                    btn.bg_color = GREEN
                elif i == chosen:
                    btn.text = f"{label}  (Your answer)"
                    btn.bg_color = RED
                else:
                    btn.bg_color = PURPLE_DARK
            else:
                btn.bg_color = PURPLE_DARK
                btn.bind(on_release=guarded_release(lambda app, idx=i: app.select_option(idx)))
            self.options_box.add_widget(btn)
            self.option_widgets.append(btn)

        if locked:
            is_correct = chosen == correct_idx
            if is_correct:
                self.status_label.text = "Correct, well done!"
                self.status_label.color = GREEN
            else:
                correct_text = q["options"][correct_idx] if correct_idx is not None else "unknown"
                self.status_label.text = f"The correct answer is {letters[correct_idx]} {correct_text}"
                self.status_label.color = RED
            
            explanation_text = q.get("explanation")
            if not explanation_text:
                correct_opt_text = q['options'][correct_idx] if correct_idx is not None and correct_idx < len(q['options']) else "the correct option"
                explanation_text = f"The correct choice is {letters[correct_idx] if correct_idx is not None else ''} {correct_opt_text}. This is based on the key concepts covered in the test material."
            self.explanation_label.text = f"Explanation: {explanation_text}"
            
            self.next_btn.text = "Finish Quiz >" if index == total - 1 else "Next Question >"
            self.next_btn.color = PURPLE_LIGHT
            self.next_btn.bold = True
        else:
            self.status_label.text = ""
            self.explanation_label.text = ""
            self.next_btn.text = "Next Question"
            self.next_btn.color = MUTED
            self.next_btn.bold = False

        app = App.get_running_app()
        if not locked:
            nav_items = [
                (f"Option {spoken_letters[i]}: {q['options'][i] if i < len(q['options']) else ''}",
                 (lambda idx=i: app.select_option(idx)), self.option_widgets[i])
                for i in range(4)
            ]
        else:
            next_label = "Finish Quiz button" if index == total - 1 else "Next Question button"
            nav_items = [(next_label, lambda: app.next_question(), self.next_btn)]
        nav_items.append(("Home button", lambda: app.confirm_go_home(), self._home_btn))
        nav_items.append(("Speak button", lambda: app.force_repeat_current(), self._speak_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Summary Screen
# ---------------------------------------------------------------------------
class SummaryScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(40))
        self.heading = Label(text="Quiz Complete!", font_size=sp(24), bold=True,
                             color=PURPLE_LIGHT, halign="left", valign="middle")
        self.heading.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(self.heading)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        self.score_label = Label(text="", font_size=sp(16), color=FG, size_hint_y=None,
                                 height=dp(32))
        root.add_widget(self.score_label)

        self.list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.list_box)
        root.add_widget(scroller)

        actions = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.save_btn = PanelButton(text="Save Questions", bg_color=PANEL_BG, font_size=sp(13))
        self.save_btn.bind(on_release=guarded_release(lambda app: app.prompt_save_quiz_format()))
        self.retry_btn = PanelButton(text="Retry Incorrect", bg_color=PURPLE, font_size=sp(13))
        self.retry_btn.bind(on_release=guarded_release(lambda app: app.retry_incorrect()))
        self.new_btn = PanelButton(text="Upload New", bg_color=PANEL_BG, font_size=sp(13))
        self.new_btn.bind(on_release=guarded_release(lambda app: app.reset_to_landing()))
        
        actions.add_widget(self.save_btn)
        actions.add_widget(self.retry_btn)
        actions.add_widget(self.new_btn)
        root.add_widget(actions)

    def render(self, questions: list[dict], user_answers: list, correct: int, total: int):
        self.score_label.text = f"Score: {correct} / {total} correct"
        self.list_box.clear_widgets()
        letters = ["a.", "b.", "c.", "d."]
        for i, q in enumerate(questions):
            given = user_answers[i]
            correct_idx = q.get("correctIndex")
            row_correct = given == correct_idx
            row = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2),
                            padding=(dp(10), dp(8)))
            head = Label(text=f"{i + 1}. {q['question']}", bold=True, color=FG,
                         font_size=sp(13), halign="left", valign="top", size_hint_y=None)
            head.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
            head.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1]))
            row.add_widget(head)

            given_text = (f"{letters[given]} {q['options'][given]}" if given is not None
                          else "No answer")
            your = Label(text=f"Your answer: {given_text}",
                         color=GREEN if row_correct else RED, font_size=sp(12),
                         halign="left", valign="top", size_hint_y=None)
            your.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
            your.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1]))
            row.add_widget(your)

            if not row_correct and correct_idx is not None:
                correct_text = f"{letters[correct_idx]} {q['options'][correct_idx]}"
                corr = Label(text=f"Correct answer: {correct_text}", color=MUTED,
                             font_size=sp(12), halign="left", valign="top", size_hint_y=None)
                corr.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
                corr.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1]))
                row.add_widget(corr)

            row.height = sum(c.height for c in row.children) + dp(16)
            self.list_box.add_widget(row)

        app = App.get_running_app()
        self._set_voice_nav_items([
            ("Save Questions button", lambda: app.prompt_save_quiz_format(), self.save_btn),
            ("Retry Incorrect button", lambda: app.retry_incorrect(), self.retry_btn),
            ("Upload New File button", lambda: app.reset_to_landing(), self.new_btn),
            ("Home button", lambda: app.confirm_go_home(), self._home_btn),
            ("Speak button", lambda: app.force_repeat_current(), self._speak_btn),
        ])


# ---------------------------------------------------------------------------
# App Main Class
# ---------------------------------------------------------------------------
class LPTestApp(App):
    title = "LPTest"

    def build(self):
        if platform == "android":
            _AndroidTTS._get_engine()

        self.questions: list[dict] = []
        self.user_answers: list = []
        self.current_index = 0
        self.mode_note = ""
        self.filepath: str | None = None
        self.current_quiz_filename: str | None = None
        self._pending_pool: list[dict] = []
        self.locked = False
        self.voice_enabled = True
        self.speech_rate = 1.0
        self.selected_tts_engine = "default"
        self.gemini_api_key = ""
        self._count_select_prompt = ""
        self._swipe_sound = None

        try:
            self._swipe_sound = SoundLoader.load("swipe.wav")
        except Exception as e:
            print(f"LPTest: Sound load warning: {e}")

        try:
            quiz_history.configure_storage_dir(self.user_data_dir)
        except Exception:
            pass

        self.sm = ScreenManager(transition=NoTransition())
        self.landing = LandingScreen(name="landing")
        self.count_select = CountSelectScreen(name="count_select")
        self.quiz = QuizScreen(name="quiz")
        self.summary = SummaryScreen(name="summary")
        for s in (self.landing, self.count_select, self.quiz, self.summary):
            self.sm.add_widget(s)

        Clock.schedule_once(lambda *_: self.speak("Welcome to LPTest. Developed by Direk Allan. Upload a file to start the quiz."), 1.0)
        return self.sm

    def play_swipe_sound(self):
        try:
            if self._swipe_sound is None:
                self._swipe_sound = SoundLoader.load("swipe.wav")
            if self._swipe_sound:
                self._swipe_sound.stop()
                self._swipe_sound.play()
        except Exception as e:
            print(f"LPTest: Error playing swipe sound: {e}")

    def speak(self, text: str):
        if not self.voice_enabled or not text:
            return
        if platform == "android":
            try:
                _AndroidTTS.speak(text, rate=self.speech_rate)
                return
            except Exception as e:
                print(f"LPTest: Android TTS failed: {e}")
        try:
            from plyer import tts
            tts.speak(message=text)
        except Exception:
            pass

    def force_repeat_current(self):
        """Pinipilit basahin ang kasalukuyang tanong o paliwanag kahit naka-off ang voice guidance."""
        old_val = self.voice_enabled
        self.voice_enabled = True
        self.repeat_current()
        self.voice_enabled = old_val

    def voice_guard(self, func):
        def wrapped(*args, **kwargs):
            if self.voice_enabled:
                return func(*args, **kwargs)
        return wrapped

    def toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self.landing.voice_btn.text = (
            "Voice Guidance On" if self.voice_enabled
            else "Voice Guidance Off"
        )
        if self.voice_enabled:
            self.speak("Voice guidance on.")

    def open_settings(self):
        content = VoiceNavBoxLayout(orientation="vertical", spacing=dp(14), padding=dp(18))
        
        content.add_widget(Label(
            text="Settings & API Configuration", font_size=sp(16), bold=True,
            color=FG, size_hint_y=None, height=dp(28)
        ))

        content.add_widget(Label(text="Gemini API Key (for Online Module Generation):", font_size=sp(13),
                                 color=MUTED, size_hint_y=None, height=dp(20), halign="left"))
        
        api_input = TextInput(
            text=self.gemini_api_key,
            hint_text="Enter Gemini API Key",
            multiline=False,
            size_hint_y=None, height=dp(44),
            background_color=PANEL_BG, foreground_color=FG,
            cursor_color=CYAN_ACCENT
        )
        def on_api_change(instance, value):
            self.gemini_api_key = value.strip()
        api_input.bind(text=on_api_change)
        content.add_widget(api_input)

        content.add_widget(Label(text="Select Speech Engine (TTS):", font_size=sp(13),
                                 color=MUTED, size_hint_y=None, height=dp(20), halign="left"))
        
        engines = _AndroidTTS.get_available_engines()
        engine_labels = [label for label, _pkg in engines]
        engine_map = {label: pkg for label, pkg in engines}

        spinner = Spinner(
            text=engine_labels[0] if engine_labels else "Default System Engine",
            values=engine_labels,
            size_hint_y=None, height=dp(44),
            background_color=PANEL_BG, color=FG
        )

        def on_engine_select(_spinner, text):
            pkg = engine_map.get(text, "default")
            self.selected_tts_engine = pkg
            _AndroidTTS.set_engine(pkg)
            self.speak(f"Engine changed to {text}")
            update_settings_nav()

        spinner.bind(text=on_engine_select)
        content.add_widget(spinner)

        content.add_widget(Label(text="Speech Speed Rate:", font_size=sp(13),
                                 color=MUTED, size_hint_y=None, height=dp(20), halign="left"))
        
        rate_label = Label(text=f"{self.speech_rate:.1f}x", font_size=sp(20), bold=True,
                           color=PURPLE_LIGHT, size_hint_y=None, height=dp(32))
        content.add_widget(rate_label)

        slider = Slider(min=0.5, max=2.0, value=self.speech_rate, step=0.1,
                        size_hint_y=None, height=dp(36))

        def on_change(_slider, value):
            self.speech_rate = round(value, 1)
            rate_label.text = f"{self.speech_rate:.1f}x"
            update_settings_nav()

        slider.bind(value=on_change)
        content.add_widget(slider)

        test_btn = PanelButton(text="Test Voice", bg_color=PURPLE, font_size=sp(14), height=dp(44))
        test_btn.bind(on_release=lambda *_: self.speak("Testing voice guidance audio."))
        content.add_widget(test_btn)

        popup = Popup(title="Settings", content=content, size_hint=(0.88, 0.75))
        close_btn = PanelButton(text="Close", bg_color=PANEL_BG, font_size=sp(14), height=dp(44))
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        content.add_widget(close_btn)

        def update_settings_nav():
            content._set_voice_nav_items([
                ("Gemini API key input field", None, api_input),
                (f"Select Speech Engine. Currently {spinner.text}", lambda: spinner.dispatch('on_release'), spinner),
                (f"Speech speed rate. Currently {self.speech_rate:.1f}x", None, slider),
                ("Test Voice button", lambda: self.speak("Testing voice guidance audio."), test_btn),
                ("Close settings button", lambda: popup.dismiss(), close_btn)
            ], reset_index=False)
            
        update_settings_nav()

        popup.open()
        self.speak("Settings opened. Configure Gemini API key or speech settings.")

    def prompt_save_quiz_format(self):
        if not self.questions:
            return
        content = VoiceNavBoxLayout(orientation="vertical", spacing=dp(14), padding=dp(18))
        content.add_widget(Label(
            text="Choose file format to save questions:", font_size=sp(16), bold=True,
            color=FG, size_hint_y=None, height=dp(28), halign="center"
        ))
        
        popup = Popup(title="Save Questions", content=content, size_hint=(0.85, 0.45), auto_dismiss=True)
        
        def save_txt():
            popup.dismiss()
            self.save_quiz_file("txt")
            
        def save_pdf():
            popup.dismiss()
            self.save_quiz_file("pdf")

        txt_btn = PanelButton(text="Save as TXT File", bg_color=PURPLE, font_size=sp(14), height=dp(48))
        txt_btn.bind(on_release=guarded_release(lambda *_: save_txt()))
        
        pdf_btn = PanelButton(text="Save as PDF File", bg_color=PANEL_BG, font_size=sp(14), height=dp(48))
        pdf_btn.bind(on_release=guarded_release(lambda *_: save_pdf()))
        
        cancel_btn = PanelButton(text="Cancel", bg_color=(0.2, 0.2, 0.2, 1), font_size=sp(14), height=dp(44))
        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        
        content.add_widget(txt_btn)
        content.add_widget(pdf_btn)
        content.add_widget(cancel_btn)
        
        content._set_voice_nav_items([
            ("Save as TXT File button", save_txt, txt_btn),
            ("Save as PDF File button", save_pdf, pdf_btn),
            ("Cancel button", lambda: popup.dismiss(), cancel_btn),
        ])
        popup.open()
        self.speak("Choose file format to save questions, TXT or PDF.")

    def save_quiz_file(self, fmt: str):
        try:
            save_dir = os.path.join(self.user_data_dir, "saved_quizzes")
            os.makedirs(save_dir, exist_ok=True)
            clean_name = "".join(c for c in (self.current_quiz_filename or "quiz") if c.isalnum() or c in "._- ")
            if clean_name.lower().endswith(('.pdf', '.docx', '.doc', '.txt', '.json')):
                clean_name = os.path.splitext(clean_name)[0]
            
            letters = ["a.", "b.", "c.", "d."]
            if fmt == "txt":
                file_path = os.path.join(save_dir, f"{clean_name}_questions.txt")
                content_lines = [f"Quiz: {self.current_quiz_filename or 'Untitled'}", f"Mode: {self.mode_note}", "="*40, ""]
                for i, q in enumerate(self.questions):
                    content_lines.append(f"Q{i+1}: {q['question']}")
                    for j, opt in enumerate(q.get("options", [])):
                        content_lines.append(f"  {letters[j]} {opt}")
                    corr_idx = q.get("correctIndex")
                    if corr_idx is not None and corr_idx < len(letters):
                        content_lines.append(f"  Correct Answer: {letters[corr_idx]} {q['options'][corr_idx]}")
                    if q.get("explanation"):
                        content_lines.append(f"  Explanation: {q['explanation']}")
                    content_lines.append("-" * 30)
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(content_lines))
                
                self.speak("Quiz saved as TXT file successfully.")
                p = Popup(title="Saved as TXT", content=Label(text=f"Saved to:\n{os.path.basename(file_path)}", halign="center"), size_hint=(0.8, 0.3))
                p.open()

            elif fmt == "pdf":
                file_path = os.path.join(save_dir, f"{clean_name}_questions.pdf")
                pdf_saved = False
                try:
                    from reportlab.lib.pagesizes import letter
                    from reportlab.pdfgen import canvas
                    c = canvas.Canvas(file_path, pagesize=letter)
                    width, height = letter
                    y = height - 40
                    c.setFont("Helvetica-Bold", 14)
                    c.drawString(40, y, f"Quiz: {self.current_quiz_filename or 'Untitled'}")
                    y -= 25
                    c.setFont("Helvetica", 10)
                    for i, q in enumerate(self.questions):
                        if y < 60:
                            c.showPage()
                            y = height - 40
                        c.setFont("Helvetica-Bold", 10)
                        c.drawString(40, y, f"Q{i+1}: {q['question']}")
                        y -= 15
                        c.setFont("Helvetica", 10)
                        for j, opt in enumerate(q.get("options", [])):
                            if y < 40:
                                c.showPage()
                                y = height - 40
                            c.drawString(60, y, f"{letters[j]} {opt}")
                            y -= 12
                        corr_idx = q.get("correctIndex")
                        if corr_idx is not None and corr_idx < len(letters):
                            if y < 40:
                                c.showPage()
                                y = height - 40
                            c.drawString(60, y, f"Correct: {letters[corr_idx]} {q['options'][corr_idx]}")
                            y -= 12
                        if q.get("explanation"):
                            if y < 40:
                                c.showPage()
                                y = height - 40
                            c.drawString(60, y, f"Explanation: {q['explanation']}")
                            y -= 15
                        y -= 10
                    c.save()
                    pdf_saved = True
                except Exception as e:
                    print(f"LPTest: ReportLab PDF generation failed: {e}")
                
                if not pdf_saved:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(f"PDF Export for {self.current_quiz_filename}\n\n" + "\n".join([f"Q{i+1}: {q['question']}" for i, q in enumerate(self.questions)]))
                
                self.speak("Quiz saved as PDF file successfully.")
                p = Popup(title="Saved as PDF", content=Label(text=f"Saved to:\n{os.path.basename(file_path)}", halign="center"), size_hint=(0.8, 0.3))
                p.open()
        except Exception as e:
            print(f"LPTest: Save file error: {e}")
            self.speak("Failed to save file.")

    def confirm_go_home(self):
        content = VoiceNavBoxLayout(orientation="vertical", spacing=dp(14), padding=dp(16))
        msg = Label(
            text="Go back to home screen?\nThis will end your current quiz.",
            color=FG, font_size=sp(15), halign="center", valign="middle",
        )
        msg.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        content.add_widget(msg)

        popup = Popup(title="Leave Quiz?", content=content, size_hint=(0.85, 0.4), auto_dismiss=False)
        btn_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))

        def do_stay(*_a):
            popup.dismiss()
            self.speak("Staying on quiz.")

        def do_leave(*_a):
            popup.dismiss()
            self.reset_to_landing()

        stay_btn = PanelButton(text="No, stay", bg_color=PANEL_BG, font_size=sp(14))
        stay_btn.bind(on_release=guarded_release(lambda app: do_stay()))
        leave_btn = PanelButton(text="Yes, go home", bg_color=PURPLE, font_size=sp(14))
        leave_btn.bind(on_release=guarded_release(lambda app: do_leave()))
        btn_row.add_widget(stay_btn)
        btn_row.add_widget(leave_btn)
        content.add_widget(btn_row)

        content._set_voice_nav_items([
            ("No stay button", do_stay, stay_btn),
            ("Yes go home button", do_leave, leave_btn),
        ])

        popup.open()
        self.speak("Go back to home screen?")

    def repeat_current(self):
        screen = self.sm.current
        letters = ["A", "B", "C", "D"]

        if screen == "quiz" and self.questions:
            q = self.questions[self.current_index]
            prior = self.user_answers[self.current_index]
            if prior is None:
                opts = ". ".join(
                    f"Option {letters[i]}: {q['options'][i]}"
                    for i in range(min(4, len(q["options"])))
                )
                self.speak(f"Question {self.current_index + 1} of {len(self.questions)}. {q['question']} {opts}")
            else:
                correct_idx = q.get("correctIndex")
                correct_text = q['options'][correct_idx] if correct_idx is not None and correct_idx < len(q['options']) else "unknown"
                is_correct = prior == correct_idx
                result_msg = "You answered correctly." if is_correct else f"Incorrect. Correct answer is option {letters[correct_idx] if correct_idx is not None else ''} {correct_text}."
                
                explanation_text = q.get("explanation")
                if not explanation_text:
                    explanation_text = f"The correct answer is option {letters[correct_idx] if correct_idx is not None else ''} {correct_text}."
                self.speak(f"{result_msg} Explanation: {explanation_text}")
        elif screen == "count_select":
            self.speak(self._count_select_prompt or self.mode_note)
        elif screen == "summary" and self.questions:
            total = len(self.questions)
            correct = sum(1 for i, q in enumerate(self.questions) if self.user_answers[i] == q.get("correctIndex"))
            self.speak(f"Quiz complete. You scored {correct} out of {total}.")
        else:
            self.speak(f"Welcome to LPTest. Developed by {DEVELOPER_NAME}. Upload a file to start the quiz.")

    def browse_file(self):
        self.speak("Opening file picker.")
        if platform == "android":
            try:
                self._android_pick_file()
                return
            except Exception as e:
                print(f"LPTest: Android picker error: {e}")
        self._browse_file_desktop()

    def _android_pick_file(self):
        from jnius import autoclass
        from android import activity

        Intent = autoclass("android.content.Intent")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        mActivity = PythonActivity.mActivity

        if not hasattr(self, "_android_select_code"):
            import random
            self._android_select_code = random.randint(1000, 9999) 
            activity.bind(on_activity_result=self._android_on_activity_result)

        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        mActivity.startActivityForResult(intent, self._android_select_code)

    def _android_on_activity_result(self, request_code, result_code, data):
        if request_code != getattr(self, "_android_select_code", None):
            return
        from jnius import autoclass
        Activity = autoclass("android.app.Activity")
        if result_code != Activity.RESULT_OK or data is None:
            Clock.schedule_once(lambda *_: self.speak("No file selected."), 0)
            return
        uri = data.getData()
        Clock.schedule_once(lambda *_: self._android_copy_uri_to_temp(uri), 0)

    def _android_copy_uri_to_temp(self, uri):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            mActivity = PythonActivity.mActivity

            resolver = mActivity.getContentResolver()
            display_name = "uploaded_file"
            try:
                OpenableColumns = autoclass("android.provider.OpenableColumns")
                cursor = resolver.query(uri, None, None, None, None)
                if cursor is not None:
                    idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if idx != -1 and cursor.moveToFirst():
                        display_name = cursor.getString(idx) or display_name
                    cursor.close()
            except Exception:
                pass
            display_name = os.path.basename(display_name) or "uploaded_file"

            input_stream = resolver.openInputStream(uri)
            dest_dir = os.path.join(self.user_data_dir, "picked_files")
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, display_name)

            buf = bytearray(65536)
            with open(dest_path, "wb") as out:
                while True:
                    n = input_stream.read(buf)
                    if n == -1:
                        break
                    out.write(bytes(buf[:n]))
            input_stream.close()
        except Exception as e:
            print(f"LPTest: Copy uri error: {e}")
            self._fail_load("Couldn't read that file.")
            return

        self.load_file(dest_path)

    def _browse_file_desktop(self):
        chooser = FileChooserListView(filters=["*" + e for e in SUPPORTED_EXT] + ["*.*"],
                                       path=os.path.expanduser("~"))
        popup_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        popup_box.add_widget(chooser)
        btn_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        popup = Popup(title="Select a document or JSON quiz", content=popup_box, size_hint=(0.95, 0.95))

        def do_select(*_a):
            if chooser.selection:
                path = chooser.selection[0]
                popup.dismiss()
                self.load_file(path)

        select_btn = Button(text="Select", size_hint_x=0.5)
        cancel_btn = Button(text="Cancel", size_hint_x=0.5)
        select_btn.bind(on_release=do_select)
        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        popup_box.add_widget(btn_row)
        popup.open()

    def load_file(self, path: str):
        self.landing.status_label.text = f"Reading {os.path.basename(path)} \u2026"
        self.landing.status_label.color = MUTED
        self.speak(f"Reading {os.path.basename(path)}. Please wait.")
        Clock.schedule_once(lambda *_: self._load_file_now(path), 0.05)

    def _fail_load(self, message: str):
        self.landing.status_label.text = message
        self.landing.status_label.color = RED
        self.speak(message)

    def _load_file_now(self, path: str):
        try:
            if path.lower().endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "questions" in data:
                        self.filepath = path
                        self.current_quiz_filename = data.get("filename", os.path.basename(path))
                        self.mode_note = data.get("mode_note", "Loaded offline JSON quiz.")
                        self.offer_count_select(data["questions"])
                        return

            result = extract_text(path)
            if result.error:
                self._fail_load(result.error)
                return

            self.filepath = path
            self.current_quiz_filename = os.path.basename(path)
            note = (result.warning + "\n") if result.warning else ""

            existing = detect_existing_qa(result.text)
            if existing:
                self.mode_note = note + "Using your file's own questions."
                self.offer_count_select(existing)
                return

            if self.gemini_api_key:
                self.landing.status_label.text = f"Generating questions with Gemini \u2026"
                questions, err = generate_questions_with_gemini(result.text, self.gemini_api_key)
                if questions:
                    self.mode_note = note + "Questions generated via Google Gemini AI."
                    self.offer_count_select(questions)
                    return

            chunks = chunk_text(result.text, result.headings)
            questions, skipped = generate_questions_offline(chunks, result.text)
            if not questions:
                self._fail_load("Couldn't find enough distinct questions in this file. Please add a Gemini API Key in Settings.")
                return

            skip_note = f" ({len(skipped)} section(s) skipped.)" if skipped else ""
            self.mode_note = note + "Questions generated offline." + skip_note
            self.offer_count_select(questions)
        except Exception as e:
            print(f"LPTest: File load error {path}: {e}")
            self._fail_load("Something went wrong reading that file.")

    def offer_count_select(self, questions: list[dict]):
        total = len(questions)
        self._pending_pool = questions
        if total <= PRESET_COUNTS[0]:
            self.start_quiz(questions)
            return
        choices = [(f"{n} Questions", n) for n in PRESET_COUNTS if n < total]
        choices.append((f"All Questions ({total})", total))
        self.count_select.show_choices(choices, total, self.mode_note)
        self.sm.current = "count_select"
        labels = ", ".join(label for label, _ in choices)
        self._count_select_prompt = f"Choose question count: {labels}."
        self.speak(self._count_select_prompt)

    def start_quiz_with_count(self, count: int):
        import random
        pool = list(self._pending_pool)
        random.shuffle(pool)
        self.start_quiz(pool[:count])

    def start_quiz(self, questions: list[dict]):
        self.questions = questions
        self.user_answers = [None] * len(questions)
        self.current_index = 0
        self.sm.current = "quiz"
        self.render_question()

    def render_question(self):
        self.locked = False
        q = self.questions[self.current_index]
        prior = self.user_answers[self.current_index]
        if prior is not None:
            self.locked = True
        self.quiz.render(q, self.current_index, len(self.questions), self.mode_note,
                         self.locked, prior)
        if not self.locked:
            letters = ["A", "B", "C", "D"]
            opts = ". ".join(
                f"Option {letters[i]}: {q['options'][i]}" for i in range(min(4, len(q["options"])))
            )
            self.speak(
                f"Question {self.current_index + 1} of {len(self.questions)}. "
                f"{q['question']} {opts}"
            )

    def select_option(self, idx: int):
        if self.locked:
            return
        self.locked = True
        self.user_answers[self.current_index] = idx
        self.render_question()

        letters = ["A", "B", "C", "D"]
        q = self.questions[self.current_index]
        correct_idx = q.get("correctIndex")
        if idx == correct_idx:
            msg = "Correct! Well done."
        else:
            correct_text = q["options"][correct_idx] if correct_idx is not None else "unknown"
            letter = letters[correct_idx] if correct_idx is not None else "?"
            msg = f"Incorrect. Correct answer is option {letter}: {correct_text}."
            
        explanation_text = q.get("explanation")
        if not explanation_text:
            correct_opt_text = q['options'][correct_idx] if correct_idx is not None and correct_idx < len(q['options']) else ""
            explanation_text = f"The correct answer is option {letters[correct_idx] if correct_idx is not None else ''} {correct_opt_text}."
        msg += f" Explanation: {explanation_text}"

        self.speak(msg)

    def next_question(self):
        if self.current_index >= len(self.questions) - 1:
            self.show_summary()
            return
        self.current_index += 1
        self.render_question()

    def show_summary(self, record: bool = True):
        total = len(self.questions)
        correct = sum(1 for i, q in enumerate(self.questions)
                      if self.user_answers[i] == q.get("correctIndex"))
        if record:
            quiz_history.save_attempt(
                filename=self.current_quiz_filename or "Untitled quiz",
                questions=self.questions,
                user_answers=self.user_answers,
                score=correct,
                total=total,
                mode_note=self.mode_note,
                filepath=self.filepath,
            )
        self.summary.render(self.questions, self.user_answers, correct, total)
        self.sm.current = "summary"
        self.speak(f"Quiz complete. You scored {correct} out of {total}.")

    def retry_incorrect(self):
        wrong = [q for i, q in enumerate(self.questions)
                 if self.user_answers[i] != q.get("correctIndex")]
        if not wrong:
            self.reset_to_landing()
            return
        self.mode_note = "Retrying incorrect questions."
        self.start_quiz(wrong)

    def reset_to_landing(self):
        self.questions = []
        self.user_answers = []
        self.current_index = 0
        self.filepath = None
        self.current_quiz_filename = None
        self.landing.status_label.text = ""
        self.sm.current = "landing"
        self.speak("Back to home screen.")

    def retake_entry(self, entry: dict):
        self.mode_note = entry.get("mode_note", "")
        self.current_quiz_filename = entry.get("filename")
        self.filepath = entry.get("filepath")
        self.start_quiz(list(entry.get("questions") or []))

    def review_entry(self, entry: dict):
        self.questions = list(entry.get("questions") or [])
        self.user_answers = list(entry.get("user_answers") or [])
        while len(self.user_answers) < len(self.questions):
            self.user_answers.append(None)
        self.mode_note = entry.get("mode_note", "")
        self.show_summary(record=False)


if __name__ == "__main__":
    LPTestApp().run()

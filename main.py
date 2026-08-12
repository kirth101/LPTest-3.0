"""
LPTest (Kivy rebuild) — entry point.

Built on Kivy for Android (buildozer / python-for-android).
Features self-contained spoken navigation, custom sound effects,
haptic feedback, Android TTS voice selection, and error handling popups.
"""
from __future__ import annotations

import os
import traceback

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line
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
from kivy.uix.widget import Widget
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.core.audio import SoundLoader
from kivy.utils import platform

from file_parser import extract_text
from question_generator import (
    detect_existing_qa,
    fill_missing_pieces_offline,
    chunk_text,
    generate_questions,
)
import quiz_history

# ---------------------------------------------------------------------------
# SAFE ABSOLUTE PATH RESOLUTION (Audio)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWIPE_PATH = os.path.join(BASE_DIR, 'swipe.wav')
if not os.path.exists(SWIPE_PATH):
    SWIPE_PATH = os.path.join(BASE_DIR, 'audio', 'swipe.wav')

SWIPE_SOUND = SoundLoader.load(SWIPE_PATH) if os.path.exists(SWIPE_PATH) else SoundLoader.load('swipe.wav')

def play_swipe_sound():
    if SWIPE_SOUND:
        try:
            SWIPE_SOUND.stop()
            SWIPE_SOUND.play()
        except Exception as e:
            print(f"LPTest: Audio play error: {e}")

# ---------------------------------------------------------------------------
# Palette — Purple/Violet Theme
# ---------------------------------------------------------------------------
BG = (0.043, 0.043, 0.043, 1)
PANEL_BG = (0.086, 0.078, 0.129, 1)
PURPLE = (0.482, 0.235, 0.898, 1)          # primary accent
PURPLE_DARK = (0.322, 0.145, 0.671, 1)     # option button fill
PURPLE_LIGHT = (0.702, 0.549, 0.988, 1)    # headings / title text
BLUE_ACCENT = (0.376, 0.522, 0.984, 1)     # "Question X of Y" label
PINK_ACCENT = (0.902, 0.345, 0.596, 1)     # "Your Previous Quizzes" heading
FG = (0.961, 0.961, 0.961, 1)
GREEN = (0.184, 0.682, 0.306, 1)
RED = (0.851, 0.263, 0.184, 1)
MUTED = (0.659, 0.659, 0.659, 1)

DEVELOPER_NAME = "Direk Allan"

SUPPORTED_EXT = [".pdf", ".docx", ".doc", ".txt"]
PRESET_COUNTS = (10, 20, 50, 100)

Window.clearcolor = BG

KV = """
<PanelButton>:
    background_normal: ''
    background_down: ''
    background_color: root.bg_color
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
            radius: [dp(10)]
    color: 1, 1, 1, 1
    bold: True
    halign: 'left'
    valign: 'middle'
    padding: dp(16), dp(14)
    size_hint_y: None

<HistoryRow>:
    size_hint_y: None
    height: dp(64)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: 0.078, 0.078, 0.078, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
"""
Builder.load_string(KV)


class PanelButton(Button):
    bg_color = ListProperty(PANEL_BG)


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
        self._roof = Line(width=dp(1.6), cap="round", joint="round")
        self._base = Line(width=dp(1.6), cap="round", joint="round")
        self._door = Line(width=dp(1.4), cap="round", joint="round")
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
        self._body = Line(width=dp(1.6), cap="round", joint="round", close=True)
        self._wave1 = Line(width=dp(1.4), cap="round")
        self._wave2 = Line(width=dp(1.4), cap="round")
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
        kwargs.setdefault("size", (dp(36), dp(36)))
        super().__init__(**kwargs)
        with self.canvas.after:
            Color(0.75, 0.75, 0.78, 1)
            self._ring = Line(width=dp(1.6))
            self._hub = Line(width=dp(1.4))
            self._teeth = [Line(width=dp(1.6), cap="round") for _ in range(8)]
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
        self.height = max(dp(48), self.texture_size[1] + dp(28))


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
# Android Native TTS Helper
# ---------------------------------------------------------------------------
class _AndroidTTS:
    _engine = None
    _selected_voice = None

    @classmethod
    def _get_engine(cls):
        if cls._engine is None and platform == "android":
            try:
                from jnius import autoclass
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                Locale = autoclass("java.util.Locale")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                cls._engine = TextToSpeech(PythonActivity.mActivity, None)
                cls._engine.setLanguage(Locale.US)
            except Exception as e:
                print(f"LPTest TTS Init Error: {e}")
        return cls._engine

    @classmethod
    def get_available_voices(cls) -> list[tuple[str, object]]:
        if platform != "android":
            return []
        try:
            engine = cls._get_engine()
            if not engine:
                return []
            from jnius import autoclass
            Build_VERSION = autoclass("android.os.Build$VERSION")
            if Build_VERSION.SDK_INT >= 21:
                voices = engine.getVoices()
                if voices:
                    v_list = []
                    for v in voices.toArray():
                        v_list.append((v.getName(), v))
                    return v_list
        except Exception as e:
            print(f"LPTest: Error getting voices: {e}")
        return []

    @classmethod
    def set_voice_by_name(cls, name: str):
        engine = cls._get_engine()
        if not engine:
            return
        voices = cls.get_available_voices()
        for v_name, v_obj in voices:
            if v_name == name:
                engine.setVoice(v_obj)
                cls._selected_voice = v_name
                break

    @classmethod
    def speak(cls, message: str, rate: float = 1.0):
        if platform == "android":
            try:
                from jnius import autoclass
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                engine = cls._get_engine()
                if engine:
                    engine.setSpeechRate(max(0.1, rate))
                    engine.speak(message, TextToSpeech.QUEUE_FLUSH, None)
            except Exception as e:
                print(f"LPTest TTS Speak Error: {e}")


# ---------------------------------------------------------------------------
# Android Native Haptic Vibration
# ---------------------------------------------------------------------------
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
        print(f"LPTest Vibration Error: {e}")


def guarded_release(action):
    def handler(*_a):
        app = App.get_running_app()
        action(app)
    return handler


def build_icon_bar(show_home: bool = True):
    width = dp(44) * (2 if show_home else 1) + (dp(8) if show_home else 0)
    bar = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint=(None, None),
                     size=(width, dp(44)))
    home_btn = None
    if show_home:
        home_btn = HomeIconButton()
        home_btn.bind(on_release=guarded_release(lambda app: app.confirm_go_home()))
        bar.add_widget(home_btn)
    speak_btn = SpeakIconButton()
    speak_btn.bind(on_release=guarded_release(lambda app: app.repeat_current()))
    bar.add_widget(speak_btn)
    return bar, home_btn, speak_btn


# ---------------------------------------------------------------------------
# Voice Navigation & Accessibility Mixin
# ---------------------------------------------------------------------------
class VoiceNavMixin:
    _SWIPE_THRESHOLD = dp(28)
    _DOUBLE_TAP_WINDOW = 0.3
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
        play_swipe_sound()
        _android_vibrate(0.02 if short else 0.05)

    def _voice_nav_focus(self, index: int, *, haptic: bool = True):
        if not self._voice_nav_items or index == self._voice_nav_index:
            return
        self._voice_nav_index = index
        if haptic:
            self._haptic(short=True)
        label, _callback, _widget = self._voice_nav_items[index]
        App.get_running_app().speak(label)

    def _voice_nav_move(self, delta: int):
        if not self._voice_nav_items:
            return
        new_index = (self._voice_nav_index + delta) % len(self._voice_nav_items)
        self._voice_nav_focus(new_index)

    def _voice_nav_activate(self):
        if not self._voice_nav_items:
            return
        self._haptic(short=False)
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
        if app and app.voice_enabled and self.collide_point(*touch.pos):
            self._swipe_start = touch.pos
            hit = self._voice_nav_hit_test(touch.pos)
            if hit is not None:
                self._voice_nav_focus(hit)
            super().on_touch_down(touch)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        app = App.get_running_app()
        if app and app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            hit = self._voice_nav_hit_test(touch.pos)
            if hit is not None:
                self._voice_nav_focus(hit)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        app = App.get_running_app()
        if app and app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            dx = touch.pos[0] - self._swipe_start[0]
            dy = touch.pos[1] - self._swipe_start[1]
            import time as _time
            now = _time.time()
            if abs(dx) > self._SWIPE_THRESHOLD and abs(dx) > abs(dy):
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
            return True
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
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        self.add_widget(root)

        header = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(60), spacing=dp(2))
        
        title = Label(
            text="[color=#9d8ec8]Welcome to [/color][color=#3be5d5]LPTest[/color]",
            markup=True,
            font_size=sp(24),
            bold=True,
            halign="center",
            valign="middle",
            size_hint_x=1
        )
        title.bind(size=lambda w, *_: setattr(w, "text_size", w.size))

        subtitle = Label(
            text=f"Developed by {DEVELOPER_NAME}",
            font_size=sp(14),
            color=(0.52, 0.35, 0.85, 1),
            halign="center",
            valign="middle",
            size_hint_x=1
        )
        subtitle.bind(size=lambda w, *_: setattr(w, "text_size", w.size))

        header.add_widget(title)
        header.add_widget(subtitle)
        root.add_widget(header)

        instructions = Label(
            text="Upload a file to start the quiz\nYou can turn On/Off the voice assistant below",
            font_size=sp(14),
            color=FG,
            size_hint_y=None,
            height=dp(56),
            halign="center"
        )
        instructions.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(instructions)

        self.upload_btn = PanelButton(
            text="Upload a file",
            bg_color=PURPLE,
            height=dp(56),
            font_size=sp(17)
        )
        self.upload_btn.bind(on_release=lambda *_: App.get_running_app().browse_file())
        root.add_widget(self.upload_btn)

        toggle_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.voice_btn = PanelButton(
            text="Voice Guidance On",
            bg_color=PANEL_BG,
            font_size=sp(14)
        )
        self.voice_btn.bind(on_release=lambda *_: App.get_running_app().toggle_voice())
        toggle_row.add_widget(self.voice_btn)
        
        self.gear_btn = GearIconButton()
        self.gear_btn.bind(on_release=lambda *_: App.get_running_app().open_settings())
        toggle_row.add_widget(self.gear_btn)
        root.add_widget(toggle_row)

        self.status_label = Label(
            text="",
            font_size=sp(13),
            color=MUTED,
            size_hint_y=None,
            height=dp(40)
        )
        root.add_widget(self.status_label)

        prev_label = Label(
            text="Your Previous Quizzes",
            font_size=sp(16),
            bold=True,
            color=PINK_ACCENT,
            size_hint_y=None,
            height=dp(36),
            halign="center",
            valign="middle"
        )
        prev_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(prev_label)

        self.history_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.history_list)
        root.add_widget(scroller)

        self._set_voice_nav_items([
            ("Upload a file button", lambda: App.get_running_app().browse_file(), self.upload_btn),
            ("Voice Guidance toggle button", lambda: App.get_running_app().toggle_voice(), self.voice_btn),
            ("Settings button", lambda: App.get_running_app().open_settings(), self.gear_btn),
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
                text="No previous quizzes yet.", color=MUTED, font_size=sp(13),
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
                                   text_size=(dp(160), None)))
            info.add_widget(Label(
                text=f"{entry.get('score', 0)}/{entry.get('total', 0)} correct",
                color=MUTED, font_size=sp(12), halign="left", valign="middle",
                text_size=(dp(160), None)
            ))
            row.add_widget(info)
            retake_btn = PanelButton(text="Retake", bg_color=PURPLE, size_hint=(None, None),
                                      width=dp(90), height=dp(40), font_size=sp(12))
            retake_btn.bind(on_release=guarded_release(lambda app, e=entry: app.retake_entry(e)))
            review_btn = PanelButton(text="Review", bg_color=PANEL_BG, size_hint=(None, None),
                                      width=dp(90), height=dp(40), font_size=sp(12))
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
        title = Label(text="How many questions?", font_size=sp(24), bold=True,
                      color=PURPLE_LIGHT, halign="left", valign="middle")
        title.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(title)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        self.desc = Label(text="", font_size=sp(13), color=MUTED, size_hint_y=None,
                           height=dp(60))
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
        nav_items.append(("Speak button, repeats options", lambda: app.repeat_current(), self._speak_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Quiz Screen
# ---------------------------------------------------------------------------
class QuizScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(8))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(32))
        self.progress_label = Label(text="", font_size=sp(15), bold=True, color=BLUE_ACCENT,
                                     halign="left", valign="middle")
        self.progress_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(self.progress_label)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        self.mode_label = Label(text="", font_size=sp(11), color=MUTED, halign="left",
                                 valign="middle", italic=True, size_hint_y=None, height=dp(18))
        self.mode_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(self.mode_label)

        question_card = BoxLayout(padding=dp(14), size_hint=(1, 0.40))
        with question_card.canvas.before:
            Color(0.5, 0.5, 0.5, 1)
            self._question_border = Line(width=dp(1.2))
        question_card.bind(pos=self._redraw_question_border, size=self._redraw_question_border)
        self.question_label = Label(text="", font_size=sp(20), bold=True, color=FG,
                                     halign="left", valign="top")
        self.question_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        q_scroller = ScrollView(size_hint=(1, 1))
        q_scroller.add_widget(self.question_label)
        question_card.add_widget(q_scroller)
        root.add_widget(question_card)

        self.options_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.options_box.bind(minimum_height=self.options_box.setter("height"))
        opt_scroller = ScrollView(size_hint=(1, 1))
        opt_scroller.add_widget(self.options_box)
        root.add_widget(opt_scroller)

        self.status_label = Label(text="", font_size=sp(14), bold=True, color=FG,
                                   size_hint_y=None, height=dp(0), halign="left", valign="top")
        self.status_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        self.status_label.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1] + dp(4)))
        root.add_widget(self.status_label)

        self.explanation_label = Label(text="", font_size=sp(12), color=MUTED,
                                        size_hint_y=None, height=dp(0), halign="left", valign="top")
        self.explanation_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        self.explanation_label.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1] + dp(4)))
        root.add_widget(self.explanation_label)

        self.next_btn = PanelButton(text="Next Question", bg_color=PURPLE, height=dp(52),
                                     font_size=sp(15), disabled=True)
        self.next_btn.bind(on_release=guarded_release(lambda app: app.next_question()))
        root.add_widget(self.next_btn)

        self.option_widgets: list[OptionButton] = []

    def _redraw_question_border(self, widget, *_a):
        self._question_border.rectangle = (widget.x, widget.y, widget.width, widget.height)

    def render(self, q: dict, index: int, total: int, mode_note: str, locked: bool, chosen: int | None):
        letters = ["a.", "b.", "c.", "d."]
        spoken_letters = ["A", "B", "C", "D"]
        self.progress_label.text = f"Question {index + 1} of {total}"
        self.mode_label.text = mode_note
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
                self.status_label.text = f"Not quite \u2014 the correct answer is {letters[correct_idx]} {correct_text}"
                self.status_label.color = RED
            if q.get("explanation"):
                self.explanation_label.text = f"Why: {q['explanation']}"
            else:
                self.explanation_label.text = ""
            self.next_btn.disabled = False
        else:
            self.status_label.text = ""
            self.explanation_label.text = ""
            self.next_btn.disabled = True

        self.next_btn.text = "Finish Quiz" if index == total - 1 else "Next Question"

        app = App.get_running_app()
        if not locked:
            nav_items = [
                (f"Option {spoken_letters[i]}: {q['options'][i] if i < len(q['options']) else ''}",
                 (lambda idx=i: app.select_option(idx)), self.option_widgets[i])
                for i in range(len(self.option_widgets))
            ]
        else:
            next_label = "Finish Quiz button" if index == total - 1 else "Next Question button"
            nav_items = [(next_label, lambda: app.next_question(), self.next_btn)]
        nav_items.append(("Home button", lambda: app.confirm_go_home(), self._home_btn))
        nav_items.append(("Speak button, repeats current question", lambda: app.repeat_current(), self._speak_btn))
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

        self.score_label = Label(text="", font_size=sp(32), bold=True, color=GREEN,
                                 size_hint_y=None, height=dp(60), halign="center")
        root.add_widget(self.score_label)

        self.message_label = Label(text="", font_size=sp(16), color=FG,
                                   size_hint_y=None, height=dp(40), halign="center")
        root.add_widget(self.message_label)

        root.add_widget(Widget())

        self.review_btn = PanelButton(text="Review Answers", bg_color=PANEL_BG, height=dp(52), font_size=sp(15))
        self.review_btn.bind(on_release=guarded_release(lambda app: app.start_review()))
        root.add_widget(self.review_btn)

        self.retake_btn = PanelButton(text="Retake Quiz", bg_color=PURPLE_DARK, height=dp(52), font_size=sp(15))
        self.retake_btn.bind(on_release=guarded_release(lambda app: app.retake_current_quiz()))
        root.add_widget(self.retake_btn)

        self.home_btn_large = PanelButton(text="Back to Home", bg_color=PURPLE, height=dp(52), font_size=sp(15))
        self.home_btn_large.bind(on_release=guarded_release(lambda app: app.confirm_go_home()))
        root.add_widget(self.home_btn_large)

    def render(self, score: int, total: int):
        pct = int((score / total) * 100) if total > 0 else 0
        self.score_label.text = f"{score} / {total} ({pct}%)"
        if pct >= 80:
            self.message_label.text = "Outstanding Performance!"
            self.score_label.color = GREEN
        elif pct >= 50:
            self.message_label.text = "Good job! Keep practicing."
            self.score_label.color = BLUE_ACCENT
        else:
            self.message_label.text = "Don't give up! Try again."
            self.score_label.color = RED

        app = App.get_running_app()
        nav_items = [
            (f"Score: {score} out of {total}, {pct} percent.", None, self.score_label),
            ("Review Answers button", lambda: app.start_review(), self.review_btn),
            ("Retake Quiz button", lambda: app.retake_current_quiz(), self.retake_btn),
            ("Back to Home button", lambda: app.confirm_go_home(), self.home_btn_large),
            ("Home button", lambda: app.confirm_go_home(), self._home_btn),
            ("Speak button", lambda: app.repeat_current(), self._speak_btn),
        ]
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Review Screen
# ---------------------------------------------------------------------------
class ReviewScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(8))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(32))
        self.progress_label = Label(text="Reviewing Quiz", font_size=sp(15), bold=True, color=BLUE_ACCENT,
                                     halign="left", valign="middle")
        self.progress_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        header.add_widget(self.progress_label)
        _bar, self._home_btn, self._speak_btn = build_icon_bar()
        header.add_widget(_bar)
        root.add_widget(header)

        question_card = BoxLayout(padding=dp(14), size_hint=(1, 0.35))
        with question_card.canvas.before:
            Color(0.5, 0.5, 0.5, 1)
            self._question_border = Line(width=dp(1.2))
        question_card.bind(pos=self._redraw_border, size=self._redraw_border)
        self.question_label = Label(text="", font_size=sp(18), bold=True, color=FG, halign="left", valign="top")
        self.question_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        q_scroller = ScrollView(size_hint=(1, 1))
        q_scroller.add_widget(self.question_label)
        question_card.add_widget(q_scroller)
        root.add_widget(question_card)

        self.options_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.options_box.bind(minimum_height=self.options_box.setter("height"))
        opt_scroller = ScrollView(size_hint=(1, 1))
        opt_scroller.add_widget(self.options_box)
        root.add_widget(opt_scroller)

        self.explanation_label = Label(text="", font_size=sp(12), color=MUTED, size_hint_y=None, height=dp(40), halign="left", valign="top")
        self.explanation_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        root.add_widget(self.explanation_label)

        nav_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.prev_btn = PanelButton(text="Previous", bg_color=PANEL_BG, font_size=sp(14))
        self.prev_btn.bind(on_release=guarded_release(lambda app: app.prev_review_q()))
        self.next_btn = PanelButton(text="Next", bg_color=PURPLE, font_size=sp(14))
        self.next_btn.bind(on_release=guarded_release(lambda app: app.next_review_q()))
        nav_row.add_widget(self.prev_btn)
        nav_row.add_widget(self.next_btn)
        root.add_widget(nav_row)

    def _redraw_border(self, widget, *_a):
        self._question_border.rectangle = (widget.x, widget.y, widget.width, widget.height)

    def render(self, q: dict, index: int, total: int, chosen: int | None):
        letters = ["a.", "b.", "c.", "d."]
        self.progress_label.text = f"Review Question {index + 1} of {total}"
        self.question_label.text = q["question"]

        self.options_box.clear_widgets()
        correct_idx = q.get("correctIndex")

        for i in range(4):
            text = q["options"][i] if i < len(q["options"]) else ""
            label_str = f"{letters[i]} {text}"
            btn = OptionButton(text=label_str, font_size=sp(15))
            if i == correct_idx:
                btn.text = f"{label_str}  (Correct Answer)"
                btn.bg_color = GREEN
            elif i == chosen:
                btn.text = f"{label_str}  (Your Answer)"
                btn.bg_color = RED
            else:
                btn.bg_color = PURPLE_DARK
            self.options_box.add_widget(btn)

        if q.get("explanation"):
            self.explanation_label.text = f"Why: {q['explanation']}"
        else:
            self.explanation_label.text = ""

        self.prev_btn.disabled = (index == 0)
        self.next_btn.text = "Done Review" if index == total - 1 else "Next"

        app = App.get_running_app()
        nav_items = [
            ("Previous Question button", lambda: app.prev_review_q(), self.prev_btn),
            ("Next Question button" if index < total - 1 else "Done Review button", lambda: app.next_review_q(), self.next_btn),
            ("Home button", lambda: app.confirm_go_home(), self._home_btn),
            ("Speak button", lambda: app.repeat_current(), self._speak_btn)
        ]
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Error Notification Popup
# ---------------------------------------------------------------------------
class ErrorPopup(Popup):
    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.title = "May Problema sa File"
        self.size_hint = (0.85, 0.38)
        self.auto_dismiss = True

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        err_label = Label(
            text=message,
            font_size=sp(14),
            color=FG,
            halign="center",
            valign="middle"
        )
        err_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        content.add_widget(err_label)

        close_btn = PanelButton(text="OK", bg_color=PURPLE, height=dp(44))
        close_btn.bind(on_release=self.dismiss)
        content.add_widget(close_btn)

        self.content = content


# ---------------------------------------------------------------------------
# Settings Popup for TTS & Voices
# ---------------------------------------------------------------------------
class SettingsPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "TTS & Voice Settings"
        self.size_hint = (0.85, 0.5)
        self.auto_dismiss = True

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        content.add_widget(Label(text="Select TTS Voice / Engine:", font_size=sp(14), bold=True, size_hint_y=None, height=dp(30)))

        self.voice_spinner = Spinner(
            text="Default System Voice",
            values=["Default System Voice"],
            size_hint_y=None,
            height=dp(44)
        )
        content.add_widget(self.voice_spinner)

        voices = _AndroidTTS.get_available_voices()
        if voices:
            v_names = [v[0] for v in voices]
            self.voice_spinner.values = v_names
            if _AndroidTTS._selected_voice:
                self.voice_spinner.text = _AndroidTTS._selected_voice
            else:
                self.voice_spinner.text = v_names[0]

        self.voice_spinner.bind(text=self.on_voice_change)
        content.add_widget(Widget())

        close_btn = PanelButton(text="Close", bg_color=PURPLE, height=dp(44))
        close_btn.bind(on_release=self.dismiss)
        content.add_widget(close_btn)

        self.content = content

    def on_voice_change(self, spinner, text):
        if text and text != "Default System Voice":
            _AndroidTTS.set_voice_by_name(text)
            App.get_running_app().speak(f"Voice changed to {text}")


# ---------------------------------------------------------------------------
# File Picker Fallback Popup
# ---------------------------------------------------------------------------
class FilePickerPopup(Popup):
    def __init__(self, callback, **kwargs):
        super().__init__(**kwargs)
        self.title = "Select Document (.pdf, .docx, .txt)"
        self.size_hint = (0.95, 0.95)
        self.callback = callback

        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        self.fc = FileChooserListView(
            path=os.path.expanduser("~"),
            filters=["*.pdf", "*.docx", "*.doc", "*.txt"]
        )
        content.add_widget(self.fc)

        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        cancel_btn = PanelButton(text="Cancel", bg_color=PANEL_BG)
        cancel_btn.bind(on_release=self.dismiss)
        select_btn = PanelButton(text="Select File", bg_color=PURPLE)
        select_btn.bind(on_release=self._on_select)

        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(select_btn)
        content.add_widget(btn_row)

        self.content = content

    def _on_select(self, *_a):
        if self.fc.selection:
            selected = self.fc.selection[0]
            self.dismiss()
            self.callback(selected)


# ---------------------------------------------------------------------------
# Application Entry Point Class
# ---------------------------------------------------------------------------
class LPTestApp(App):
    voice_enabled = BooleanProperty(True)

    def build(self):
        self.title = "LPTest"
        self.sm = ScreenManager(transition=NoTransition())

        self.landing_screen = LandingScreen(name="landing")
        self.count_screen = CountSelectScreen(name="count_select")
        self.quiz_screen = QuizScreen(name="quiz")
        self.summary_screen = SummaryScreen(name="summary")
        self.review_screen = ReviewScreen(name="review")

        self.sm.add_widget(self.landing_screen)
        self.sm.add_widget(self.count_screen)
        self.sm.add_widget(self.quiz_screen)
        self.sm.add_widget(self.summary_screen)
        self.sm.add_widget(self.review_screen)

        self.current_filepath = None
        self.questions = []
        self.active_questions = []
        self.current_q_index = 0
        self.score = 0
        self.user_answers = []
        self.review_q_index = 0
        self.selected_count = 10
        self.current_filename = ""

        return self.sm

    def speak(self, text: str):
        if not self.voice_enabled or not text:
            return
        if platform == "android":
            _AndroidTTS.speak(text)
        else:
            print(f"[Speech Output]: {text}")

    def toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        status = "On" if self.voice_enabled else "Off"
        self.landing_screen.voice_btn.text = f"Voice Guidance {status}"
        if self.voice_enabled:
            self.speak("Voice Guidance Enabled")
        else:
            self.speak("Voice Guidance Disabled")

    def open_settings(self):
        popup = SettingsPopup()
        popup.open()

    def browse_file(self):
        if platform == "android":
            try:
                from plyer import filechooser
                filechooser.open_file(on_selection=self.on_file_selected)
                return
            except Exception as e:
                print(f"Plyer chooser failed, fallback to popup: {e}")
        popup = FilePickerPopup(callback=self.on_file_selected_path)
        popup.open()

    def on_file_selected(self, selection):
        if selection:
            path = selection[0] if isinstance(selection, list) else selection
            self.on_file_selected_path(path)

    def on_file_selected_path(self, path: str):
        if not path or not os.path.exists(path):
            self.landing_screen.status_label.text = "Invalid file selected."
            ErrorPopup("Hindi mahanap o di-valid ang napiling file.").open()
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXT:
            self.landing_screen.status_label.text = f"Unsupported file type: {ext}"
            ErrorPopup(f"Hindi suportado ang ganitong uri ng file: {ext}\nGumamit lamang ng .pdf, .docx, .doc, o .txt").open()
            return

        self.current_filepath = path
        self.current_filename = os.path.basename(path)
        self.landing_screen.status_label.text = f"Binabasa ang: {self.current_filename}..."
        self.speak("Binabasa ang file, sandali lamang.")

        Clock.schedule_once(lambda dt: self._process_file_async(path), 0.1)

    def _process_file_async(self, path):
        try:
            print(f"LPTest Debug: Simula ng pag-extract ng text mula sa {path}")
            text = extract_text(path)

            if not text or len(text.strip()) < 20:
                print("LPTest Debug: Kulang o walang na-extract na text.")
                self.landing_screen.status_label.text = "Walang nabasang teksto sa file."
                ErrorPopup("Hindi makakuha ng sapat na teksto mula sa file na ito. Subukan ang ibang file.").open()
                return

            print(f"LPTest Debug: Na-extract ang text ({len(text)} characters). Sinusuri ang mga tanong...")
            qa_list = detect_existing_qa(text)

            if qa_list and len(qa_list) >= 5:
                self.questions = qa_list
                mode_note = f"May nakitang {len(qa_list)} na umiiral na tanong sa dokumento."
            else:
                print("LPTest Debug: Walang nakitang existing Q&A, gumagawa gamit ang generator...")
                generated = generate_questions(text)
                self.questions = generated
                mode_note = f"Gumawa ng {len(generated)} na tanong mula sa dokumento."

            if not self.questions:
                print("LPTest Debug: Nabigo gumawa ng mga tanong.")
                self.landing_screen.status_label.text = "Walang nabuong tanong."
                ErrorPopup("Hindi nakabuo ng mga tanong mula sa nilalaman ng file.").open()
                return

            total = len(self.questions)
            choices = []
            for count in PRESET_COUNTS:
                if count <= total:
                    choices.append((f"{count} Questions", count))
            choices.append((f"All Questions ({total})", total))

            print(f"LPTest Debug: Tagumpay! May {total} na tanong. Lilipat sa count_select screen.")
            self.count_screen.show_choices(choices, total, mode_note)
            self.sm.current = "count_select"
            self.speak("File loaded successfully. Please select the number of questions.")

        except Exception as e:
            print(f"LPTest Error sa pag-process ng file: {e}")
            traceback.print_exc()
            self.landing_screen.status_label.text = f"Error: {e}"
            ErrorPopup(f"Nagka-problema sa pagbasa ng file:\n{str(e)}").open()

    def start_quiz_with_count(self, count: int):
        self.selected_count = min(count, len(self.questions))
        self.active_questions = self.questions[:self.selected_count]
        self.current_q_index = 0
        self.score = 0
        self.user_answers = [None] * self.selected_count

        self.sm.current = "quiz"
        self.render_current_question()

    def render_current_question(self):
        q = self.active_questions[self.current_q_index]
        chosen = self.user_answers[self.current_q_index]
        locked = chosen is not None
        self.quiz_screen.render(
            q=q,
            index=self.current_q_index,
            total=self.selected_count,
            mode_note="",
            locked=locked,
            chosen=chosen
        )
        if not locked:
            self.speak(f"Question {self.current_q_index + 1}. {q['question']}")

    def select_option(self, idx: int):
        if self.user_answers[self.current_q_index] is not None:
            return

        self.user_answers[self.current_q_index] = idx
        q = self.active_questions[self.current_q_index]
        correct_idx = q.get("correctIndex")

        if idx == correct_idx:
            self.score += 1
            self.speak("Correct answer!")
        else:
            letters = ["A", "B", "C", "D"]
            correct_text = q["options"][correct_idx] if correct_idx is not None else ""
            self.speak(f"Incorrect. The correct answer is {letters[correct_idx]}, {correct_text}")

        self.render_current_question()

    def next_question(self):
        if self.current_q_index < self.selected_count - 1:
            self.current_q_index += 1
            self.render_current_question()
        else:
            quiz_history.save_quiz_result(
                filename=self.current_filename,
                score=self.score,
                total=self.selected_count,
                questions=self.active_questions,
                user_answers=self.user_answers
            )
            self.summary_screen.render(self.score, self.selected_count)
            self.sm.current = "summary"
            self.speak(f"Quiz complete! Your score is {self.score} out of {self.selected_count}.")

    def retake_current_quiz(self):
        self.start_quiz_with_count(self.selected_count)

    def start_review(self):
        self.review_q_index = 0
        self.sm.current = "review"
        self.render_review_question()

    def render_review_question(self):
        q = self.active_questions[self.review_q_index]
        chosen = self.user_answers[self.review_q_index]
        self.review_screen.render(q, self.review_q_index, self.selected_count, chosen)
        self.speak(f"Review question {self.review_q_index + 1}. {q['question']}")

    def next_review_q(self):
        if self.review_q_index < self.selected_count - 1:
            self.review_q_index += 1
            self.render_review_question()
        else:
            self.sm.current = "summary"

    def prev_review_q(self):
        if self.review_q_index > 0:
            self.review_q_index -= 1
            self.render_review_question()

    def retake_entry(self, entry: dict):
        self.current_filename = entry.get("filename", "Quiz")
        self.questions = entry.get("questions", [])
        if self.questions:
            self.start_quiz_with_count(len(self.questions))

    def review_entry(self, entry: dict):
        self.current_filename = entry.get("filename", "Quiz")
        self.active_questions = entry.get("questions", [])
        self.user_answers = entry.get("user_answers", [])
        self.selected_count = len(self.active_questions)
        if self.active_questions:
            self.start_review()

    def confirm_go_home(self):
        self.sm.current = "landing"
        self.landing_screen.refresh_history()
        self.speak("Returned to Home Screen.")

    def repeat_current(self):
        curr_screen = self.sm.current_screen
        if hasattr(curr_screen, "_voice_nav_items") and curr_screen._voice_nav_items:
            idx = curr_screen._voice_nav_index
            label = curr_screen._voice_nav_items[idx][0]
            self.speak(label)


if __name__ == '__main__':
    LPTestApp().run()

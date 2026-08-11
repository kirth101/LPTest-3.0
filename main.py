"""
LPTest (Kivy rebuild) — entry point.

This is a from-scratch UI rewrite of the Tkinter/Windows desktop LPTest,
built on Kivy so it has a real path to an Android APK (via buildozer /
python-for-android). The Windows-only pieces of the original app —
NVDA/JAWS/SAPI screen-reader announcements (accessible_output2) and the
edge-tts "Read Aloud" voice — are Windows APIs with no Android
equivalent, so they were dropped in the initial rebuild.

Accessibility note: Kivy draws its entire UI itself via OpenGL, bypassing
Android's native View hierarchy -- which is exactly what TalkBack reads
from. That means a Kivy app is invisible to TalkBack by default; there is
no setting that fixes this, and building real TalkBack support would mean
exposing Android's AccessibilityNodeInfo tree by hand, a large project on
its own. What this app does instead is a self-contained *spoken
navigation mode*: Android's own text-to-speech engine (via plyer) reads
the question, options, and results aloud automatically as the quiz
progresses, and every button announces what it does when pressed. It's
not a replacement for TalkBack, but it means a blind user isn't blocked
from using the app.

Reused as-is from the desktop app (plain Python, no OS-specific calls):
  - file_parser.py        (PDF/DOCX/TXT text extraction)
  - question_generator.py (detects existing Q&A in a file, or generates
                            new multiple-choice questions from it)
  - quiz_history.py        (local JSON history of past attempts)

Run on desktop for development/testing with:   python main.py
Build an Android .apk with:                     buildozer -v android debug
(see README_ANDROID.md for the full explanation of why that build step
can't be run inside this chat, and the two easiest ways to run it
yourself.)
"""
from __future__ import annotations

import os

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
# Palette — purple/violet theme
# ---------------------------------------------------------------------------
BG = (0.043, 0.043, 0.043, 1)
PANEL_BG = (0.086, 0.078, 0.129, 1)
PURPLE = (0.482, 0.235, 0.898, 1)          # primary accent -- buttons, icons
PURPLE_DARK = (0.322, 0.145, 0.671, 1)     # option button fill
PURPLE_LIGHT = (0.702, 0.549, 0.988, 1)    # headings / title text
BLUE_ACCENT = (0.376, 0.522, 0.984, 1)     # "Question X of Y" label
PINK_ACCENT = (0.902, 0.345, 0.596, 1)     # "Your Previous Quizzes" heading
FG = (0.961, 0.961, 0.961, 1)
GREEN = (0.184, 0.682, 0.306, 1)
RED = (0.851, 0.263, 0.184, 1)
MUTED = (0.659, 0.659, 0.659, 1)

# Change this to however you'd like to be credited on the home screen.
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
    """Base for the small round Home / Speak buttons. Draws its icon as
    plain vector lines instead of an emoji/symbol character -- emoji
    glyphs depend on the device having a font that includes them, and
    Kivy's bundled default font doesn't, so text like "\U0001F3E0" was
    rendering as an empty tofu box on-device instead of an actual icon.
    Vector lines always render correctly, on every device, regardless of
    font support."""
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
        """Subclasses return a list of Line() instances (empty points to
        start; _redraw() fills them in based on current size)."""
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
    """Plain gear/settings icon -- deliberately without a filled circle
    background (unlike Home/Speak), matching the understated gray gear
    that sits next to the Voice Guidance toggle in the reference design."""
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
    """Same idea as the desktop app's adaptive sizing: short options keep
    a comfortably large, thumb-friendly size; only genuinely long options
    step down. Unlike the desktop version we don't need pixel-perfect fit
    math here, because every options list lives inside a ScrollView (see
    QuizScreen) -- so nothing can ever get clipped/cut off the way the
    original Tkinter bug did. sp() (not dp()) is used so this also
    respects the user's own OS-level font-size/accessibility setting."""
    longest = max((len(o) for o in options), default=0)
    total = sum(len(o) for o in options)
    if longest <= 30 and total <= 140:
        return 17
    elif longest <= 55 and total <= 220:
        return 16
    elif longest <= 90 and total <= 320:
        return 15
    return 14


class _AndroidTTS:
    """Direct Android TextToSpeech wrapper (bypassing plyer.tts).

    plyer.tts recreates a brand-new TextToSpeech engine from scratch on
    every single call and polls in a sleep loop waiting for it to become
    ready -- slow, and it exposes no way to set a speech rate at all.
    This keeps one engine alive for the whole app (fast, immediate) and
    supports setSpeechRate() for the Settings screen."""
    _engine = None

    @classmethod
    def _get_engine(cls):
        if cls._engine is None:
            from jnius import autoclass
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            Locale = autoclass("java.util.Locale")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            cls._engine = TextToSpeech(PythonActivity.mActivity, None)
            cls._engine.setLanguage(Locale.US)
        return cls._engine

    @classmethod
    def speak(cls, message: str, rate: float = 1.0):
        from jnius import autoclass
        TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
        engine = cls._get_engine()
        engine.setSpeechRate(max(0.1, rate))
        engine.speak(message, TextToSpeech.QUEUE_FLUSH, None)


def _android_vibrate(seconds: float):
    """Direct Android Vibrator wrapper (bypassing plyer.vibrator), used
    for the haptic pulses on every focus change/activation. Kept as a
    plain function (not tied to any particular engine instance) since,
    unlike TTS, there's no setup cost worth caching here."""
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


def guarded_release(action):
    """Wrap a click handler (taking the running App as its one argument)
    so it's a no-op while Voice Guidance is on -- see App.voice_guard.
    Used for every ordinary on_release binding in the UI so direct
    single-taps only work when Voice Guidance is off; while it's on,
    only the double-tap-to-activate gesture (VoiceNavMixin) activates
    anything."""
    def handler(*_a):
        app = App.get_running_app()
        app.voice_guard(action)(app)
    return handler


def build_icon_bar(show_home: bool = True):
    """Home + Speak round icon buttons, sized to sit inline in a header
    row (next to a title/progress label) rather than floating on top of
    other content -- floating over the mode-note text was the visual bug
    reported earlier. Returns (bar, home_btn_or_None, speak_btn) so the
    caller can also register the buttons themselves as voice-nav items
    (with a real widget reference, so explore-by-touch can find them)."""
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


class VoiceNavMixin:
    """Adds TalkBack-style touch navigation to a Screen (or any widget),
    active only while Voice Guidance is on:

    - Explore by touch: dragging a finger across the screen moves focus
      onto whatever item it passes over and announces it immediately,
      like sliding a finger around to feel what's there.
    - Swipe left/right: moves focus to the previous/next item without
      needing to land exactly on it -- handy when exploring isn't
      practical.
    - Double-tap anywhere: activates whichever item currently has focus.
    - A short, distinct haptic pulse fires on every focus change and on
      activation, the same tactile confirmation TalkBack gives, so it
      reads as responsive rather than laggy.

    Every screen that uses this mixin populates `self._voice_nav_items`
    with (spoken_label, activate_callable, widget_or_None) covering
    everything meaningfully tappable on that screen -- including its own
    Home/Speak icons -- as soon as its content is built or changes. The
    widget reference is what makes touch-exploration possible: without
    it we can only do discrete swipes, not "what's under my finger".

    While Voice Guidance is on, ordinary single taps on buttons are
    intentionally NOT wired to activate anything directly (see
    App.voice_guard) -- only double-tap-to-activate does. That matches
    how a real screen reader behaves and protects a blind user from
    accidentally triggering the wrong thing while exploring; a sighted
    user who doesn't want this can just turn Voice Guidance off."""

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
        """A quick vibration pulse -- 15ms for a focus move, 35ms for an
        activation -- so exploring/swiping feels immediate and alive
        instead of silent or laggy. Goes straight through Android's own
        Vibrator API (see _android_vibrate) rather than plyer.vibrator,
        which had the same "recreate everything, hope it works" fragility
        as plyer.tts did -- this is easier to reason about and to debug
        if a pulse ever silently fails to fire."""
        if platform != "android":
            return
        try:
            _android_vibrate(0.015 if short else 0.035)
        except Exception as e:
            print(f"LPTest: haptic feedback failed: {e}")

    def _voice_nav_focus(self, index: int, *, haptic: bool = True):
        if not self._voice_nav_items or index == self._voice_nav_index:
            return
        self._voice_nav_index = index
        if haptic:
            self._haptic(short=True)
        label, _callback, _widget = self._voice_nav_items[index]
        App.get_running_app().speak(label)

    def _voice_nav_speak_current(self):
        app = App.get_running_app()
        if not app.voice_enabled or not self._voice_nav_items:
            return
        label, _callback, _widget = self._voice_nav_items[self._voice_nav_index]
        app.speak(label)

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
        """Which nav item (if any) is under `window_pos`, correctly
        accounting for scrolling/nesting -- to_widget() walks up the
        widget tree applying every ancestor's transform (including a
        ScrollView's current scroll offset), so this still works for
        options that have scrolled partway off-screen."""
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
        if app.voice_enabled and self.collide_point(*touch.pos):
            self._swipe_start = touch.pos
            # Explore-by-touch: landing a finger directly on an item
            # focuses it immediately, same as real screen readers.
            hit = self._voice_nav_hit_test(touch.pos)
            if hit is not None:
                self._voice_nav_focus(hit)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            hit = self._voice_nav_hit_test(touch.pos)
            if hit is not None:
                self._voice_nav_focus(hit)
        # Never swallow move events -- a ScrollView underneath still
        # needs them to keep scrolling working while exploring.
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            dx = touch.pos[0] - self._swipe_start[0]
            dy = touch.pos[1] - self._swipe_start[1]
            import time as _time
            now = _time.time()
            if abs(dx) > self._SWIPE_THRESHOLD and abs(dx) > abs(dy):
                # Horizontal swipe -> move focus. Right = next, left =
                # previous (the usual screen-reader convention). Vertical
                # drags fall through untouched below, so normal
                # scrolling still works everywhere it's needed.
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
    """A plain BoxLayout with the same touch-exploration/swipe/double-tap
    behavior as a Screen -- used for Popup content (e.g. the "leave
    quiz?" confirmation), since a Popup isn't a Screen and wouldn't
    otherwise get any of this."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()


# ---------------------------------------------------------------------------
# Landing screen
# ---------------------------------------------------------------------------
class LandingScreen(VoiceNavMixin, Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voice_nav_init()
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        self.add_widget(root)

        header = BoxLayout(size_hint_y=None, height=dp(50))
        title_box = BoxLayout(orientation="vertical")
        title = Label(text="Welcome to LPTest", font_size=sp(24), bold=True,
                      color=PURPLE_LIGHT, halign="left", valign="bottom")
        title.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        subtitle = Label(text=f"Developed by {DEVELOPER_NAME}", font_size=sp(13),
                          color=PURPLE_LIGHT, halign="left", valign="top")
        subtitle.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        title_box.add_widget(title)
        title_box.add_widget(subtitle)
        header.add_widget(title_box)
        _bar, _home, self._speak_btn = build_icon_bar(show_home=False)
        header.add_widget(_bar)
        root.add_widget(header)

        instructions = Label(
            text="Upload a file to start the quiz\nYou can turn On/Off the voice assistant below",
            font_size=sp(14), color=FG, size_hint_y=None, height=dp(56), halign="center"
        )
        instructions.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(instructions)

        self.upload_btn = PanelButton(text="Upload a file", bg_color=PURPLE, height=dp(56),
                                       font_size=sp(17))
        # Direct single-tap, deliberately NOT gated behind Voice Guidance
        # (see App.voice_guard) -- this is the home screen, and a sighted
        # user (or someone helping a blind user) needs a simple, ordinary
        # tap here at all times, most importantly to switch Voice
        # Guidance off again without first having to learn the
        # swipe/double-tap gestures. It's still also reachable via
        # explore+double-tap below, for a blind user starting the app.
        self.upload_btn.bind(on_release=lambda *_: App.get_running_app().browse_file())
        root.add_widget(self.upload_btn)

        toggle_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        self.voice_btn = PanelButton(text="Voice Guidance On", bg_color=PANEL_BG,
                                      font_size=sp(14))
        self.voice_btn.bind(on_release=lambda *_: App.get_running_app().toggle_voice())
        toggle_row.add_widget(self.voice_btn)
        self.gear_btn = GearIconButton()
        self.gear_btn.bind(on_release=lambda *_: App.get_running_app().open_settings())
        toggle_row.add_widget(self.gear_btn)
        root.add_widget(toggle_row)

        self.status_label = Label(text="", font_size=sp(13), color=MUTED,
                                   size_hint_y=None, height=dp(40))
        root.add_widget(self.status_label)

        root.add_widget(Label(text="Your Previous Quizzes", font_size=sp(16), bold=True,
                               color=PINK_ACCENT, size_hint_y=None, height=dp(36),
                               halign="left", valign="middle"))

        self.history_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.history_list)
        root.add_widget(scroller)

        # Swipe/explore-reachable from the moment the app opens -- this is
        # the screen a blind user lands on first, so "Upload a file" has
        # to be reachable here by touch, not just once already inside a
        # quiz. Direct tap ALSO works on every one of these (see above),
        # so this is a second, parallel way to reach the same actions.
        app = App.get_running_app
        self._set_voice_nav_items([
            ("Upload a file button", lambda: app().browse_file(), self.upload_btn),
            ("Voice Guidance toggle button", lambda: app().toggle_voice(), self.voice_btn),
            ("Settings button", lambda: app().open_settings(), self.gear_btn),
            ("Speak button, repeats the welcome message", lambda: app().repeat_current(), self._speak_btn),
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
            ("Speak button, repeats the welcome message",
             lambda: App.get_running_app().repeat_current(), self._speak_btn),
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
# Question-count selection
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
        root.add_widget(BoxLayout())  # spacer

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
        nav_items.append(("Speak button, repeats the question count options",
                           lambda: app.repeat_current(), self._speak_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Quiz screen
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

        # Bordered question card -- a plain outlined box around the
        # question text, matching the reference design, so it reads as
        # its own distinct panel rather than floating loosely at the top.
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
        self.explanation_label.bind(
            texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1] + dp(4)))
        root.add_widget(self.explanation_label)

        self.next_btn = PanelButton(text="Next Question", bg_color=PURPLE, height=dp(52),
                                     font_size=sp(15), disabled=True)
        self.next_btn.bind(on_release=guarded_release(lambda app: app.next_question()))
        root.add_widget(self.next_btn)

        self.option_widgets: list[OptionButton] = []

    def _redraw_question_border(self, widget, *_a):
        self._question_border.rectangle = (widget.x, widget.y, widget.width, widget.height)

    def render(self, q: dict, index: int, total: int, mode_note: str, locked: bool,
               chosen: int | None):
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
                self.status_label.text = (
                    f"Not quite \u2014 the correct answer is {letters[correct_idx]} {correct_text}"
                )
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
                for i in range(4)
            ]
        else:
            next_label = "Finish Quiz button" if index == total - 1 else "Next Question button"
            nav_items = [(next_label, lambda: app.next_question(), self.next_btn)]
        nav_items.append(("Home button", lambda: app.confirm_go_home(), self._home_btn))
        nav_items.append(("Speak button, repeats the current question",
                           lambda: app.repeat_current(), self._speak_btn))
        self._set_voice_nav_items(nav_items)


# ---------------------------------------------------------------------------
# Summary screen
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
        self.retry_btn = PanelButton(text="Retry Incorrect", bg_color=PURPLE, font_size=sp(13))
        self.retry_btn.bind(on_release=guarded_release(lambda app: app.retry_incorrect()))
        self.new_btn = PanelButton(text="Upload New File", bg_color=PANEL_BG, font_size=sp(13))
        self.new_btn.bind(on_release=guarded_release(lambda app: app.reset_to_landing()))
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
            ("Retry Incorrect button", lambda: app.retry_incorrect(), self.retry_btn),
            ("Upload New File button", lambda: app.reset_to_landing(), self.new_btn),
            ("Home button", lambda: app.confirm_go_home(), self._home_btn),
            ("Speak button, repeats your final score", lambda: app.repeat_current(), self._speak_btn),
        ])


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class LPTestApp(App):
    title = "LPTest"

    def build(self):
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
        self._count_select_prompt = ""

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

        Clock.schedule_once(lambda *_: self.speak(
            "Welcome to LPTest. Tap Upload File to begin, or tap Voice Guidance "
            "to turn off spoken narration."
        ), 1.0)
        return self.sm

    # -- spoken navigation (accessibility) --------------------------------
    def speak(self, text: str):
        """Speak `text` aloud via the device's own text-to-speech engine.

        Kivy draws its whole UI itself (OpenGL), bypassing the Android
        View hierarchy TalkBack reads from -- so a Kivy app is invisible
        to TalkBack no matter what we do inside Kivy. This is the
        pragmatic alternative: the app narrates itself. Every screen
        transition and quiz event speaks what just happened/what's on
        screen, so a blind user can follow along and act on it without
        needing to see anything, even though it isn't real TalkBack
        gesture navigation."""
        if not self.voice_enabled or not text:
            return
        if platform == "android":
            try:
                _AndroidTTS.speak(text, rate=self.speech_rate)
                return
            except Exception as e:
                print(f"LPTest: Android TTS failed, falling back to plyer: {e}")
        try:
            from plyer import tts
            tts.speak(message=text)
        except Exception:
            pass  # TTS isn't available on this platform/build -- fail silently

    def voice_guard(self, func):
        """Wrap a direct single-tap handler so it's a no-op while Voice
        Guidance is on. Real screen readers require a deliberate
        double-tap to activate anything specifically so a blind user
        exploring the screen doesn't accidentally trigger whatever their
        finger happens to land on first -- this makes every button
        behave the same way once Voice Guidance is on, activating only
        through the double-tap-to-activate gesture (see VoiceNavMixin),
        while leaving plain, ordinary single-tap behavior untouched for
        sighted users who leave Voice Guidance off."""
        def wrapped(*args, **kwargs):
            if self.voice_enabled:
                return
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
        """The gear icon next to Voice Guidance. Lets the speech rate be
        adjusted -- plyer.tts had no way to do this at all (see
        _AndroidTTS), so this is only possible now that speak() talks to
        Android's TextToSpeech directly."""
        content = BoxLayout(orientation="vertical", spacing=dp(16), padding=dp(20))
        content.add_widget(Label(
            text="Voice Guidance Speech Rate", font_size=sp(16), bold=True,
            color=FG, size_hint_y=None, height=dp(28)
        ))
        rate_label = Label(text=f"{self.speech_rate:.1f}x", font_size=sp(22), bold=True,
                            color=PURPLE_LIGHT, size_hint_y=None, height=dp(40))
        content.add_widget(rate_label)

        slider = Slider(min=0.5, max=2.0, value=self.speech_rate, step=0.1,
                         size_hint_y=None, height=dp(40))

        def on_change(_slider, value):
            self.speech_rate = round(value, 1)
            rate_label.text = f"{self.speech_rate:.1f}x"

        slider.bind(value=on_change)
        content.add_widget(slider)

        speed_row = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
        speed_row.add_widget(Label(text="Slower", font_size=sp(11), color=MUTED))
        speed_row.add_widget(Label(text="Faster", font_size=sp(11), color=MUTED))
        content.add_widget(speed_row)

        test_btn = PanelButton(text="Test Voice", bg_color=PURPLE, font_size=sp(14), height=dp(48))
        test_btn.bind(on_release=lambda *_: self.speak(
            "This is a test of the voice guidance speech rate."))
        content.add_widget(test_btn)

        popup = Popup(title="Settings", content=content, size_hint=(0.85, 0.55))
        close_btn = PanelButton(text="Close", bg_color=PANEL_BG, font_size=sp(14), height=dp(48))
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        content.add_widget(close_btn)

        popup.open()
        self.speak(f"Settings. Speech rate is {self.speech_rate:.1f} times normal speed. "
                    "Drag the slider to change it, or tap Test Voice to hear it.")

    def confirm_go_home(self):
        """The Home icon button. Rather than jumping straight back and
        silently discarding an in-progress quiz, ask first -- and read
        the question aloud immediately, since the person tapping this
        may not be able to see the confirmation dialog that popped up.

        The dialog content is a VoiceNavBoxLayout, not a plain one --
        without that, swipe/explore/double-tap (and the haptic feedback
        that goes with them) would silently stop working the moment this
        popup opened, even though Voice Guidance is still on. That was
        the bug: gestures worked everywhere except inside this dialog."""
        content = VoiceNavBoxLayout(orientation="vertical", spacing=dp(14), padding=dp(16))
        msg = Label(
            text="Go back to the home screen?\nThis will end your current quiz.",
            color=FG, font_size=sp(15), halign="center", valign="middle",
        )
        msg.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        content.add_widget(msg)

        popup = Popup(title="Leave Quiz?", content=content, size_hint=(0.85, 0.4),
                       auto_dismiss=False)

        btn_row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))

        def do_stay(*_a):
            popup.dismiss()
            self.speak("Staying on this screen.")

        def do_leave(*_a):
            popup.dismiss()
            self.reset_to_landing()

        stay_btn = PanelButton(text="No, stay here", bg_color=PANEL_BG, font_size=sp(14))
        stay_btn.bind(on_release=guarded_release(lambda app: do_stay()))
        leave_btn = PanelButton(text="Yes, go home", bg_color=PURPLE, font_size=sp(14))
        leave_btn.bind(on_release=guarded_release(lambda app: do_leave()))
        btn_row.add_widget(stay_btn)
        btn_row.add_widget(leave_btn)
        content.add_widget(btn_row)

        content._set_voice_nav_items([
            ("No, stay here button", do_stay, stay_btn),
            ("Yes, go home button", do_leave, leave_btn),
        ])

        popup.open()
        self.speak("Go back to the home screen? This will end your current quiz. "
                    "Swipe to choose, then double-tap to confirm.")

    def repeat_current(self):
        """The Speak icon button. Re-reads whatever the current screen is
        showing -- the same wording that would have been auto-announced
        when this screen first appeared, so it works as a general-purpose
        'say that again' the user can reach for any time."""
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
                self.speak(
                    f"Question {self.current_index + 1} of {len(self.questions)}. "
                    f"{q['question']} {opts}"
                )
            else:
                correct_idx = q.get("correctIndex")
                if prior == correct_idx:
                    msg = "You answered correctly."
                else:
                    correct_text = q["options"][correct_idx] if correct_idx is not None else "unknown"
                    letter = letters[correct_idx] if correct_idx is not None else "?"
                    msg = f"You answered incorrectly. The correct answer is option {letter}: {correct_text}."
                if q.get("explanation"):
                    msg += f" Why: {q['explanation']}"
                self.speak(msg)
        elif screen == "count_select":
            self.speak(self._count_select_prompt or self.mode_note)
        elif screen == "summary" and self.questions:
            total = len(self.questions)
            correct = sum(1 for i, q in enumerate(self.questions)
                          if self.user_answers[i] == q.get("correctIndex"))
            self.speak(f"Quiz complete. You scored {correct} out of {total}.")
        else:
            self.speak("Welcome to LPTest. Tap Upload File to begin.")

    # -- file loading -----------------------------------------------------
    def browse_file(self):
        self.speak("Opening file picker.")
        if platform == "android":
            try:
                self._android_pick_file()
                return
            except Exception as e:
                print(f"LPTest: Android file picker failed to open: {e}")
                self.speak("Couldn't open the file picker. Trying the backup file browser.")
                # fall through to the desktop-style picker as a backup
        self._browse_file_desktop()

    def _android_pick_file(self):
        """Open Android's real system document picker directly via
        pyjnius, instead of going through plyer.filechooser.

        plyer's Android file chooser resolves the picked file by reading
        the legacy `_data` column off the content:// URI -- but that
        column is routinely null on modern Android's scoped storage, and
        not just for cloud-backed files: plain local files (including
        .txt files picked from the ordinary Files/Downloads app) hit this
        too, which was the actual bug. The fix is to stop trying to
        resolve a filesystem path at all: read the picked file's bytes
        straight from its ContentResolver stream and copy them into our
        own app-private storage, which we know is always readable
        regardless of what the source provider does or doesn't expose."""
        from jnius import autoclass
        from android import activity, mActivity

        Intent = autoclass("android.content.Intent")

        if not hasattr(self, "_android_select_code"):
            import random
            self._android_select_code = random.randint(100000, 999999)
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
        # onActivityResult runs off Kivy's own event loop -- hop back
        # onto it via Clock before touching any widget or app state.
        Clock.schedule_once(lambda *_: self._android_copy_uri_to_temp(uri), 0)

    def _android_copy_uri_to_temp(self, uri):
        try:
            from jnius import autoclass
            from android import mActivity

            resolver = mActivity.getContentResolver()

            # OpenableColumns.DISPLAY_NAME works across virtually every
            # content provider (unlike the `_data` column) -- it's the
            # column SAF itself guarantees providers fill in.
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
            print(f"LPTest: failed to copy picked file: {e}")
            self._fail_load("Couldn't read that file. Please try a different file.")
            return

        self.load_file(dest_path)

    def _browse_file_desktop(self):
        """Kivy's own in-window file browser. Used on desktop, where a
        real filesystem path is always meaningful. On Android this is
        NOT used -- Android's scoped storage means an app-drawn file
        browser starting at a plain filesystem path can't see the
        user's actual Documents/Downloads at all, which was the original
        bug report ("can't select a file"). Android instead goes through
        browse_file()'s plyer/SAF path above, which opens the real
        system file picker and needs no storage permission."""
        chooser = FileChooserListView(filters=["*" + e for e in SUPPORTED_EXT] + ["*.*"],
                                       path=os.path.expanduser("~"))
        popup_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        popup_box.add_widget(chooser)
        btn_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        popup = Popup(title="Select a study document", content=popup_box, size_hint=(0.95, 0.95))

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
        # Broad guard by design: this runs from a Clock callback with no
        # console visible on a phone to see a traceback on, so an
        # unexpected error here (a corrupt file, a permission hiccup, an
        # edge case in a third-party parsing library) must never be
        # allowed to propagate and take down the whole app -- it should
        # surface as a normal, recoverable on-screen/spoken error instead.
        try:
            result = extract_text(path)
            if result.error:
                self._fail_load(result.error)
                return

            self.filepath = path
            self.current_quiz_filename = os.path.basename(path)
            note = (result.warning + "\n") if result.warning else ""

            existing = detect_existing_qa(result.text)
            if existing:
                questions = fill_missing_pieces_offline(existing, result.text)
                if questions:
                    self.mode_note = note + "Using your file's own questions."
                    self.offer_count_select(questions)
                    return

            chunks = chunk_text(result.text, result.headings)
            questions, skipped = generate_questions(chunks, result.text)
            if not questions:
                self._fail_load(
                    "We couldn't find enough distinct facts in this file to build a fair "
                    "quiz (need at least 4 distinct facts). Try a longer or more detailed file."
                )
                return

            skip_note = f" ({len(skipped)} section(s) skipped.)" if skipped else ""
            self.mode_note = note + "Questions generated from your file." + skip_note
            self.offer_count_select(questions)
        except Exception as e:
            print(f"LPTest: unexpected error while reading file {path!r}: {e}")
            self._fail_load(
                "Something went wrong reading that file. Please try a different file."
            )

    # -- question-count selection ------------------------------------------
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
        self._count_select_prompt = (
            f"{self.mode_note} How many questions would you like? Choose from: {labels}."
        )
        self.speak(self._count_select_prompt)

    def start_quiz_with_count(self, count: int):
        import random
        pool = list(self._pending_pool)
        random.shuffle(pool)
        self.start_quiz(pool[:count])

    # -- quiz flow -----------------------------------------------------
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
            msg = f"Incorrect. The correct answer is option {letter}: {correct_text}."
        if q.get("explanation"):
            msg += f" Why: {q['explanation']}"
        self.speak(msg)

    def next_question(self):
        if self.current_index >= len(self.questions) - 1:
            self.show_summary()
            return
        self.current_index += 1
        self.render_question()

    # -- summary -----------------------------------------------------
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
        self.speak("Back to the home screen. Tap Upload File to begin.")

    # -- history actions -----------------------------------------------------
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

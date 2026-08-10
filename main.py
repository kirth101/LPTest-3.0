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
# Palette — same design as the desktop app (black bg, orange accents)
# ---------------------------------------------------------------------------
BG = (0.043, 0.043, 0.043, 1)
PANEL_BG = (0.078, 0.078, 0.078, 1)
ORANGE = (0.886, 0.400, 0.102, 1)
ORANGE_DARK = (0.478, 0.208, 0.063, 1)
ORANGE_LIGHT = (1.0, 0.541, 0.239, 1)
FG = (0.961, 0.961, 0.961, 1)
GREEN = (0.184, 0.682, 0.306, 1)
RED = (0.851, 0.263, 0.184, 1)
MUTED = (0.659, 0.659, 0.659, 1)

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

<IconButton>:
    text_size: self.size
    halign: 'center'
    valign: 'middle'
    canvas.before:
        Color:
            rgba: self.bg_color
        Ellipse:
            pos: self.pos
            size: self.size
"""
Builder.load_string(KV)


class PanelButton(Button):
    bg_color = ListProperty(PANEL_BG)


class IconButton(ButtonBehavior, Label):
    """Small round icon button -- used for the Home / Speak controls that
    float in the top-right corner of each in-quiz screen so a screen-
    reader user (or anyone) can always get back home or hear the current
    screen again, from a predictable, fixed spot."""
    bg_color = ListProperty(ORANGE)

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(44), dp(44)))
        kwargs.setdefault("color", (1, 1, 1, 1))
        kwargs.setdefault("font_size", sp(20))
        super().__init__(**kwargs)


class OptionButton(ButtonBehavior, Label):
    bg_color = ListProperty(ORANGE_DARK)

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


def build_icon_bar(show_home: bool = True) -> BoxLayout:
    """Floating Home + Speak round icon buttons, anchored top-right. Added
    as an extra widget on top of a Screen's normal content (Screen behaves
    like a RelativeLayout, so this just overlaps in its own corner without
    disturbing the rest of the layout) -- always in the same predictable
    spot on every screen so it's easy to find without looking."""
    width = dp(100) if show_home else dp(56)
    bar = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint=(None, None),
                     size=(width, dp(44)), pos_hint={"right": 0.97, "top": 0.97})
    if show_home:
        home_btn = IconButton(text="\U0001F3E0")
        home_btn.bind(on_release=lambda *_: App.get_running_app().confirm_go_home())
        bar.add_widget(home_btn)
    speak_btn = IconButton(text="\U0001F50A")
    speak_btn.bind(on_release=lambda *_: App.get_running_app().repeat_current())
    bar.add_widget(speak_btn)
    return bar


# ---------------------------------------------------------------------------
# Landing screen
# ---------------------------------------------------------------------------
class LandingScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        self.add_widget(root)

        root.add_widget(Label(
            text="Welcome to LPTest", font_size=sp(26), bold=True,
            color=ORANGE_LIGHT, size_hint_y=None, height=dp(48)
        ))
        root.add_widget(Label(
            text="Upload a study file (PDF, Word, or text) to generate a quiz from it.",
            font_size=sp(14), color=MUTED, size_hint_y=None, height=dp(48)
        ))

        self.upload_btn = PanelButton(text="Upload File", bg_color=ORANGE, height=dp(56),
                                       font_size=sp(16))
        self.upload_btn.bind(on_release=lambda *_: App.get_running_app().browse_file())
        root.add_widget(self.upload_btn)

        self.voice_btn = PanelButton(text="\U0001F50A Voice Guidance: On", bg_color=PANEL_BG,
                                      height=dp(48), font_size=sp(13))
        self.voice_btn.bind(on_release=lambda *_: App.get_running_app().toggle_voice())
        root.add_widget(self.voice_btn)

        self.status_label = Label(text="", font_size=sp(13), color=MUTED,
                                   size_hint_y=None, height=dp(40))
        root.add_widget(self.status_label)

        root.add_widget(Label(text="Your Previous Quizzes", font_size=sp(16), bold=True,
                               color=ORANGE_LIGHT, size_hint_y=None, height=dp(36),
                               halign="left", valign="middle"))

        self.history_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.history_list.bind(minimum_height=self.history_list.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.history_list)
        root.add_widget(scroller)

    def on_pre_enter(self, *_a):
        self.refresh_history()

    def refresh_history(self):
        self.history_list.clear_widgets()
        history = list(reversed(quiz_history.load_history()))
        if not history:
            self.history_list.add_widget(Label(
                text="No previous quizzes yet.", color=MUTED, font_size=sp(13),
                size_hint_y=None, height=dp(32)
            ))
            return
        app = App.get_running_app()
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
            retake_btn = PanelButton(text="Retake", bg_color=ORANGE, size_hint=(None, None),
                                      width=dp(90), height=dp(40), font_size=sp(12))
            retake_btn.bind(on_release=lambda *_a, e=entry: app.retake_entry(e))
            review_btn = PanelButton(text="Review", bg_color=PANEL_BG, size_hint=(None, None),
                                      width=dp(90), height=dp(40), font_size=sp(12))
            review_btn.bind(on_release=lambda *_a, e=entry: app.review_entry(e))
            row.add_widget(retake_btn)
            row.add_widget(review_btn)
            self.history_list.add_widget(row)


# ---------------------------------------------------------------------------
# Question-count selection
# ---------------------------------------------------------------------------
class CountSelectScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(14))
        self.add_widget(root)
        root.add_widget(Label(text="How many questions?", font_size=sp(24), bold=True,
                               color=ORANGE_LIGHT, size_hint_y=None, height=dp(44)))
        self.desc = Label(text="", font_size=sp(13), color=MUTED, size_hint_y=None,
                           height=dp(60))
        root.add_widget(self.desc)
        self.btns_box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.btns_box.bind(minimum_height=self.btns_box.setter("height"))
        root.add_widget(self.btns_box)
        root.add_widget(BoxLayout())  # spacer
        self.add_widget(build_icon_bar())

    def show_choices(self, choices: list[tuple[str, int]], total: int, mode_note: str):
        self.desc.text = mode_note or f"{total} questions available."
        self.btns_box.clear_widgets()
        app = App.get_running_app()
        for label, n in choices:
            btn = PanelButton(text=label, bg_color=ORANGE_DARK, height=dp(52), font_size=sp(15))
            btn.bind(on_release=lambda *_a, count=n: app.start_quiz_with_count(count))
            self.btns_box.add_widget(btn)


# ---------------------------------------------------------------------------
# Quiz screen
# ---------------------------------------------------------------------------
class QuizScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        self.add_widget(root)

        top_bar = BoxLayout(size_hint_y=None, height=dp(28))
        self.progress_label = Label(text="", font_size=sp(13), color=MUTED, halign="left",
                                     valign="middle")
        self.progress_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        self.mode_label = Label(text="", font_size=sp(11), color=MUTED, halign="right",
                                 valign="middle", italic=True)
        self.mode_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        top_bar.add_widget(self.progress_label)
        top_bar.add_widget(self.mode_label)
        root.add_widget(top_bar)

        self.question_label = Label(text="", font_size=sp(20), bold=True, color=FG,
                                     halign="left", valign="top", size_hint_y=None)
        self.question_label.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        self.question_label.bind(texture_size=lambda w, *_: setattr(w, "height", w.texture_size[1]))
        q_scroller = ScrollView(size_hint=(1, 0.42))
        q_scroller.add_widget(self.question_label)
        root.add_widget(q_scroller)

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

        self.next_btn = PanelButton(text="Next Question", bg_color=ORANGE, height=dp(52),
                                     font_size=sp(15), disabled=True)
        self.next_btn.bind(on_release=lambda *_: App.get_running_app().next_question())
        root.add_widget(self.next_btn)

        self.add_widget(build_icon_bar())

        self.option_widgets: list[OptionButton] = []

        # -- swipe-to-navigate / double-tap-to-activate ----------------
        # Active only while Voice Guidance is on (see on_touch_down/up
        # below). This layers a simple, TalkBack-style touch exploration
        # on top of the app -- swipe to move a "focus" between the
        # options (or the Next button once answered), hear each one
        # named as focus lands on it, and double-tap anywhere to activate
        # whichever one is currently focused. Direct taps on a button
        # still work exactly as before regardless of this -- this is
        # purely additive, for when the user can't see well enough to
        # aim a tap at a specific button.
        self._voice_nav_items: list[tuple[str, object]] = []
        self._voice_nav_index = 0
        self._swipe_start = None
        self._last_tap_time = 0.0
        self._last_tap_pos = (0.0, 0.0)

    def _set_voice_nav_items(self, items: list[tuple[str, object]]):
        self._voice_nav_items = items
        self._voice_nav_index = 0

    def _voice_nav_speak_current(self):
        app = App.get_running_app()
        if not app.voice_enabled or not self._voice_nav_items:
            return
        label, _callback = self._voice_nav_items[self._voice_nav_index]
        app.speak(label)

    def _voice_nav_move(self, delta: int):
        if not self._voice_nav_items:
            return
        self._voice_nav_index = (self._voice_nav_index + delta) % len(self._voice_nav_items)
        self._voice_nav_speak_current()

    def _voice_nav_activate(self):
        if not self._voice_nav_items:
            return
        _label, callback = self._voice_nav_items[self._voice_nav_index]
        if callback:
            callback()

    def on_touch_down(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self.collide_point(*touch.pos):
            self._swipe_start = touch.pos
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        app = App.get_running_app()
        if app.voice_enabled and self._swipe_start is not None and self.collide_point(*touch.pos):
            dx = touch.pos[0] - self._swipe_start[0]
            dy = touch.pos[1] - self._swipe_start[1]
            import time as _time
            now = _time.time()
            if abs(dx) > dp(40) and abs(dx) > abs(dy):
                # Horizontal swipe -> move focus. Right = next, left =
                # previous, matching the usual screen-reader convention.
                # (Vertical drags fall through untouched below, so normal
                # scrolling in the question/options areas still works.)
                self._voice_nav_move(1 if dx > 0 else -1)
                self._swipe_start = None
                return True
            else:
                same_spot = (abs(touch.pos[0] - self._last_tap_pos[0]) < dp(60) and
                             abs(touch.pos[1] - self._last_tap_pos[1]) < dp(60))
                if now - self._last_tap_time < 0.4 and same_spot:
                    self._voice_nav_activate()
                    self._last_tap_time = 0.0
                    self._swipe_start = None
                    return True
                self._last_tap_time = now
                self._last_tap_pos = touch.pos
        self._swipe_start = None
        return super().on_touch_up(touch)

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
                    btn.text = f"{label}  \u2713 Correct"
                    btn.bg_color = GREEN
                elif i == chosen:
                    btn.text = f"{label}  \u2717 Your answer"
                    btn.bg_color = RED
                else:
                    btn.bg_color = ORANGE_DARK
            else:
                btn.bg_color = ORANGE_DARK
                btn.bind(on_release=lambda _w, idx=i: App.get_running_app().select_option(idx))
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
            elif q.get("sourceChunk"):
                snippet = q["sourceChunk"]
                if len(snippet) > 220:
                    snippet = snippet[:220].rsplit(" ", 1)[0] + "\u2026"
                self.explanation_label.text = f"From your file: \u201c{snippet}\u201d"
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
            self._set_voice_nav_items([
                (f"Option {spoken_letters[i]}: {q['options'][i] if i < len(q['options']) else ''}",
                 (lambda idx=i: app.select_option(idx)))
                for i in range(4)
            ])
        else:
            next_label = "Finish Quiz button" if index == total - 1 else "Next Question button"
            self._set_voice_nav_items([(next_label, lambda: app.next_question())])


# ---------------------------------------------------------------------------
# Summary screen
# ---------------------------------------------------------------------------
class SummaryScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        self.add_widget(root)

        self.heading = Label(text="Quiz Complete!", font_size=sp(24), bold=True,
                              color=ORANGE_LIGHT, size_hint_y=None, height=dp(40))
        root.add_widget(self.heading)
        self.score_label = Label(text="", font_size=sp(16), color=FG, size_hint_y=None,
                                  height=dp(32))
        root.add_widget(self.score_label)

        self.list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroller = ScrollView(size_hint=(1, 1))
        scroller.add_widget(self.list_box)
        root.add_widget(scroller)

        actions = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        home_btn = PanelButton(text="Home", bg_color=PANEL_BG, font_size=sp(13))
        home_btn.bind(on_release=lambda *_: App.get_running_app().reset_to_landing())
        retry_btn = PanelButton(text="Retry Incorrect", bg_color=ORANGE, font_size=sp(13))
        retry_btn.bind(on_release=lambda *_: App.get_running_app().retry_incorrect())
        new_btn = PanelButton(text="Upload New File", bg_color=PANEL_BG, font_size=sp(13))
        new_btn.bind(on_release=lambda *_: App.get_running_app().reset_to_landing())
        actions.add_widget(home_btn)
        actions.add_widget(retry_btn)
        actions.add_widget(new_btn)
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
        try:
            from plyer import tts
            tts.speak(message=text)
        except Exception:
            pass  # TTS isn't available on this platform/build -- fail silently

    def toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self.landing.voice_btn.text = (
            "\U0001F50A Voice Guidance: On" if self.voice_enabled
            else "\U0001F507 Voice Guidance: Off"
        )
        if self.voice_enabled:
            self.speak("Voice guidance on.")

    def confirm_go_home(self):
        """The Home icon button. Rather than jumping straight back and
        silently discarding an in-progress quiz, ask first -- and read
        the question aloud immediately, since the person tapping this
        may not be able to see the confirmation dialog that popped up."""
        self.speak("Go back to the home screen? This will end your current quiz.")

        content = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(16))
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
        stay_btn.bind(on_release=do_stay)
        leave_btn = PanelButton(text="Yes, go home", bg_color=ORANGE, font_size=sp(14))
        leave_btn.bind(on_release=do_leave)
        btn_row.add_widget(stay_btn)
        btn_row.add_widget(leave_btn)
        content.add_widget(btn_row)

        popup.open()

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

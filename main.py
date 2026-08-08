"""
LPTest (Kivy rebuild) — entry point.

This is a from-scratch UI rewrite of the Tkinter/Windows desktop LPTest,
built on Kivy so it has a real path to an Android APK (via buildozer /
python-for-android). The Windows-only pieces of the original app —
NVDA/JAWS/SAPI screen-reader announcements (accessible_output2), the
edge-tts "Read Aloud" voice, and Windows drag-and-drop — are Windows APIs
with no Android equivalent, so they are intentionally NOT part of this
rebuild (per the tradeoff agreed with the user). Android's own
accessibility story (TalkBack) is different enough that it would need
its own separate pass, not a straight port.

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
"""
Builder.load_string(KV)


class PanelButton(Button):
    bg_color = ListProperty(PANEL_BG)


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

        self.option_widgets: list[OptionButton] = []

    def render(self, q: dict, index: int, total: int, mode_note: str, locked: bool,
               chosen: int | None):
        letters = ["a.", "b.", "c.", "d."]
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
        return self.sm

    # -- file loading -----------------------------------------------------
    def browse_file(self):
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
        Clock.schedule_once(lambda *_: self._load_file_now(path), 0.05)

    def _load_file_now(self, path: str):
        result = extract_text(path)
        if result.error:
            self.landing.status_label.text = result.error
            self.landing.status_label.color = RED
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
            self.landing.status_label.text = (
                "We couldn't find enough distinct facts in this file to build a fair "
                "quiz (need at least 4 distinct facts). Try a longer or more detailed file."
            )
            self.landing.status_label.color = RED
            return

        skip_note = f" ({len(skipped)} section(s) skipped.)" if skipped else ""
        self.mode_note = note + "Questions generated from your file." + skip_note
        self.offer_count_select(questions)

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

    def select_option(self, idx: int):
        if self.locked:
            return
        self.locked = True
        self.user_answers[self.current_index] = idx
        self.render_question()

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

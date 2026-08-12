import os
import re
import json
import random
from datetime import datetime

# Kivy Imports
from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, RoundedRectangle, Line

# Baguhin ang Background Color ng Buong App (Dark Theme - Hex #0A0915)
Window.clearcolor = (0.04, 0.03, 0.08, 1)

# Plyer TTS
try:
    from plyer import tts
except ImportError:
    tts = None


# ==========================================
# CUSTOM STYLED UI WIDGETS (Eksaktong Design)
# ==========================================

class PurpleButton(Button):
    """Vibrant Purple Rounded Button para sa Main Actions at Quiz Options"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.bold = True
        self.font_size = '16sp'
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Solid Violet/Purple Fill (#582CBA)
            Color(0.34, 0.17, 0.73, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[12])


class PillButton(Button):
    """Dark Pill Button na may Light Border (Voice Guidance Button)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.bold = True
        self.font_size = '15sp'
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Dark Background
            Color(0.1, 0.08, 0.18, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[22])
            # Glowing Light Purple/Grey Outline Border
            Color(0.6, 0.5, 0.8, 0.8)
            Line(rounded_rectangle=(self.pos[0], self.pos[1], self.size[0], self.size[1], 22), width=1.3)


class CircleIconButton(Button):
    """Maliit na Round Icon Button para sa Top Right (Home at Speaker)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = (0, 0, 0, 0)
        self.color = (1, 1, 1, 1)
        self.font_size = '18sp'
        self.bold = True
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.34, 0.17, 0.73, 1)
            # Perfect Circle
            radius = min(self.size) / 2
            RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])


class QuestionBox(BoxLayout):
    """Kahon ng Tanong na may Grey Outline Border"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # Dark Card Background
            Color(0.02, 0.02, 0.04, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[6])
            # Grey Outline Border
            Color(0.6, 0.6, 0.65, 1)
            Line(rounded_rectangle=(self.pos[0], self.pos[1], self.size[0], self.size[1], 6), width=1.8)


# ==========================================
# 1. FILE PARSER LOGIC
# ==========================================
def extract_text(filepath):
    if not os.path.exists(filepath):
        return ""

    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".txt":
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading txt file: {e}")
            return ""

    elif ext == ".pdf":
        text = ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            if text.strip():
                return text
        except Exception:
            pass

        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(filepath)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            if text.strip():
                return text
        except Exception:
            pass

        return text

    elif ext in [".docx", ".doc"]:
        try:
            import docx
            doc = docx.Document(filepath)
            full_text = [p.text for p in doc.paragraphs if p.text]
            return "\n".join(full_text)
        except Exception as e:
            print(f"Error reading docx file: {e}")
            return ""

    return ""


# ==========================================
# 2. QUESTION GENERATOR LOGIC
# ==========================================
def detect_existing_qa(text):
    if not text or not text.strip():
        return []

    questions = []
    blocks = re.split(r'\n(?=(?:Q(?:uestion)?\s*\d+[:.]|\d+[\.\)]))\s*', text, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue

        q_text = lines[0]
        q_text = re.sub(r'^(?:Q(?:uestion)?\s*\d*[:.]|\d+[\.\)])\s*', '', q_text, flags=re.IGNORECASE)

        options = []
        ans_text = ""

        for line in lines[1:]:
            opt_match = re.match(r'^(?:[A-D][\.\)]|\([A-D]\))\s*(.*)', line, re.IGNORECASE)
            ans_match = re.match(r'^(?:Answer|Ans|Sagot)[:.]\s*(.*)', line, re.IGNORECASE)

            if opt_match:
                options.append(opt_match.group(1).strip())
            elif ans_match:
                ans_text = ans_match.group(1).strip()

        if q_text and len(options) >= 2:
            while len(options) < 4:
                options.append(f"Option {chr(65 + len(options))}")

            correct_idx = 0
            if ans_text:
                for i, opt in enumerate(options):
                    if ans_text.lower() in opt.lower() or ans_text.upper() == chr(65 + i):
                        correct_idx = i
                        break

            questions.append({
                "question": q_text,
                "options": options[:4],
                "correctIndex": correct_idx,
                "explanation": ""
            })

    return questions


def generate_questions(text, count=20):
    if not text:
        return []

    existing = detect_existing_qa(text)
    if len(existing) >= 1:
        return existing[:count]

    questions = []
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip().split()) > 6]

    for sentence in sentences:
        words = sentence.split()
        if len(words) < 5:
            continue

        target_idx = random.randint(0, len(words) - 1)
        target_word = re.sub(r'[^\w\s]', '', words[target_idx])

        if len(target_word) <= 3:
            continue

        masked_sentence = " ".join([w if i != target_idx else "______" for i, w in enumerate(words)])
        
        options = ["Option A", "Option B", "Option C", target_word]
        random.shuffle(options)
        correct_idx = options.index(target_word)

        questions.append({
            "question": f"Fill in the missing word:\n\"{masked_sentence}\"",
            "options": options,
            "correctIndex": correct_idx,
            "explanation": f"The full sentence is: \"{sentence}\""
        })

        if len(questions) >= count:
            break

    return questions


# ==========================================
# 3. QUIZ HISTORY LOGIC
# ==========================================
HISTORY_FILE = "quiz_history.json"

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading history: {e}")
        return []

def save_quiz_result(filename, score, total, questions, user_answers):
    history = load_history()
    entry = {
        "filename": filename,
        "score": score,
        "total": total,
        "questions": questions,
        "user_answers": user_answers,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    history.append(entry)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving quiz history: {e}")


# ==========================================
# 4. KIVY SCREENS (Styled UI)
# ==========================================

class UploadScreen(Screen):
    """HOME PAGE — Eksaktong gayagaya sa Reference Image 1"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=[20, 30, 20, 20], spacing=15)

        # 1. Header: Welcome to LPTest
        lbl_title = Label(
            text="[color=38BDF8][b]Welcome to [/b][/color][color=8B5CF6][b]LPTest[/b][/color]",
            markup=True,
            font_size='26sp',
            size_hint_y=None,
            height=40
        )
        layout.add_widget(lbl_title)

        # Sub-header: Developed by Direk Allan
        lbl_sub = Label(
            text="[color=7C3AED]Developed by Direk Allan[/color]",
            markup=True,
            font_size='15sp',
            size_hint_y=None,
            height=25
        )
        layout.add_widget(lbl_sub)

        # Instructions
        lbl_desc = Label(
            text="Upload a file to start the quiz\nYou can turn On/Off the\nvoice assistant below",
            halign='center',
            font_size='16sp',
            color=(0.9, 0.9, 0.95, 1),
            size_hint_y=None,
            height=80
        )
        layout.add_widget(lbl_desc)

        # 2. Big Purple "Upload a file" Button
        btn_upload = PurpleButton(text="Upload a file", size_hint_y=None, height=50)
        btn_upload.bind(on_release=self.open_file_chooser)
        layout.add_widget(btn_upload)

        # 3. Voice Guidance Pill + Settings Gear Row
        voice_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=45, spacing=15)
        
        self.btn_voice = PillButton(text="Voice Guidance On", size_hint_x=0.8)
        self.btn_voice.bind(on_release=self.toggle_voice)
        
        btn_settings = CircleIconButton(text="⚙", size_hint_x=None, width=45)
        
        voice_row.add_widget(self.btn_voice)
        voice_row.add_widget(btn_settings)
        layout.add_widget(voice_row)

        # Spacer
        layout.add_widget(BoxLayout(size_hint_y=None, height=15))

        # 4. Section Title: Your Previous Quizzes
        lbl_history_title = Label(
            text="[color=EC4899][b]Your Previous Quizzes[/b][/color]",
            markup=True,
            font_size='20sp',
            size_hint_y=None,
            height=35
        )
        layout.add_widget(lbl_history_title)

        # 5. History Scroll Area
        scroll = ScrollView(size_hint_y=1)
        self.history_list = GridLayout(cols=1, spacing=10, size_hint_y=None)
        self.history_list.bind(minimum_height=self.history_list.setter('height'))
        scroll.add_widget(self.history_list)
        layout.add_widget(scroll)

        self.add_widget(layout)

    def on_enter(self):
        # I-load ang mga dating quizzes
        self.history_list.clear_widgets()
        history = load_history()
        if not history:
            self.history_list.add_widget(Label(text="No previous quizzes found.", size_hint_y=None, height=30, color=(0.5, 0.5, 0.6, 1)))
            return

        for item in reversed(history):
            text = f"📄 {item.get('filename', 'Quiz')}  —  Score: {item.get('score', 0)} / {item.get('total', 0)}  ({item.get('date', '')})"
            lbl = Label(text=text, size_hint_y=None, height=40, color=(0.85, 0.85, 0.95, 1), font_size='13sp')
            self.history_list.add_widget(lbl)

    def toggle_voice(self, instance):
        app = App.get_running_app()
        app.voice_assistant_on = not app.voice_assistant_on
        if app.voice_assistant_on:
            self.btn_voice.text = "Voice Guidance On"
        else:
            self.btn_voice.text = "Voice Guidance Off"

    def open_file_chooser(self, instance):
        content = FileChooserListView(path=os.path.expanduser("~"))
        popup = Popup(title="Pumili ng File (.txt, .pdf, .docx)", content=content, size_hint=(0.9, 0.9))

        def select_file(chooser, selection, touch):
            if selection:
                filepath = selection[0]
                extracted_text = extract_text(filepath)
                if extracted_text.strip():
                    app = App.get_running_app()
                    app.raw_text = extracted_text
                    app.filename = os.path.basename(filepath)
                    popup.dismiss()
                    self.manager.current = "count_screen"
                else:
                    self.show_popup("Walang text na nabasa sa napiling file!")

        content.bind(on_submit=select_file)
        popup.open()

    def show_popup(self, msg):
        popup = Popup(title='Notice', content=Label(text=msg), size_hint=(0.8, 0.3))
        popup.open()


class CountScreen(Screen):
    """Screen para pumili ng bilang ng tanong"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=25, spacing=20)

        layout.add_widget(Label(text="[color=8B5CF6][b]How many questions?[/b][/color]", markup=True, font_size='22sp', size_hint_y=0.2))

        self.txt_count = TextInput(
            text="10",
            input_filter='int',
            multiline=False,
            size_hint=(0.5, None),
            height=50,
            font_size='24sp',
            halign='center',
            pos_hint={'center_x': 0.5}
        )
        layout.add_widget(self.txt_count)

        btn_start = PurpleButton(text="Start Quiz", size_hint_y=None, height=50)
        btn_start.bind(on_release=self.start_quiz)
        layout.add_widget(btn_start)

        btn_back = Button(text="Cancel", size_hint_y=None, height=40, background_color=(0,0,0,0), color=(0.7,0.7,0.8,1))
        btn_back.bind(on_release=self.go_back)
        layout.add_widget(btn_back)

        self.add_widget(layout)

    def start_quiz(self, instance):
        app = App.get_running_app()
        try:
            count = int(self.txt_count.text)
            if count <= 0:
                count = 5
        except ValueError:
            count = 10

        questions = generate_questions(app.raw_text, count=count)
        if not questions:
            popup = Popup(title='Warning', content=Label(text="No questions could be generated!"), size_hint=(0.8, 0.3))
            popup.open()
            return

        app.questions = questions
        app.current_q_index = 0
        app.score = 0
        app.user_answers = []

        quiz_screen = self.manager.get_screen("quiz_screen")
        quiz_screen.load_question()
        self.manager.current = "quiz_screen"

    def go_back(self, instance):
        self.manager.current = "upload_screen"


class QuizScreen(Screen):
    """QUIZ VIEW — Eksaktong gayagaya sa Reference Image 2"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', padding=15, spacing=15)

        # 1. Top Bar: Question Counter + Top-Right Home & Audio Icons
        top_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=40)
        
        self.lbl_progress = Label(
            text="[color=8B5CF6]Question 1 of 10[/color]",
            markup=True,
            font_size='16sp',
            halign='left',
            valign='middle',
            size_hint_x=0.7
        )
        self.lbl_progress.bind(size=self.lbl_progress.setter('text_size'))

        icons_box = BoxLayout(orientation='horizontal', spacing=8, size_hint_x=0.3)
        btn_home = CircleIconButton(text="🏠", size_hint=(None, None), size=(36, 36))
        btn_home.bind(on_release=self.go_home)
        btn_audio = CircleIconButton(text="🔊", size_hint=(None, None), size=(36, 36))
        btn_audio.bind(on_release=self.speak_question)

        icons_box.add_widget(btn_home)
        icons_box.add_widget(btn_audio)

        top_bar.add_widget(self.lbl_progress)
        top_bar.add_widget(icons_box)
        layout.add_widget(top_bar)

        # 2. Question Card (Naka-box at may Grey Border)
        self.q_card = QuestionBox(orientation='vertical', padding=15, size_hint_y=0.35)
        self.lbl_question = Label(
            text="",
            font_size='16sp',
            bold=True,
            halign='center',
            valign='middle',
            color=(1, 1, 1, 1)
        )
        self.lbl_question.bind(size=self.lbl_question.setter('text_size'))
        self.q_card.add_widget(self.lbl_question)
        layout.add_widget(self.q_card)

        # 3. Options Buttons Layout (a, b, c, d)
        self.options_layout = BoxLayout(orientation='vertical', spacing=10, size_hint_y=0.5)
        layout.add_widget(self.options_layout)

        # 4. Bottom "Next Question" / Skip button
        btn_next = Button(
            text="Next Question",
            size_hint_y=None,
            height=30,
            background_color=(0,0,0,0),
            color=(0.5, 0.5, 0.6, 1),
            font_size='14sp'
        )
        btn_next.bind(on_release=self.skip_question)
        layout.add_widget(btn_next)

        # Sound Effect File
        sound_file = "swipe.wav" if os.path.exists("swipe.wav") else ("swiping.wav" if os.path.exists("swiping.wav") else None)
        self.sound = SoundLoader.load(sound_file) if sound_file else None

        self.add_widget(layout)

    def load_question(self):
        app = App.get_running_app()
        q_idx = app.current_q_index
        q_data = app.questions[q_idx]

        self.lbl_progress.text = f"[color=8B5CF6]Question {q_idx + 1} of {len(app.questions)}[/color]"
        self.lbl_question.text = q_data["question"]

        self.options_layout.clear_widgets()
        prefixes = ["a. ", "b. ", "c. ", "d. "]

        for idx, opt in enumerate(q_data["options"]):
            prefix = prefixes[idx] if idx < 4 else ""
            btn = PurpleButton(text=f"{prefix}{opt}", size_hint_y=1)
            # Left-align text inside button for readability like reference
            btn.halign = 'left'
            btn.valign = 'middle'
            btn.bind(size=btn.setter('text_size'))
            btn.bind(on_release=lambda instance, chosen=idx: self.select_answer(chosen))
            self.options_layout.add_widget(btn)

        if self.sound:
            self.sound.play()

        # Automatic TTS reading if Voice Assistant is ON
        if app.voice_assistant_on:
            self.speak_question(None)

    def speak_question(self, instance):
        if tts:
            try:
                tts.speak(self.lbl_question.text)
            except Exception as e:
                print(f"TTS Error: {e}")

    def select_answer(self, choice_idx):
        app = App.get_running_app()
        q_data = app.questions[app.current_q_index]

        is_correct = (choice_idx == q_data["correctIndex"])
        if is_correct:
            app.score += 1

        app.user_answers.append({
            "selected": choice_idx,
            "correct": q_data["correctIndex"],
            "is_correct": is_correct
        })

        app.current_q_index += 1
        if app.current_q_index < len(app.questions):
            self.load_question()
        else:
            save_quiz_result(app.filename, app.score, len(app.questions), app.questions, app.user_answers)
            self.manager.get_screen("result_screen").show_results()
            self.manager.current = "result_screen"

    def skip_question(self, instance):
        self.select_answer(-1)

    def go_home(self, instance):
        self.manager.current = "upload_screen"


class ResultScreen(Screen):
    """Result Screen"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=25, spacing=15)
        
        self.lbl_score = Label(text="", markup=True, font_size='22sp', size_hint_y=0.3)
        self.layout.add_widget(self.lbl_score)

        btn_download = PurpleButton(text="📥 Download Questions & Answers", size_hint_y=None, height=50)
        btn_download.bind(on_release=self.download_questions)
        self.layout.add_widget(btn_download)

        btn_again = PurpleButton(text="Take Another Quiz", size_hint_y=None, height=50)
        btn_again.bind(on_release=self.restart)
        self.layout.add_widget(btn_again)

        self.add_widget(self.layout)

    def show_results(self):
        app = App.get_running_app()
        self.lbl_score.text = f"[color=38BDF8][b]Quiz Completed![/b][/color]\n\n[color=8B5CF6]Your Score: {app.score} / {len(app.questions)}[/color]"

    def download_questions(self, instance):
        app = App.get_running_app()
        if not app.questions:
            return

        download_path = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(download_path):
            download_path = os.getcwd()

        clean_filename = os.path.splitext(app.filename)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_filename = f"Quiz_{clean_filename}_{timestamp}.txt"
        full_path = os.path.join(download_path, out_filename)

        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(f"========================================\n")
                f.write(f" LPTest — SET OF QUESTIONS & ANSWERS\n")
                f.write(f" Source: {app.filename}\n")
                f.write(f" Score: {app.score} / {len(app.questions)}\n")
                f.write(f"========================================\n\n")

                letters = ["a", "b", "c", "d"]
                for idx, q in enumerate(app.questions):
                    f.write(f"Q{idx + 1}. {q['question']}\n")
                    for opt_idx, opt in enumerate(q['options']):
                        f.write(f"   {letters[opt_idx]}. {opt}\n")
                    
                    correct_letter = letters[q['correctIndex']]
                    correct_text = q['options'][q['correctIndex']]
                    f.write(f"   ✔ Correct Answer: {correct_letter}. {correct_text}\n\n")

            popup = Popup(
                title='Downloaded!',
                content=Label(text=f"Saved to:\n{full_path}", halign='center'),
                size_hint=(0.85, 0.4)
            )
            popup.open()

        except Exception as e:
            popup = Popup(title='Error', content=Label(text=f"Could not save file:\n{e}"), size_hint=(0.8, 0.4))
            popup.open()

    def restart(self, instance):
        self.manager.current = "upload_screen"


# ==========================================
# 5. MAIN APPLICATION
# ==========================================
class QuizApp(App):
    raw_text = ""
    filename = ""
    questions = []
    current_q_index = 0
    score = 0
    user_answers = []
    voice_assistant_on = True

    def build(self):
        sm = ScreenManager()
        sm.add_widget(UploadScreen(name="upload_screen"))
        sm.add_widget(CountScreen(name="count_screen"))
        sm.add_widget(QuizScreen(name="quiz_screen"))
        sm.add_widget(ResultScreen(name="result_screen"))
        return sm


if __name__ == "__main__":
    QuizApp().run()

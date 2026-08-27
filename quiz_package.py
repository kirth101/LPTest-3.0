"""
quiz_package.py

Implements the Online <-> Offline "bridge" from the app design:

  Online Mode ends with a Download button that saves the generated
  questions (with correct answers and choices) as a portable package file.

  Offline Mode loads that package back in later -- on this computer or a
  different one, with or without internet -- and replays it. No OCR, no
  AI call: the questions are already there. Every replay reshuffles the
  question order AND the choice order within each question, so retaking
  the same package doesn't mean memorizing "the 3rd option is always
  right."

Package format: plain JSON, ``.lptquiz`` extension (a JSON file with a
distinct extension so it isn't confused with some unrelated .json the user
might also have lying around, but any text editor / json.load can still
read it in a pinch).
"""

from __future__ import annotations
import copy
import json
import os
import random
from datetime import datetime
from typing import Optional

PACKAGE_EXT = ".lptquiz"
PACKAGE_MARKER = "lptest_package"
PACKAGE_VERSION = 1


def is_package_file(path: str) -> bool:
    """Cheap, extension-first check so we don't try to JSON-parse every
    .pdf/.docx a user drags in. Also accepts a plain .json IF its content
    carries our marker, so a package renamed/exported as .json still loads."""
    ext = os.path.splitext(path)[1].lower()
    if ext == PACKAGE_EXT:
        return True
    if ext == ".json":
        try:
            with open(path, "r", encoding="utf-8") as f:
                # Only peek at the start -- packages can have hundreds of
                # questions and we don't need to parse the whole thing twice.
                head = f.read(200)
            return f'"{PACKAGE_MARKER}"' in head
        except OSError:
            return False
    return False


def build_package(questions: list[dict], source_filename: str) -> dict:
    """Assemble the exportable package dict from a finished question set."""
    return {
        PACKAGE_MARKER: True,
        "version": PACKAGE_VERSION,
        "source_filename": source_filename,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "question_count": len(questions),
        "questions": questions,
    }


def save_package(path: str, questions: list[dict], source_filename: str) -> None:
    package = build_package(questions, source_filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def load_package(path: str) -> tuple[Optional[dict], Optional[str]]:
    """Returns (package, error). On success, package has at least
    'questions' (list[dict]) and 'source_filename'."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError) as e:
        return None, f"Couldn't open this quiz package ({e})."
    except json.JSONDecodeError as e:
        return None, f"This quiz package file is corrupted or not valid JSON ({e})."

    if not isinstance(data, dict) or not data.get(PACKAGE_MARKER):
        return None, "This doesn't look like an LPTest quiz package."

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        return None, "This quiz package has no questions in it."

    for q in questions:
        if not isinstance(q, dict) or "question" not in q or "options" not in q \
                or "correctIndex" not in q:
            return None, "This quiz package's question data looks corrupted."

    return data, None


def shuffle_for_replay(questions: list[dict]) -> list[dict]:
    """Smart Randomization: a fresh deep copy with the question order
    shuffled, and -- independently, per question -- the choice order
    shuffled too (with correctIndex recomputed to still point at the right
    answer). Called every time a package is loaded or a saved quiz is
    retaken, so no two attempts look identical."""
    shuffled = copy.deepcopy(questions)
    for q in shuffled:
        options = q.get("options") or []
        correct_idx = q.get("correctIndex")
        if not isinstance(correct_idx, int) or not (0 <= correct_idx < len(options)):
            continue
        correct_text = options[correct_idx]
        new_order = list(options)
        random.shuffle(new_order)
        q["options"] = new_order
        q["correctIndex"] = new_order.index(correct_text)
    random.shuffle(shuffled)
    return shuffled

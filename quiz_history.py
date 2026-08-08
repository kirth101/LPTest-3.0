"""
quiz_history.py

Persists completed quiz attempts to a small local JSON file so the landing
page can list "Your Previous Quizzes" — file name + score for each — and
let the user retake the same set of questions or review their answers
without needing to re-upload or re-parse the original file.

Storage location: ~/.lptest/history.json
- Kept outside the app's own folder so it survives the app being moved,
  updated, or rebuilt into a new .exe.
- Works the same whether run from source (`python main.py`) or as a
  packaged PyInstaller .exe.

Each saved entry is a full, self-contained snapshot of that attempt
(questions, options, correct answers, and the user's chosen answers), not
just a score — that's what makes "Retake" and "Review" possible even if
the original uploaded file is no longer available.
"""

from __future__ import annotations
import json
import os
import uuid
from datetime import datetime
from typing import Optional

_HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".lptest")
_HISTORY_FILE = os.path.join(_HISTORY_DIR, "history.json")


def configure_storage_dir(base_dir: str) -> None:
    """Point history storage at `base_dir` instead of the default
    ~/.lptest -- used on Android, where the app should write inside its
    own sandboxed data dir (App.user_data_dir) rather than a home
    directory that may not be writable/meaningful there. Call this once,
    before the first load_history()/save_attempt(), from the app's
    on_start."""
    global _HISTORY_DIR, _HISTORY_FILE
    _HISTORY_DIR = base_dir
    _HISTORY_FILE = os.path.join(_HISTORY_DIR, "history.json")

# Keep the file from growing without bound over months of use.
MAX_ENTRIES = 100


def _ensure_dir() -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)


def load_history() -> list[dict]:
    """Return saved attempts, oldest first. A missing or corrupt file
    quietly returns an empty list rather than crashing the app."""
    if not os.path.exists(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        pass
    return []


def _write_history(history: list[dict]) -> None:
    _ensure_dir()
    # Write to a temp file then atomically replace, so a crash mid-write
    # can't corrupt the existing history.
    tmp_path = _HISTORY_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _HISTORY_FILE)


def save_attempt(
    filename: str,
    questions: list[dict],
    user_answers: list,
    score: int,
    total: int,
    mode_note: str = "",
    filepath: Optional[str] = None,
) -> dict:
    """Append one completed attempt and persist it to disk. Returns the
    saved entry. Never raises — a failure to save (e.g. read-only disk)
    shouldn't interrupt the quiz the user just finished."""
    entry = {
        "id": uuid.uuid4().hex,
        "filename": filename,
        "filepath": filepath,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "score": score,
        "total": total,
        "mode_note": mode_note,
        "questions": questions,
        "user_answers": user_answers,
    }
    history = load_history()
    history.append(entry)
    if len(history) > MAX_ENTRIES:
        history = history[-MAX_ENTRIES:]
    try:
        _write_history(history)
    except OSError:
        pass
    return entry


def delete_entry(entry_id: str) -> None:
    history = [e for e in load_history() if e.get("id") != entry_id]
    try:
        _write_history(history)
    except OSError:
        pass

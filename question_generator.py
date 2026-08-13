"""
question_generator.py
Handles Existing Q&A Detection, Google Gemini API Generation (online),
and Offline Fallback (no internet needed).
"""

from __future__ import annotations
import re
import random
import json
from dataclasses import dataclass, field
from typing import Optional

import requests

random.seed()

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
DEFINITION_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9\-\s]{2,60}?)\s+(?:is|are|was|were|refers to|means|is defined as)\s+(.{15,220}?)[\.\!]?$"
)

# ---------------------------------------------------------------------------
# 1. Detect existing Q&A in uploaded files
# ---------------------------------------------------------------------------
_NUMBERED_Q_RE = re.compile(r"^\s*\d+[\.\)]\s*(.+?)\s*$")
_QLABEL_RE = re.compile(r"^\s*Q\s*[:.]\s*(.+)$", re.IGNORECASE)
_QHEADER_RE = re.compile(r"^\s*Question\s+\d+\s*[:.]?\s*(.*)$", re.IGNORECASE)
_ALABEL_RE = re.compile(r"^\s*(?:Correct\s+)?A(?:nswer)?\s*[:.]\s*(.+)$", re.IGNORECASE)
_LETTER_OPT_RE = re.compile(r"^\s*([a-dA-D])[\.\)]\s*(.+)$")
_ANSWER_KEY_LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\):-]\s*([a-dA-D])\s*$")
_ANSWER_LEADING_LETTER_RE = re.compile(r"^\s*([a-dA-D])[\.\):]\s*(.*)$")

def detect_existing_qa(text: str) -> Optional[list[dict]]:
    research_indicators = ["chapter i", "statement of the problem", "review of related literature", "methodology", "presentation, analysis"]
    text_lower = text.lower()
    matches_count = sum(1 for ind in research_indicators if ind in text_lower)
    if matches_count >= 2:
        return None

    lines = [l for l in text.splitlines()]
    n = len(lines)
    questions: list[dict] = []
    i = 0
    q_index = 0

    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        m_num = _NUMBERED_Q_RE.match(line)
        if m_num and _ANSWER_KEY_LINE_RE.match(line):
            m_num = None
        m_qlabel = _QLABEL_RE.match(line)
        m_qheader = _QHEADER_RE.match(line) if not (m_num or m_qlabel) else None

        if m_num or m_qlabel or m_qheader:
            q_index += 1
            options: list[str] = []

            if m_num or m_qlabel:
                q_text = (m_num or m_qlabel).group(1).strip()
                i += 1
            else:
                text_lines = []
                same_line_text = m_qheader.group(1).strip()
                if same_line_text:
                    text_lines.append(same_line_text)
                i += 1
                while i < n:
                    nxt = lines[i].strip()
                    if not nxt:
                        i += 1
                        if text_lines:
                            break
                        continue
                    if (_LETTER_OPT_RE.match(nxt) or _ALABEL_RE.match(nxt) or
                            _NUMBERED_Q_RE.match(nxt) or _QLABEL_RE.match(nxt) or
                            _QHEADER_RE.match(nxt)):
                        break
                    text_lines.append(nxt)
                    i += 1
                q_text = " ".join(text_lines).strip()
                if not q_text:
                    continue

            answer_letter = None
            while i < n:
                nxt = lines[i].strip()
                if not nxt:
                    i += 1
                    continue
                m_opt = _LETTER_OPT_RE.match(nxt)
                m_ans = _ALABEL_RE.match(nxt)
                if m_opt:
                    options.append(m_opt.group(2).strip())
                    i += 1
                    continue
                if m_ans:
                    ans_raw = m_ans.group(1).strip()
                    m_letter = _ANSWER_LEADING_LETTER_RE.match(ans_raw)
                    if len(ans_raw) == 1 and ans_raw.lower() in "abcd":
                        answer_letter = ans_raw.lower()
                    elif m_letter:
                        answer_letter = m_letter.group(1).lower()
                    i += 1
                    continue
                break

            if options and answer_letter:
                idx = ord(answer_letter) - ord("a")
                if 0 <= idx < len(options):
                    questions.append({
                        "question": q_text,
                        "options": options[:4],
                        "correctIndex": idx,
                        "sourceChunk": q_text,
                        "explanation": "Loaded from existing file/review material.",
                        "_qnum": q_index,
                    })
                    continue
        i += 1

    if not questions or len(questions) < 2:
        return None
    return questions


# ---------------------------------------------------------------------------
# 2. Chunking & Gemini Online Generation
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    content: str
    label: str

def chunk_text(text: str, headings: list[tuple[str, int]] | None = None, target_words: int = 300) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    buffer_paras: list[str] = []
    word_count = 0
    chunks: list[Chunk] = []
    chunk_num = 1

    for para in paragraphs:
        buffer_paras.append(para)
        word_count += len(para.split())
        if word_count >= target_words:
            content = "\n".join(buffer_paras)
            chunks.append(Chunk(content=content, label=f"Section {chunk_num}"))
            chunk_num += 1
            buffer_paras = []
            word_count = 0
    if buffer_paras:
        content = "\n".join(buffer_paras)
        if chunks:
            chunks[-1].content += "\n" + content
        else:
            chunks.append(Chunk(content=content, label="Section 1"))
    return chunks

def _finalize_question(question: str, options: list[str], correct_index: int, source_chunk: str, explanation: Optional[str] = None) -> dict:
    return {
        "question": question,
        "options": options,
        "correctIndex": correct_index,
        "sourceChunk": source_chunk[:280],
        "explanation": explanation or "No explanation provided.",
    }

# "-latest" aliases auto-follow Google's current recommended model in
# that tier over time, so this never needs bumping by hand as specific
# Gemini versions get retired -- see https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = "gemini-flash-latest"

_QUESTION_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "question": {"type": "STRING"},
            "options": {"type": "ARRAY", "items": {"type": "STRING"}, "minItems": 4, "maxItems": 4},
            "correctIndex": {"type": "INTEGER"},
            "explanation": {"type": "STRING"},
        },
        "required": ["question", "options", "correctIndex", "explanation"],
    },
}

def generate_questions_with_gemini(text: str, api_key: str) -> tuple[list[dict], Optional[str]]:
    """Ask Gemini to generate MCQs from `text` via a direct REST API call
    (using `requests`, already a proven dependency in this Android build)
    -- deliberately NOT via the `google-generativeai` / `google-genai`
    Python SDKs, since:
      1. `google-generativeai` (the SDK this file used to import) was
         permanently deprecated by Google on November 30, 2025 -- it's
         no longer maintained at all.
      2. Pulling in the newer `google-genai` SDK instead would add a
         chain of new pip dependencies (httpx, pydantic, google-auth,
         websockets, ...) that have never been proven to cross-compile
         under python-for-android -- exactly the kind of fragile,
         hard-to-diagnose Android build risk this project already hit
         once with the `freetype` recipe. A plain REST call over
         `requests` sidesteps that risk entirely.
    "gemini-flash-latest" is a Google-maintained alias that always
    points at their current recommended Flash model, so this doesn't
    need to be hand-updated as specific model versions (like the old
    hardcoded gemini-1.5-flash here before) get retired over time.
    Returns (questions, error) -- on ANY failure (no package needed here
    so that's not a failure mode, but: no key, network error, bad
    response, zero usable items, ...) questions is [] and error is a
    short human-readable reason; never raises.
    """
    if not text or not text.strip():
        return [], "No text to generate questions from."
    if not api_key or not api_key.strip():
        return [], "Gemini API Key is missing."

    prompt = f"""
Act as a professional test creator and expert educator. Based on the following study text, research paper, or module,
generate multiple-choice questions (MCQs) that test deep comprehension, key concepts, findings, and important details.

Return ONLY a JSON array of objects with this exact structure:
[
    {{
        "question": "The question text here?",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correctIndex": 0,
        "explanation": "Detailed explanation of why this answer is correct based on the text."
    }}
]

Text to analyze:
{text[:15000]}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": _QUESTION_SCHEMA,
        },
    }

    try:
        resp = requests.post(url, params={"key": api_key}, json=payload, timeout=30)
    except requests.RequestException as e:
        return [], f"Gemini request failed ({type(e).__name__}: {e})"

    if resp.status_code != 200:
        # Google's error responses are themselves small JSON objects with
        # a human-readable message -- surface that instead of just the
        # status code where possible (e.g. "API key not valid").
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        return [], f"Gemini API Error: HTTP {resp.status_code} - {detail}"

    try:
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        questions_data = json.loads(raw_text)
    except Exception as e:
        return [], f"Gemini returned an unexpected response ({type(e).__name__}: {e})"

    formatted_questions = []
    for q in questions_data:
        try:
            if "question" not in q or "options" not in q or "correctIndex" not in q:
                continue
            options = [str(o) for o in q["options"]][:4]
            correct_index = int(q["correctIndex"])
            if len(options) != 4 or not (0 <= correct_index < 4):
                continue  # malformed item -- skip it, don't fail the whole batch
            formatted_questions.append(_finalize_question(
                question=str(q["question"]),
                options=options,
                correct_index=correct_index,
                source_chunk=text[:200],
                explanation=q.get("explanation", "Correct answer based on the lesson module.")
            ))
        except Exception:
            continue

    if not formatted_questions:
        return [], "Gemini returned empty or invalid question structures."
    return formatted_questions, None


# ---------------------------------------------------------------------------
# 3. Offline Fallback Generator
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "of", "to", "in", "on", "for", "with", "as", "by", "at", "from",
    "that", "this", "these", "those", "it", "its", "their", "his", "her",
    "he", "she", "they", "we", "you", "i", "not", "will", "can", "has",
    "have", "had", "into", "than", "then", "also", "such",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{3,}")


def _candidate_words(full_text: str) -> list[str]:
    """Distinct, real content words drawn from the WHOLE document, used
    as wrong-answer options below -- real words the student's own file
    actually uses, not placeholder text like "Option A"."""
    seen_lower: set[str] = set()
    out: list[str] = []
    for w in _WORD_RE.findall(full_text):
        lw = w.lower()
        if lw in _STOPWORDS or lw in seen_lower:
            continue
        seen_lower.add(lw)
        out.append(w)
    return out


def generate_questions_offline(chunks: list[Chunk], full_text: str) -> tuple[list[dict], list[str]]:
    questions: list[dict] = []
    skipped: list[str] = []
    word_pool = _candidate_words(full_text)

    for chunk in chunks:
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(chunk.content) if len(s.split()) >= 8]
        if not sentences:
            skipped.append(chunk.label)
            continue

        fact = sentences[0]
        words = fact.split()
        mid = len(words) // 2

        # Walk outward from the middle of the sentence looking for a real
        # content word to blank out -- skips short/stop words (so "the"
        # or "of" never becomes the answer) and strips trailing
        # punctuation so the correct option doesn't end in a stray comma.
        target = None
        target_idx = None
        for offset in range(len(words)):
            for idx in (mid + offset, mid - offset):
                if 0 <= idx < len(words):
                    candidate = words[idx].strip(".,;:!?\"'()")
                    if len(candidate) >= 4 and candidate.lower() not in _STOPWORDS:
                        target, target_idx = candidate, idx
                        break
            if target is not None:
                break
        if target is None:
            skipped.append(chunk.label)
            continue

        blanked = " ".join("_____" if i == target_idx else w for i, w in enumerate(words))

        # Real distractor words pulled from elsewhere in the SAME
        # document, instead of literal placeholder text -- a student
        # can no longer spot the correct answer just by noticing it's
        # the only option that isn't named "Option A/B/C".
        distractor_pool = [w for w in word_pool if w.lower() != target.lower()]
        random.shuffle(distractor_pool)
        distractors = distractor_pool[:3]
        if len(distractors) < 3:
            skipped.append(chunk.label)  # not enough other distinct words in this file
            continue

        options = distractors + [target]
        random.shuffle(options)
        questions.append(_finalize_question(
            f"Complete the statement: \"{blanked}\"",
            options, options.index(target), chunk.content,
            explanation=f"Derived from offline module text: {fact}"
        ))
    return questions, skipped

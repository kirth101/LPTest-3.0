"""
question_generator.py
Handles both Existing Q&A Detection (for offline review/re-upload of downloaded files)
and Google Gemini API Question Generation (for raw modules/lessons) with offline fallback.
"""

from __future__ import annotations
import re
import random
import json
from dataclasses import dataclass, field
from typing import Optional

random.seed()

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
DEFINITION_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9\-\s]{2,60}?)\s+(?:is|are|was|were|refers to|means|is defined as)\s+(.{15,220}?)[\.\!]?$"
)
_LEADING_ARTICLE_RE = re.compile(r"^(The|A|An)\s+")
NUMBER_RE = re.compile(r"\b\d{1,4}(?:[.,]\d+)?%?\b")
PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z]{2,}(?:[ \t][A-Z][a-zA-Z]{2,}){0,2})\b")

GENERIC_STOPWORDS = {
    "The", "This", "That", "These", "Those", "It", "They", "There", "Chapter",
    "Section", "Figure", "Table", "Introduction", "Conclusion", "Summary",
}

# ---------------------------------------------------------------------------
# 1. Detect existing Q&A in uploaded files (Para sa offline re-upload ng downloaded files)
# ---------------------------------------------------------------------------

_NUMBERED_Q_RE = re.compile(r"^\s*\d+[\.\)]\s*(.+?)\s*$")
_QLABEL_RE = re.compile(r"^\s*Q\s*[:.]\s*(.+)$", re.IGNORECASE)
_QHEADER_RE = re.compile(r"^\s*Question\s+\d+\s*[:.]?\s*(.*)$", re.IGNORECASE)
_ALABEL_RE = re.compile(r"^\s*(?:Correct\s+)?A(?:nswer)?\s*[:.]\s*(.+)$", re.IGNORECASE)
_LETTER_OPT_RE = re.compile(r"^\s*([a-dA-D])[\.\)]\s*(.+)$")
_ANSWER_KEY_LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\):-]\s*([a-dA-D])\s*$")
_ANSWER_LEADING_LETTER_RE = re.compile(r"^\s*([a-dA-D])[\.\):]\s*(.*)$")

def _parse_answer_key_block(lines: list[str]) -> dict[int, str]:
    key = {}
    for line in lines:
        for match in _ANSWER_KEY_LINE_RE.finditer(line):
            key[int(match.group(1))] = match.group(2).lower()
        for match in re.finditer(r"(\d+)\s*[-.:]\s*([a-dA-D])", line):
            key[int(match.group(1))] = match.group(2).lower()
    return key

def detect_existing_qa(text: str) -> Optional[list[dict]]:
    """Idine-detect kung ang in-upload na file ay mayroon nang mga tanong at pagpipilian (tulad ng na-download na quiz file)."""
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
            explanation_answer_text = None

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
                    else:
                        explanation_answer_text = ans_raw
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
            elif options:
                questions.append({
                    "question": q_text,
                    "options": options[:4],
                    "correctIndex": 0, # Default fallback if index is missing
                    "sourceChunk": q_text,
                    "explanation": "Loaded from existing file.",
                    "_qnum": q_index,
                })
                continue
        i += 1

    if not questions:
        return None

    usable = [q for q in questions if q.get("correctIndex") is not None]
    if len(usable) < max(1, len(questions) * 0.3):
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

def generate_questions_with_gemini(text: str, api_key: str) -> tuple[list[dict], Optional[str]]:
    """Gumagamit ng Google Gemini API para mag-generate ng mga tanong mula sa buong module/lesson."""
    try:
        import google.generativeai as genai
    except ImportError:
        return [], "Google Generative AI package is not installed. Run: pip install google-generativeai"

    if not api_key:
        return [], "Gemini API Key is missing."

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Act as a professional test creator and expert educator. Based on the following study text/module, 
        generate multiple-choice questions (MCQs). Ensure questions test deep comprehension, key concepts, and important details.
        
        Return ONLY a valid JSON array containing objects with this exact structure, with no markdown formatting outside:
        [
            {{
                "question": "The question text here?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correctIndex": 0,
                "explanation": "Detailed explanation of why this answer is correct."
            }}
        ]

        Text to analyze:
        {text[:15000]}
        """

        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        questions_data = json.loads(response_text.strip())
        formatted_questions = []
        
        for q in questions_data:
            if "question" in q and "options" in q and "correctIndex" in q:
                formatted_questions.append(_finalize_question(
                    question=q["question"],
                    options=q["options"][:4],
                    correctIndex=int(q["correctIndex"]),
                    source_chunk=text[:200],
                    explanation=q.get("explanation", "Correct answer based on the lesson module.")
                ))
                
        if not formatted_questions:
            return [], "Gemini returned empty or invalid question structures."
            
        return formatted_questions, None

    except Exception as e:
        return [], f"Gemini API Error: {str(e)}"


# ---------------------------------------------------------------------------
# 3. Offline Fallback Generator (Sakaling walang internet at walang existing Q&A)
# ---------------------------------------------------------------------------

def generate_questions_offline(chunks: list[Chunk], full_text: str) -> tuple[list[dict], list[str]]:
    questions: list[dict] = []
    skipped: list[str] = []

    for chunk in chunks:
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(chunk.content) if len(s.split()) >= 8]
        if sentences:
            fact = sentences[0]
            words = fact.split()
            target = words[len(words)//2]
            blanked = fact.replace(target, "_____", 1)
            options = ["Option A", "Option B", "Option C", target]
            random.shuffle(options)
            questions.append(_finalize_question(
                f"Complete the statement: \"{blanked}\"",
                options, options.index(target), chunk.content,
                explanation=f"Derived from offline module text: {fact}"
            ))
        else:
            skipped.append(chunk.label)

    return questions, skipped

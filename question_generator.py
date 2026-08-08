"""
question_generator.py

Offline / rule-based pipeline (no external AI calls, works with no internet):

1. detect_existing_qa()  -> reuse the student's own questions if the file already has them
2. chunk_text()          -> break source text into study-worthy segments
3. generate_questions()  -> build MCQ objects {question, options, correctIndex, sourceChunk}
                             from chunks when no existing Q&A was found

Every question dict follows the shape described in the spec:
{
    "question": str,
    "options": [str, str, str, str],
    "correctIndex": int,
    "sourceChunk": str,
    "explanation": Optional[str],
}
"""

from __future__ import annotations
import re
import random
from dataclasses import dataclass, field
from typing import Optional

random.seed()  # system randomness; shuffle differs each run

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
# 1. Detect existing Q&A in the uploaded file (study guides, worksheets, etc.)
# ---------------------------------------------------------------------------

_NUMBERED_Q_RE = re.compile(r"^\s*\d+[\.\)]\s*(.+?)\s*$")
_QLABEL_RE = re.compile(r"^\s*Q\s*[:.]\s*(.+)$", re.IGNORECASE)
# "Question 1" / "Question 1:" / "Question 1: <text>" as its own header line
# (question text may follow on the same line, or on the line(s) after it —
# see the gathering loop in detect_existing_qa).
_QHEADER_RE = re.compile(r"^\s*Question\s+\d+\s*[:.]?\s*(.*)$", re.IGNORECASE)
# Accepts "A:", "Answer:", and "Correct Answer:" style lines.
_ALABEL_RE = re.compile(r"^\s*(?:Correct\s+)?A(?:nswer)?\s*[:.]\s*(.+)$", re.IGNORECASE)
_LETTER_OPT_RE = re.compile(r"^\s*([a-dA-D])[\.\)]\s*(.+)$")
_ANSWER_KEY_LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\):-]\s*([a-dA-D])\s*$")
# Pulls a leading option letter out of an answer line's remainder, e.g.
# "Correct Answer: B. Abstract reasoning" -> letter "B", text "Abstract reasoning".
_ANSWER_LEADING_LETTER_RE = re.compile(r"^\s*([a-dA-D])[\.\):]\s*(.*)$")


def _parse_answer_key_block(lines: list[str]) -> dict[int, str]:
    """Parse a trailing 'Answer key' section like '1. B  2. A  3. C'."""
    key = {}
    for line in lines:
        for match in _ANSWER_KEY_LINE_RE.finditer(line):
            key[int(match.group(1))] = match.group(2).lower()
        # also handle space-separated inline keys: "1-b 2-a 3-c"
        for match in re.finditer(r"(\d+)\s*[-.:]\s*([a-dA-D])", line):
            key[int(match.group(1))] = match.group(2).lower()
    return key


def detect_existing_qa(text: str) -> Optional[list[dict]]:
    """Return parsed question objects if the file already contains its own
    quiz content, else None. Heuristic pattern matching (not exhaustive)."""
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
        # A numbered line is only a real question header if it isn't ALSO
        # a compact answer-key entry like "3. B" (just a number + a lone
        # option letter, nothing else) -- those get parsed separately by
        # _parse_answer_key_block below and must not be swallowed here as
        # a phantom one-letter "question".
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
                # "Question N" header — the question text may be on the same
                # line, and/or continue on the following line(s) up until a
                # blank line, an option line, an answer line, or the next
                # question header.
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
                    continue  # header with no question text at all -- skip
            answer_letter = None
            explanation_answer_text = None

            # gather following lettered options and/or an inline answer/A: line
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
                        # "B. Abstract reasoning" / "B) Abstract reasoning" ->
                        # letter B, regardless of trailing option text.
                        answer_letter = m_letter.group(1).lower()
                    else:
                        explanation_answer_text = ans_raw
                    i += 1
                    continue
                # Not an option or an answer line yet. Some exam formats
                # give a sub-list of statements between the question stem
                # and its real A-D options, e.g.:
                #   1. Which are most likely ... raised by authoritarian
                #      parents?
                #   I. Fearful  II. Inhibited  III. Hostile  IV. Withdrawn
                #   A. I and II   B. I, II, and III  ...
                # That "I. Fearful II. ..." line is part of the question
                # body, not a stray line -- swallow it into q_text instead
                # of stopping, but ONLY before any real options have been
                # collected, and only if it isn't itself the start of the
                # next question (checked the same way the main loop would).
                looks_like_next_question = (
                    (_NUMBERED_Q_RE.match(nxt) and not _ANSWER_KEY_LINE_RE.match(nxt))
                    or _QLABEL_RE.match(nxt) or _QHEADER_RE.match(nxt)
                )
                if not options and not looks_like_next_question:
                    q_text = (q_text + " " + nxt).strip()
                    i += 1
                    continue
                break  # next question / unrelated content

            if options and answer_letter:
                idx = ord(answer_letter) - ord("a")
                if 0 <= idx < len(options):
                    questions.append({
                        "question": q_text,
                        "options": options[:4],
                        "correctIndex": idx,
                        "sourceChunk": q_text,
                        "explanation": None,
                        "_qnum": q_index,
                    })
                    continue
            elif options and not answer_letter:
                # options exist but no marked answer yet -- fill in later from answer key
                questions.append({
                    "question": q_text,
                    "options": options[:4],
                    "correctIndex": None,
                    "sourceChunk": q_text,
                    "explanation": None,
                    "_qnum": q_index,
                })
                continue
            elif explanation_answer_text and not options:
                # Q:/A: style with a free-text answer, no options yet.
                questions.append({
                    "question": q_text,
                    "options": None,
                    "correctIndex": None,
                    "sourceChunk": q_text,
                    "explanation": explanation_answer_text,
                    "_correct_text": explanation_answer_text,
                    "_qnum": q_index,
                })
                continue
            else:
                # A bare "N. ...?" line with nothing following it isn't usable.
                questions.append({
                    "question": q_text,
                    "options": None,
                    "correctIndex": None,
                    "sourceChunk": q_text,
                    "explanation": None,
                    "_correct_text": None,
                    "_qnum": q_index,
                })
                continue
        i += 1

    if not questions:
        return None

    # look for a trailing answer-key block for questions missing correctIndex
    key = _parse_answer_key_block(lines[-30:])
    if key:
        for q in questions:
            if q.get("correctIndex") is None and q.get("options"):
                letter = key.get(q["_qnum"])
                if letter:
                    idx = ord(letter) - ord("a")
                    if 0 <= idx < len(q["options"]):
                        q["correctIndex"] = idx

    # require a majority of found "questions" to actually look like real
    # quiz content (has options+answer OR a free-text answer) or we bail out
    usable = [q for q in questions if q.get("correctIndex") is not None or q.get("_correct_text")]
    if len(usable) < max(2, len(questions) * 0.4):
        return None

    return questions


def fill_missing_pieces_offline(existing_questions: list[dict], full_text: str) -> list[dict]:
    """For §4's 'fall back to AI generation only for the missing piece' —
    since we're offline-only, we build distractors/options ourselves using
    the same term pool used by the generator, instead of calling an AI model.
    """
    pool = _build_distractor_pool(full_text)
    finished = []
    for q in existing_questions:
        options = q.get("options")
        correct_idx = q.get("correctIndex")
        correct_text = q.get("_correct_text")

        if options and correct_idx is not None:
            finished.append(_finalize_question(q["question"], options, correct_idx, q["sourceChunk"]))
            continue

        if options and correct_idx is None:
            # Options exist, but we don't know which is right -- can't safely guess.
            continue

        if correct_text:
            distractors = _pick_distractors(correct_text, pool, count=3)
            if len(distractors) < 3:
                continue  # not enough material to build fair options; skip (edge case handling)
            opts = distractors + [correct_text]
            random.shuffle(opts)
            finished.append(_finalize_question(q["question"], opts, opts.index(correct_text), q["sourceChunk"]))
            continue
        # no options, no answer text at all -> unusable, skip
    return finished


# ---------------------------------------------------------------------------
# 2. Chunking
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    content: str
    label: str


def chunk_text(text: str, headings: list[tuple[str, int]] | None = None,
                target_words: int = 120) -> list[Chunk]:
    headings = headings or []
    chunks: list[Chunk] = []

    if headings:
        offsets = [h[1] for h in headings] + [len(text)]
        for idx, (heading, start) in enumerate(headings):
            end = offsets[idx + 1]
            segment = text[start:end].strip()
            if len(segment.split()) >= 15:
                chunks.append(Chunk(content=segment, label=heading))
        if chunks:
            return chunks

    # No usable headings -> paragraph-based chunking with a fixed word window
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    buffer_paras: list[str] = []
    word_count = 0
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
        if word_count >= 15 and chunks:
            chunks.append(Chunk(content=content, label=f"Section {chunk_num}"))
        elif not chunks:
            chunks.append(Chunk(content=content, label="Section 1"))
        elif chunks:
            # too-small leftover: merge into the previous chunk instead of dropping it
            chunks[-1].content += "\n" + content

    return chunks


# ---------------------------------------------------------------------------
# 3. Question generation
# ---------------------------------------------------------------------------

def _finalize_question(question: str, options: list[str], correct_index: int,
                        source_chunk: str) -> dict:
    return {
        "question": question,
        "options": options,
        "correctIndex": correct_index,
        "sourceChunk": source_chunk[:280],
        "explanation": None,
    }


def _split_into_sentences(text: str) -> list[str]:
    """Split on line breaks first (so headings/titles never bleed into the
    next sentence), then on sentence-ending punctuation within each line."""
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        sentences.extend(s.strip() for s in SENTENCE_SPLIT_RE.split(line) if s.strip())
    return sentences


def _extract_definitions(chunk_text_: str) -> list[tuple[str, str]]:
    """Find 'Term is/are definition' style sentences."""
    found = []
    for s in _split_into_sentences(chunk_text_):
        s_no_article = _LEADING_ARTICLE_RE.sub("", s)
        m = DEFINITION_RE.match(s_no_article)
        if m:
            term, definition = m.group(1).strip(), m.group(2).strip()
            if (term.split()[0] not in GENERIC_STOPWORDS and len(term.split()) <= 6
                    and len(term) >= 3):
                found.append((term.capitalize() if term.islower() else term, definition))
    return found


def _extract_key_facts(chunk_text_: str) -> list[str]:
    """Sentences containing a number or proper noun — used as fallback facts."""
    facts = [s for s in _split_into_sentences(chunk_text_)
             if len(s.split()) >= 8 and (NUMBER_RE.search(s) or PROPER_NOUN_RE.search(s))]
    return facts


def _build_distractor_pool(full_text: str) -> dict[str, list[str]]:
    """Collect candidate distractor material from the whole document,
    grouped by 'kind' so distractors stay plausible (numbers vs numbers,
    names vs names, definitions vs definitions)."""
    pool = {"definition": [], "number": [], "proper_noun": []}
    for term, definition in _extract_definitions(full_text):
        pool["definition"].append(definition)
    for line in full_text.splitlines():
        for m in NUMBER_RE.finditer(line):
            pool["number"].append(m.group(0))
        for m in PROPER_NOUN_RE.finditer(line):
            name = m.group(1)
            if name.split()[0] not in GENERIC_STOPWORDS:
                pool["proper_noun"].append(name)
    for k in pool:
        pool[k] = list(dict.fromkeys(pool[k]))  # de-dupe, keep order
    return pool


def _pick_distractors(correct: str, pool: dict[str, list[str]], count: int = 3) -> list[str]:
    if NUMBER_RE.fullmatch(correct.strip()):
        candidates = [c for c in pool["number"] if c != correct]
    elif correct in pool["definition"]:
        candidates = [c for c in pool["definition"] if c != correct]
    else:
        candidates = [c for c in pool["proper_noun"] if c != correct]

    if len(candidates) < count:
        # widen the net across all pools as a last resort
        everything = [c for group in pool.values() for c in group if c != correct]
        candidates = list(dict.fromkeys(candidates + everything))

    random.shuffle(candidates)
    return candidates[:count]


def generate_questions(chunks: list[Chunk], full_text: str) -> tuple[list[dict], list[str]]:
    """Returns (questions, skipped_chunk_labels)."""
    pool = _build_distractor_pool(full_text)
    questions: list[dict] = []
    skipped: list[str] = []

    for chunk in chunks:
        definitions = _extract_definitions(chunk.content)
        made_one = False

        for term, definition in definitions:
            distractors = _pick_distractors(definition, pool, count=3)
            if len(distractors) < 3:
                continue
            options = distractors + [definition]
            random.shuffle(options)
            questions.append(_finalize_question(
                f"What is {term}?", options, options.index(definition), chunk.content
            ))
            made_one = True
            break  # one solid question per chunk keeps pacing even

        if not made_one:
            facts = _extract_key_facts(chunk.content)
            fact_used = False
            for fact in facts:
                num_match = NUMBER_RE.search(fact)
                noun_match = PROPER_NOUN_RE.search(fact)
                target_match = num_match or noun_match
                if not target_match:
                    continue
                answer = target_match.group(0)
                blanked = fact[:target_match.start()] + "_____" + fact[target_match.end():]
                distractors = _pick_distractors(answer, pool, count=3)
                if len(distractors) < 3:
                    continue
                options = distractors + [answer]
                random.shuffle(options)
                questions.append(_finalize_question(
                    f"Fill in the blank: \"{blanked.strip()}\"",
                    options, options.index(answer), chunk.content
                ))
                fact_used = True
                break

            if not fact_used:
                skipped.append(chunk.label)  # not enough distinct facts (edge case)

    return questions, skipped

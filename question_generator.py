"""
question_generator.py

Pipeline (kept in sync with the desktop LPTest's question_generator.py):

1. detect_existing_qa()        -> reuse the student's own questions if the file already has them
2. chunk_text()                -> break source text into study-worthy segments
3. generate_questions_with_proxy() -> online generation (text AND/OR pictures) via LPTest's
                                   own proxy service, no API key required from the user
4. generate_questions_with_gemini() -> optional escape hatch: call Gemini directly with the
                                   user's OWN key instead of the proxy
5. generate_questions()         -> fully offline, rule-based fallback (no internet, no AI)

Every question dict follows this shape:
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
import json
import random
from dataclasses import dataclass, field
from typing import Optional, Callable

import requests

random.seed()  # system randomness; shuffle differs each run

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
DEFINITION_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9\-\s]{2,60}?)\s+(?:is|are|was|were|refers to|means|is defined as)\s+(.{15,220}?)[\.\!]?$"
)
_LEADING_ARTICLE_RE = re.compile(r"^(The|A|An)\s+")
NUMBER_RE = re.compile(r"\b\d{1,4}(?:[.,]\d+)?%?\b")
PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z]{2,}(?:[ \t][A-Z][a-zA-Z]{2,}){0,2})\b")

# A line that starts a new enumerated item -- "A.", "b)", "139.", "1)", or a
# Roman-numeral sub-item like "I.", "II.", "III.", "IV." (very common in PH
# board-exam reviewers that list statements as I/II/III/IV before asking
# "which combination is correct?"). Capped at X (1-10) to avoid accidentally
# matching an ordinary capitalized word.
OPTION_LABEL_RE = re.compile(
    r"^(?:[A-Da-d][.\)]\s+|\(?[A-Da-d]\)\s+|\d{1,4}[.\)]\s+|"
    r"(?:I{1,3}|IV|VI{0,3}|IX|X)[.\)]\s+)"
)

GENERIC_STOPWORDS = {
    "the", "this", "that", "these", "those", "it", "they", "there", "chapter",
    "section", "figure", "table", "introduction", "conclusion", "summary",
    # Interrogative/question words -- a sentence like "What is the main
    # focus of...?" matches the definition pattern grammatically, but it's
    # a question (often a heading), not an actual "X is Y" definition, so
    # it must never become the quiz term itself.
    "what", "who", "whom", "whose", "which", "where", "when", "why", "how",
}


# ---------------------------------------------------------------------------
# 1. Detect existing Q&A in the uploaded file (study guides, worksheets, etc.)
# ---------------------------------------------------------------------------

_NUMBERED_Q_RE = re.compile(r"^\s*\d+[\.\)]\s*(.+?)\s*$")
_QLABEL_RE = re.compile(r"^\s*Q\s*[:.]\s*(.+)$", re.IGNORECASE)
# "Question 1" / "Question 1:" / "Question 1: <text>" as its own header line
# (question text may follow on the same line, or on the line(s) after it —
# see the gathering loop in detect_existing_qa).
_QHEADER_RE = re.compile(r"^\s*Question\s*[:.]?\s*\d+\s*[:.]?\s*(.*)$", re.IGNORECASE)
# Accepts "A:", "Answer:", and "Correct Answer:" style lines.
_ALABEL_RE = re.compile(r"^\s*(?:Correct\s+)?A(?:nswer)?\s*[:.]\s*(.+)$", re.IGNORECASE)
_LETTER_OPT_RE = re.compile(r"^\s*(?:Option\s+)?([a-dA-D])[\.\):]\s*(.+)$", re.IGNORECASE)
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
                # Not an option or an answer line yet. Some exam formats give
                # a sub-list of statements between the question stem and its
                # real A-D options (e.g. "I. Fearful  II. Inhibited ..."
                # before "A. I and II  B. I, II, and III ..."). Keep folding
                # such lines into the question text instead of stopping, but
                # ONLY before any real options have been collected, and only
                # if it isn't itself the start of the next question.
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
    """When the file has its own questions but some are missing options or a
    marked answer, build the missing pieces ourselves using the same
    distractor pool as the offline generator, instead of calling an AI model."""
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
                continue  # not enough material to build fair options; skip
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


def _finalize_question(question: str, options: list[str], correct_index: int,
                        source_chunk: str, explanation: Optional[str] = None) -> dict:
    return {
        "question": question,
        "options": options,
        "correctIndex": correct_index,
        "sourceChunk": source_chunk[:280],
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# 3. Online generation via LPTest's own proxy (recommended path -- no API
#    key needed from the user, and the only path that supports pictures)
# ---------------------------------------------------------------------------

# DEFAULT_APP_TOKEN is NOT a Gemini/OpenRouter key -- it's a narrow-scope,
# rotatable token that only unlocks LPTest's own Cloudflare Worker (which
# holds the real AI key server-side). Safe to ship in the APK: if it ever
# needs to be revoked, only the Worker's token needs rotating, not any real
# provider key.
DEFAULT_PROXY_URL = "https://lptest-gemini-proxy.lptest-alman001.workers.dev"
DEFAULT_APP_TOKEN = "Nw5Zp7IyAcdFibHO6HIPKZ1MSQVfFAvqu471ll_c55E"

PROXY_MAX_QUESTIONS_PER_CALL = 20  # hard ceiling on the Worker's side -- requesting more just gets clamped
PROXY_MAX_CALLS = 5                # caps how many of the Worker's daily-per-IP quota one upload can spend
PROXY_MAX_TEXT_CHARS = 15000       # the Worker truncates to this per call regardless of what's sent

MIN_TARGET_QUESTIONS = 50
MAX_TARGET_QUESTIONS = 100
WORDS_PER_QUESTION = 15


def target_question_count(text: str) -> int:
    """How many questions to ask for. Always requests at least
    MIN_TARGET_QUESTIONS (50) regardless of how short the source text is --
    for AI generation this is just a request (the model does its best with
    whatever material it's given); for the offline generator, the actual
    number returned is still capped by how many genuinely distinct facts
    exist in the text (see generate_questions()) rather than padded out
    with repeats or low-quality filler."""
    word_count = len(text.split())
    if word_count == 0:
        return MIN_TARGET_QUESTIONS
    estimate = word_count // WORDS_PER_QUESTION
    return max(MIN_TARGET_QUESTIONS, min(MAX_TARGET_QUESTIONS, estimate))


def _split_text_for_proxy(text: str, num_segments: int) -> list[str]:
    """Splits text into num_segments roughly-equal, non-overlapping pieces
    (by word count) so each proxy call sees different material and
    generates different questions, rather than all calls repeating the same
    content. Each piece is kept under PROXY_MAX_TEXT_CHARS since the Worker
    truncates beyond that anyway."""
    words = text.split()
    if num_segments <= 1 or len(words) < num_segments * 20:
        return [text[:PROXY_MAX_TEXT_CHARS]]
    per = max(1, len(words) // num_segments)
    segments = []
    for i in range(num_segments):
        start = i * per
        end = None if i == num_segments - 1 else start + per
        piece = " ".join(words[start:end])
        if piece.strip():
            segments.append(piece[:PROXY_MAX_TEXT_CHARS])
    return segments or [text[:PROXY_MAX_TEXT_CHARS]]


def _proxy_post(proxy_url: str, app_token: str, payload: dict) -> tuple[Optional[list], Optional[str]]:
    """One POST to the Worker. Returns (questions, error) -- the Worker's
    success response is already a plain JSON array, no unwrapping needed."""
    try:
        resp = requests.post(
            proxy_url,
            headers={"Content-Type": "application/json", "X-App-Token": app_token},
            json=payload,
            timeout=90,
        )
    except requests.RequestException as e:
        return None, f"Couldn't reach the question service ({type(e).__name__}: {e})"

    if resp.status_code == 401:
        return None, "The proxy rejected this app's token."
    if resp.status_code == 429:
        try:
            detail = resp.json().get("error", "")
        except Exception:
            detail = ""
        return None, detail or "Daily quiz-generation limit reached. Try again tomorrow."
    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        return None, f"Question service error: HTTP {resp.status_code} - {detail}"

    try:
        data = resp.json()
    except Exception as e:
        return None, f"Question service returned an unexpected response ({e})"

    if isinstance(data, dict) and "error" in data:
        return None, data["error"]
    if not isinstance(data, list):
        return None, "Question service returned an unexpected response shape."
    return data, None


def generate_questions_with_proxy(
    text: str, proxy_url: str = DEFAULT_PROXY_URL, app_token: str = DEFAULT_APP_TOKEN,
    images: Optional[list[str]] = None, target_count: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[list[dict], Optional[str]]:
    """Generates questions via the lptest-proxy Cloudflare Worker instead of
    calling any AI provider directly -- this app never holds a real API key.
    Each call is capped at PROXY_MAX_QUESTIONS_PER_CALL by the Worker itself,
    so reaching a larger target_count means multiple calls, each over a
    different slice of the text (see _split_text_for_proxy) so they produce
    different questions instead of repeating each other. Images and text are
    mutually exclusive per call (matching worker.js's contract), so if both
    are present, one image call and one-or-more text calls are made and
    merged. All calls run CONCURRENTLY (not one-after-another) -- with up to
    5 calls at ~90s worst case each, doing them sequentially could mean
    several minutes of waiting; in parallel it's roughly as fast as the
    single slowest call. If given, progress_callback(done, total) fires
    (from whichever worker thread finishes each call, NOT the caller's
    thread) every time one of the calls completes, so a caller on the Kivy
    main thread can poll/display real progress via Clock.schedule_once
    rather than guessing. Returns (questions, error) -- error is only
    returned if every call failed and nothing could be salvaged."""
    import concurrent.futures

    if not proxy_url or not app_token:
        return [], "Online question generation isn't configured (missing proxy URL/token)."

    images = images or []
    has_text = len(text.strip()) >= 20
    count = target_count if target_count is not None else target_question_count(text)

    # Build the list of (payload, source_label) calls to make, then fire
    # them all at once on a small thread pool.
    calls: list[tuple[dict, str]] = []
    if images:
        calls.append(({
            "images": images[:20],
            "num_questions": min(count, PROXY_MAX_QUESTIONS_PER_CALL),
        }, "(generated from an uploaded picture)"))
    if has_text:
        remaining = max(0, count - (min(count, PROXY_MAX_QUESTIONS_PER_CALL) if images else 0))
        if remaining > 0:
            num_calls = min(PROXY_MAX_CALLS, max(1, -(-remaining // PROXY_MAX_QUESTIONS_PER_CALL)))
            segments = _split_text_for_proxy(text, num_calls)
            per_call = max(1, -(-remaining // len(segments)))
            for segment in segments:
                calls.append(({
                    "text": segment,
                    "num_questions": min(per_call, PROXY_MAX_QUESTIONS_PER_CALL),
                }, segment[:200]))

    if not calls:
        return [], "Nothing to send to the question service (no text or pictures)."

    results: list[tuple[Optional[list], Optional[str], str]] = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(_proxy_post, proxy_url, app_token, payload): label
                   for payload, label in calls}
        for future in concurrent.futures.as_completed(futures):
            label = futures[future]
            completed += 1
            if progress_callback:
                try:
                    progress_callback(completed, len(calls))
                except Exception:
                    pass  # progress reporting must never break generation
            questions, err = future.result()
            results.append((questions, err, label))

    all_questions: list[dict] = []
    errors: list[str] = []
    seen_questions: set[str] = set()
    for questions, err, label in results:
        if questions:
            for q in questions:
                if not isinstance(q, dict):
                    continue
                opts = q.get("options")
                idx = q.get("correctIndex")
                qtext = q.get("question")
                if not qtext or not isinstance(opts, list) or len(opts) != 4:
                    continue
                if not isinstance(idx, int) or not (0 <= idx < len(opts)):
                    continue
                key = qtext.strip().lower()
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                all_questions.append(_finalize_question(
                    question=qtext, options=opts[:4], correct_index=int(idx),
                    source_chunk=label,
                    explanation=q.get("explanation")
                ))
        elif err:
            errors.append(err)

    if not all_questions:
        return [], "; ".join(dict.fromkeys(errors)) if errors else "The question service returned no usable questions."
    return all_questions, None


def verify_and_explain_with_proxy(
    questions: list[dict], proxy_url: str = DEFAULT_PROXY_URL, app_token: str = DEFAULT_APP_TOKEN,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[Optional[list[dict]], Optional[str]]:
    """For questions that came from the file ITSELF (detect_existing_qa /
    fill_missing_pieces_offline) rather than being generated -- sends them
    to the proxy's "verify" mode, which double-checks each marked answer
    and writes an explanation, WITHOUT generating anything new. Used so a
    student gets a real explanation for their own reviewer questions
    instead of just a bare right/wrong.

    The question and option TEXT sent back by the model is deliberately
    ignored -- only correctIndex and explanation are taken from its
    response, keeping the app's own extracted text authoritative. This
    protects against a model paraphrasing/altering a question that was
    already correct as extracted, and means a validation failure (wrong
    length, wrong shape) can only affect explanations/answer-correction,
    never silently swap in AI-written question text.

    Returns (enriched_questions, error). On total failure (e.g. no
    internet), returns (None, error) -- the caller falls back to using
    `questions` exactly as given. On partial failure (some batches failed,
    matching this function's own batching -- see PROXY_MAX_QUESTIONS_PER_CALL),
    still returns a full-length list; any question whose batch failed is
    included unchanged (original correctIndex, no explanation) rather than
    being dropped.
    """
    if not proxy_url or not app_token:
        return None, "Online verification isn't configured (missing proxy URL/token)."
    if not questions:
        return None, "No questions to verify."

    import concurrent.futures

    # Only genuine 4-option multiple-choice items go through verification
    # -- anything else (e.g. a Q:/A: free-text pair detect_existing_qa
    # couldn't turn into options) isn't something this "verify" schema can
    # represent, so it's carried through unchanged rather than dropped or
    # sent to the model in a shape it can't use.
    mc_indices = [i for i, q in enumerate(questions)
                  if isinstance(q.get("options"), list) and len(q["options"]) == 4]
    if not mc_indices:
        return None, "No multiple-choice questions to verify."
    mc_questions = [questions[i] for i in mc_indices]

    def to_payload_item(q: dict) -> dict:
        return {"question": q["question"], "options": q["options"], "correctIndex": q.get("correctIndex")}

    batches = [mc_questions[i:i + PROXY_MAX_QUESTIONS_PER_CALL]
               for i in range(0, len(mc_questions), PROXY_MAX_QUESTIONS_PER_CALL)]

    results: list[tuple[int, Optional[list], Optional[str]]] = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as pool:
        futures = {
            pool.submit(_proxy_post, proxy_url, app_token,
                        {"mode": "verify", "questions": [to_payload_item(q) for q in batch]}): idx
            for idx, batch in enumerate(batches)
        }
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            completed += 1
            if progress_callback:
                try:
                    progress_callback(completed, len(batches))
                except Exception:
                    pass
            verified, err = future.result()
            results.append((idx, verified, err))

    results.sort(key=lambda r: r[0])
    verified_by_position: dict[int, dict] = {}
    any_success = False
    errors: list[str] = []
    for batch_idx, verified, err in results:
        batch = batches[batch_idx]
        batch_start = sum(len(b) for b in batches[:batch_idx])
        if verified and len(verified) == len(batch):
            any_success = True
            for offset, (original, v) in enumerate(zip(batch, verified)):
                q = dict(original)
                v_idx = v.get("correctIndex") if isinstance(v, dict) else None
                if isinstance(v_idx, int) and 0 <= v_idx < len(q.get("options", [])):
                    q["correctIndex"] = v_idx
                if isinstance(v, dict) and v.get("explanation"):
                    q["explanation"] = v["explanation"]
                verified_by_position[batch_start + offset] = q
        else:
            if err:
                errors.append(err)
            # This batch's verification failed -- keep those questions
            # unchanged rather than dropping them.
            for offset, original in enumerate(batch):
                verified_by_position[batch_start + offset] = dict(original)

    if not any_success:
        return None, "; ".join(dict.fromkeys(errors)) if errors else "Verification service unavailable."

    enriched = list(questions)  # non-MC items stay exactly as given, at their original positions
    for mc_pos, q_idx in enumerate(mc_indices):
        result_q = verified_by_position.get(mc_pos)
        if result_q is not None:
            result_q.pop("_qnum", None)
            result_q.pop("_correct_text", None)
            enriched[q_idx] = result_q
    return enriched, None


# ---------------------------------------------------------------------------
# 4. Direct Gemini call -- optional escape hatch for a technical user who'd
#    rather use their OWN key, bypassing the proxy entirely. Off by default.
# ---------------------------------------------------------------------------

GEMINI_MODEL = "gemini-flash-latest"  # a Google-maintained alias for their current recommended Flash model


def generate_questions_with_gemini(text: str, api_key: str) -> tuple[list[dict], Optional[str]]:
    """Calls the Gemini REST API directly with the CALLER'S OWN key. Returns
    (questions, error) -- on ANY failure (network error, bad response, zero
    usable items, ...) questions is [] and error is a short human-readable
    reason; never raises."""
    if not text or not text.strip():
        return [], "No text to generate questions from."
    if not api_key or not api_key.strip():
        return [], "Gemini API Key is missing. Add one via Settings first."

    num_questions = min(target_question_count(text), 50)  # single un-chunked call; higher risks a truncated/invalid JSON response
    prompt = f"""Act as a professional test creator and expert educator. Based on the following study text, research paper, or module, generate {num_questions} multiple-choice questions (MCQs) that test deep comprehension, key concepts, findings, and important details.

Return ONLY a valid JSON array containing objects with this exact structure, with no markdown formatting outside:
[
    {{
        "question": "The question text here?",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correctIndex": 0,
        "explanation": "Detailed explanation of why this answer is correct based on the text."
    }}
]

Text to analyze:
{text[:15000]}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    try:
        resp = requests.post(url, params={"key": api_key}, json=payload, timeout=45)
    except requests.RequestException as e:
        return [], f"Gemini request failed ({type(e).__name__}: {e})"
    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        if resp.status_code in (400, 401, 403) and ("API key" in detail or "API_KEY" in detail):
            return [], "That Gemini API key was rejected. Check it in Settings."
        return [], f"Gemini API Error: HTTP {resp.status_code} - {detail}"
    try:
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        questions_data = json.loads(raw_text)
    except Exception as e:
        return [], f"Gemini returned an unexpected response ({type(e).__name__}: {e})"

    formatted: list[dict] = []
    if isinstance(questions_data, list):
        for q in questions_data:
            if not isinstance(q, dict):
                continue
            opts, idx, qtext = q.get("options"), q.get("correctIndex"), q.get("question")
            if not qtext or not isinstance(opts, list) or len(opts) != 4:
                continue
            if not isinstance(idx, int) or not (0 <= idx < len(opts)):
                continue
            formatted.append(_finalize_question(
                question=qtext, options=opts[:4], correct_index=int(idx),
                source_chunk=text[:280], explanation=q.get("explanation"),
            ))

    if not formatted:
        return [], "Gemini returned empty or invalid question structures."
    return formatted, None


# ---------------------------------------------------------------------------
# 5. Fully offline fallback (no internet, no AI model, no key required)
# ---------------------------------------------------------------------------

def _split_into_sentences(text: str) -> list[str]:
    """Split on line breaks first (so headings/titles never bleed into the
    next sentence), then on sentence-ending punctuation within each line.
    Lines that are actually multiple-choice option labels or item numbers
    (see OPTION_LABEL_RE) are dropped entirely -- they're structural, not
    prose, and must never be mistaken for a fact or a definition."""
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if not line or OPTION_LABEL_RE.match(line):
            continue
        sentences.extend(s.strip() for s in SENTENCE_SPLIT_RE.split(line) if s.strip())
    return sentences


def _extract_definitions(chunk_text_: str) -> list[tuple[str, str]]:
    """Find 'Term is/are definition' style sentences."""
    found = []
    for s in _split_into_sentences(chunk_text_):
        if s.rstrip().endswith("?"):
            continue  # a question ("What is X?"), not a declarative definition -- skip it
        s_no_article = _LEADING_ARTICLE_RE.sub("", s)
        m = DEFINITION_RE.match(s_no_article)
        if m:
            term, definition = m.group(1).strip(), m.group(2).strip()
            if (term.split()[0].lower() not in GENERIC_STOPWORDS and len(term.split()) <= 6
                    and len(term) >= 3 and not definition.rstrip().endswith("?")):
                found.append((term.capitalize() if term.islower() else term, definition))
    return found


def _extract_key_facts(chunk_text_: str) -> list[str]:
    """Sentences containing a number or proper noun — used as fallback facts."""
    facts = [s for s in _split_into_sentences(chunk_text_)
             if len(s.split()) >= 8 and not s.rstrip().endswith("?")
             and (NUMBER_RE.search(s) or PROPER_NOUN_RE.search(s))]
    return facts


def _build_distractor_pool(full_text: str) -> dict[str, list[str]]:
    """Collect candidate distractor material from the whole document,
    grouped by 'kind' so distractors stay plausible (numbers vs numbers,
    names vs names, definitions vs definitions)."""
    pool = {"definition": [], "number": [], "proper_noun": []}
    for term, definition in _extract_definitions(full_text):
        pool["definition"].append(definition)
    for line in full_text.splitlines():
        line = line.strip()
        if not line or OPTION_LABEL_RE.match(line):
            continue  # skip item numbers ("139.") and option labels ("A.") -- not real data
        for m in NUMBER_RE.finditer(line):
            pool["number"].append(m.group(0))
        for m in PROPER_NOUN_RE.finditer(line):
            name = m.group(1)
            if name.split()[0].lower() not in GENERIC_STOPWORDS:
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
    """Fully offline, rule-based generator. Returns (questions, skipped_chunk_labels)."""
    pool = _build_distractor_pool(full_text)
    questions: list[dict] = []
    skipped: list[str] = []
    used_terms: set[str] = set()  # avoid asking "What is X?" more than once for the same X

    for chunk in chunks:
        definitions = [(t, d) for t, d in _extract_definitions(chunk.content)
                       if t.lower() not in used_terms]
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
            used_terms.add(term.lower())
            made_one = True
            break  # one solid question per chunk keeps pacing even

        if not made_one:
            facts = _extract_key_facts(chunk.content)
            fact_used = False
            for fact in facts:
                num_match = NUMBER_RE.search(fact)
                noun_match = None
                for candidate in PROPER_NOUN_RE.finditer(fact):
                    # Skip a match that's just a sentence-initial capitalized
                    # word like "Which"/"This" -- PROPER_NOUN_RE can't tell
                    # ordinary capitalization from an actual proper noun, so
                    # this filters it the same way the pool-building step does.
                    if candidate.group(1).split()[0].lower() not in GENERIC_STOPWORDS:
                        noun_match = candidate
                        break
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


# Backwards-compatible alias -- older Android code called this
# "generate_questions_offline"; keep working if anything still imports it.
generate_questions_offline = generate_questions

"""
question_generator.py
Handles AI Question Generation using Google Gemini API with offline fallback.
"""

from __future__ import annotations
import os
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

@dataclass
class Chunk:
    content: str
    label: str

def chunk_text(text: str, headings: list[tuple[str, int]] | None = None, target_words: int = 300) -> list[Chunk]:
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
            chunks[-1].content += "\n" + content

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
    """
    Gumagamit ng Google Gemini API para mag-generate ng multiple-choice questions 
    kasama ang tamang sagot at paliwanag mula sa in-upload na materyal.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        return [], "Google Generative AI package is not installed. Run: pip install google-generativeai"

    if not api_key:
        return [], "Gemini API Key is missing."

    try:
        genai.configure(api_key=api_key)
        # Paggamit ng pinakabagong ligtas at mabilis na flash model
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        Act as a professional test creator and expert educator. Based on the following study text/module, 
        generate multiple-choice questions (MCQs). Ensure questions test deep comprehension, key concepts, and important details.
        
        Return ONLY a valid JSON array containing objects with this exact structure, with no markdown formatting outside or inside if possible (or standard JSON format):
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
        
        # Linisin ang response kung sakaling may kasamang markdown code blocks
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

# Offline Fallback Generator (Sakaling walang internet connection)
def _build_distractor_pool(full_text: str) -> dict[str, list[str]]:
    pool = {"definition": [], "number": [], "proper_noun": []}
    for line in full_text.splitlines():
        for m in NUMBER_RE.finditer(line):
            pool["number"].append(m.group(0))
        for m in PROPER_NOUN_RE.finditer(line):
            name = m.group(1)
            if name.split()[0] not in GENERIC_STOPWORDS:
                pool["proper_noun"].append(name)
    for k in pool:
        pool[k] = list(dict.fromkeys(pool[k]))
    return pool

def _pick_distractors(correct: str, pool: dict[str, list[str]], count: int = 3) -> list[str]:
    candidates = [c for group in pool.values() for c in group if c != correct]
    random.shuffle(candidates)
    return candidates[:count] if len(candidates) >= count else ["Option A", "Option B", "Option C"][:count]

def generate_questions_offline(chunks: list[Chunk], full_text: str) -> tuple[list[dict], list[str]]:
    pool = _build_distractor_pool(full_text)
    questions: list[dict] = []
    skipped: list[str] = []

    for chunk in chunks:
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(chunk.content) if len(s.split()) >= 8]
        if sentences:
            fact = sentences[0]
            words = fact.split()
            target = words[len(words)//2]
            blanked = fact.replace(target, "_____", 1)
            distractors = _pick_distractors(target, pool, count=3)
            options = distractors + [target]
            random.shuffle(options)
            questions.append(_finalize_question(
                f"Complete the statement: \"{blanked}\"",
                options, options.index(target), chunk.content,
                explanation=f"This is derived directly from the offline module text: {fact}"
            ))
        else:
            skipped.append(chunk.label)

    return questions, skipped

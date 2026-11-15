"""The only place where the tutor uses the language model: one short hint.

The model answers 22% of these problems, so it can't be trusted to explain
them. It writes one sentence about the first step, and check() decides in code
whether the student ever sees it.

Speed: the board reads about 11 tokens per second and writes about 5. warm()
makes the server read the problem while the student is still reading it. With
cache_prompt, generate() then only reads the short instruction at the end.
Keep the problem first and the instruction last, or the cache is useless.
"""
import re
import time

from ..client import get, post
from ..config import CONFIG
from . import settings as S
from .textutil import has_number, numbers_in, option_value, strip_numbering, words

BASE = f"http://{S.LLM_HOST}:{CONFIG['LLM_PORT']}"
URL = BASE + "/v1/chat/completions"
SYSTEM = ("You are a math tutor for school students. You give one short hint about how to "
          "start a problem. You never solve it and you never state the answer.")
STATES_ANSWER = re.compile(r"\b(the answer is|answer:|la resposta (és|es)|resposta:|la respuesta es)\b", re.IGNORECASE)


def reachable(timeout=2):
    """Is the model server answering? From inside App Lab it usually isn't: see settings.py."""
    try:
        get(BASE + "/health", timeout=timeout)
        return True
    except (OSError, ValueError):
        return False


def _instruction():
    return (f"\n\nWrite one short sentence in {S.HINT_LANGUAGE} with a hint about the first step. "
            "Do not solve the problem. Do not write the answer.")


def _messages(problem_text, with_instruction):
    content = "Problem:\n" + strip_numbering(problem_text)
    if with_instruction:
        content += _instruction()
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def warm(problem_text, timeout=120):
    """Make the server read the problem now. Returns the tokens it had to read."""
    response = post(URL, {"messages": _messages(problem_text, False), "max_tokens": 1,
                          "temperature": 0, "seed": S.SEED, "cache_prompt": True}, timeout=timeout)
    return response.get("timings", {}).get("prompt_n", 0)


def generate(problem_text, timeout=120):
    """Return (hint, seconds, tokens read). The hint is one line, not yet checked."""
    start = time.perf_counter()
    response = post(URL, {"messages": _messages(problem_text, True), "max_tokens": S.HINT_MAX_TOKENS,
                          "temperature": 0, "seed": S.SEED, "cache_prompt": True}, timeout=timeout)
    text = response["choices"][0]["message"]["content"]
    return clean(text), time.perf_counter() - start, response.get("timings", {}).get("prompt_n", 0)


def clean(text):
    """First non-empty line, without quotes or a 'Hint:' label."""
    for line in (text or "").splitlines():
        line = line.strip().strip('"“”«»').strip()
        line = re.sub(r"^(hint|pista)\s*:\s*", "", line, flags=re.IGNORECASE)
        if line:
            return line
    return ""


def check(hint, problem_texts, options, label):
    """Return (passed, reason). A hint that fails is never shown.

    problem_texts: the problem in every language we have, to compare words.
    """
    if not hint:
        return False, "empty"
    if len(hint.split()) > S.HINT_MAX_WORDS:
        return False, "too_long"
    if STATES_ANSWER.search(hint):
        return False, "states_answer"
    if label and re.search(rf"(?<!\w){label}\)|\b(option|opció|opcion)\s+{label}\b", hint):
        return False, "leaks_letter"
    correct = option_value((options or {}).get(label, ""))
    data = [n for text in problem_texts for n in numbers_in(text)]
    if correct is not None and correct not in data and has_number(hint, correct):
        return False, "leaks_value"
    raw = ((options or {}).get(label) or "").strip().lower()
    if correct is None and len(raw) >= 4 and raw in hint.lower():
        return False, "leaks_value"
    known = set().union(*(words(text) for text in problem_texts)) if problem_texts else set()
    if known and not (words(hint) & known):
        return False, "off_topic"
    return True, "ok"

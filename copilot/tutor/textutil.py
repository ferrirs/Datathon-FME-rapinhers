"""Small text helpers: numbers, questions, words, and a stand-in embedding."""
import hashlib
import math
import re

NUMBER = re.compile(r"(?<![\w.,/])[-−]?\d+(?:[.,]\d+)?(?:\s?/\s?\d+)?(?![\w/])")
LEADING_NUMBER = re.compile(r"^\s*\d{1,2}\s*[.)]\s+")
OPTION_VALUE = re.compile(r"^\s*([-−]?\d+(?:[.,]\d+)?(?:\s?/\s?\d+)?)\s*(%|[^\d\s][^\d]{0,14})?\s*$")
SENTENCE_END = re.compile(r"(?<=[.?!])\s+")
WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def clean_text(text):
    """M3Kang texts keep the line breaks of the printed page: make it one flowing paragraph."""
    return re.sub(r"\s+", " ", text or "").strip()


def strip_numbering(text):
    """'13. For 3 days...' -> 'For 3 days...': the question number is not data."""
    return LEADING_NUMBER.sub("", text.strip(), count=1)


def to_float(token):
    token = token.replace("−", "-").replace(" ", "")
    try:
        if "/" in token:
            top, bottom = token.split("/")
            return float(top.replace(",", ".")) / float(bottom)
        return float(token.replace(",", "."))
    except (ValueError, ZeroDivisionError):
        return None


def numbers_in(text):
    """The numbers of a problem text, in order and without repeats."""
    found = []
    for token in NUMBER.findall(strip_numbering(text)):
        value = to_float(token)
        if value is not None and value not in found:
            found.append(value)
    return found


def option_value(raw):
    """'12 cm' -> 12.0, '1/2' -> 0.5, 'a triangle' -> None. One number, an optional unit."""
    match = OPTION_VALUE.match(raw or "")
    return to_float(match.group(1)) if match else None


def split_question(text):
    """Return (context, question): the question is the last sentence with a '?'."""
    sentences = [s.strip() for s in SENTENCE_END.split(strip_numbering(text)) if s.strip()]
    if not sentences:
        return "", ""
    asked = [i for i, s in enumerate(sentences) if "?" in s]
    index = asked[-1] if asked else len(sentences) - 1
    context = " ".join(sentences[:index] + sentences[index + 1:])
    return context, sentences[index]


def words(text):
    return {w.lower() for w in WORD.findall(text or "")}


def has_number(text, value):
    """Does the text contain this value as a number of its own? 12 is not in '120'."""
    return any(abs(v - value) < 1e-9 for v in numbers_in(text))


def utf8_console():
    """Print any character on a Windows console too, even without PYTHONUTF8=1."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def hash_embed(text, dim=384):
    """A bag-of-words vector for tests and for a laptop without the embedding server.

    It only knows shared words, not meaning. Never use it for the real bank.
    """
    vector = [0.0] * dim
    for word in re.findall(r"\w+", text.lower()):
        digest = hashlib.md5(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dim] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]

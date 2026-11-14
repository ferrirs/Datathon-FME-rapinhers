"""Correct the model's letter bias in predict.py.

The baseline answers D or A far more often than the true answers do (README,
step 11.3). calibrate_letters.py measures, on training problems, how much the
model likes each letter whatever the problem. Here we subtract that from the
log probabilities of a new problem, and answer the letter that is left on top.

    python3 calibrate_letters.py            # writes copilot/letter_bias.json

answer() is a drop-in for llm.answer_letter. Without a bias file it calls
answer_letter itself, so nothing changes until you calibrate. Still one
request, one token, temperature 0: the 60 seconds and the determinism hold.

Not run against the real server yet. First check what it returns:
    python3 calibrate_letters.py --limit 3 --show
If no letters come back, this llama.cpp build reports log probabilities in
another shape: adapt letter_logprobs(), which is the only place that reads them.
"""
import json
import os

from .config import CONFIG
from .client import post
from .llm import URL, answer_letter, build_messages

BIAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "letter_bias.json")
LETTERS = "ABCDE"
MISSING = 3.0  # a letter outside the top list is at least this much below the last one seen


def letter_logprobs(response):
    """{"A": -0.4, ...} from a chat completion asked with logprobs. Empty when absent."""
    try:
        top = response["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    except (KeyError, IndexError, TypeError):
        return {}
    found = {}
    for item in top:
        token = str(item.get("token", "")).strip()
        if len(token) == 1 and token in LETTERS and "logprob" in item:
            found[token] = max(found.get(token, float("-inf")), item["logprob"])
    return found


def ask(problem, examples=(), timeout=60, image_b64=None, url=URL):
    """Return (letter, {letter: logprob}, timings) for one problem."""
    response = post(url, {
        "messages": build_messages(problem, examples, image_b64),
        "grammar": "root ::= [A-E]",
        "max_tokens": 1,
        "temperature": 0,
        "seed": int(CONFIG["SEED"]),
        "cache_prompt": True,
        "logprobs": True,
        "top_logprobs": 10,
    }, timeout=timeout)
    letter = response["choices"][0]["message"]["content"].strip()
    return letter, letter_logprobs(response), response.get("timings", {})


def filled(logprobs):
    """Give the letters the server didn't list a value below the lowest one it did."""
    floor = min(logprobs.values()) - MISSING
    return {letter: logprobs.get(letter, floor) for letter in LETTERS}


def debiased(logprobs, bias):
    """The letter with the best log probability once the bias is taken away, or None."""
    if len(logprobs) < 2:
        return None
    scores = filled(logprobs)
    return max(LETTERS, key=lambda letter: (scores[letter] - bias.get(letter, 0.0), letter))


def load_bias(path=BIAS_PATH):
    try:
        with open(path) as f:
            bias = json.load(f)["bias"]
        return bias if set(bias) == set(LETTERS) else None
    except (OSError, ValueError, KeyError):
        return None


_BIAS = load_bias()


def answer(problem, examples=(), timeout=60, image_b64=None, url=URL):
    """Same contract as llm.answer_letter: (letter, timings)."""
    if _BIAS is None:
        return answer_letter(problem, examples, timeout=timeout, image_b64=image_b64, url=url)
    letter, logprobs, timings = ask(problem, examples, timeout=timeout, image_b64=image_b64, url=url)
    return debiased(logprobs, _BIAS) or letter, timings

"""Why did the student pick that wrong option?

Kangaroo distractors are often the result of a typical mistake. For each wrong
numeric option we try a few rules, with the numbers of the problem and the
correct value. The first rule that fits is stored in options.misconception.

The messages are questions. They never state the correct value, but some of
them narrow it down, so they are only shown after a wrong answer.
"""
from itertools import combinations

from .textutil import numbers_in, option_value

MESSAGES = {
    "DATA_COPY": "Aquest nombre surt a l'enunciat. És una dada o és el que et demanen?",
    "PARTIAL_STEP": "Has fet un pas del problema. Falta alguna cosa més abans de respondre?",
    "DOUBLE_HALF": "Pot ser que hagis comptat alguna cosa dues vegades, o només la meitat?",
    "OFF_BY_ONE": "Revisa els extrems: has comptat el primer i l'últim?",
    "MISSING_OP": "Has fet servir totes les dades de l'enunciat?",
    "MAGNITUDE": "Comprova les unitats i l'ordre de magnitud del resultat.",
}
GENERIC = "Torna a llegir què et demanen i comprova cada pas abans de triar."
RULES = tuple(MESSAGES)


def _same(a, b):
    return abs(a - b) < 1e-9


def _pair_results(data):
    results = []
    for a, b in combinations(data[:8], 2):
        results += [a + b, abs(a - b), a * b]
    return results


def rule_for(value, correct, data):
    """Return the code of the first rule that explains a wrong value, or None."""
    if value is None or correct is None or _same(value, correct):
        return None
    if any(_same(value, d) for d in data):
        return "DATA_COPY"
    pairs = _pair_results(data)
    if any(_same(value, r) for r in pairs) and not any(_same(correct, r) for r in pairs):
        return "PARTIAL_STEP"
    if correct != 0 and (_same(value, 2 * correct) or _same(value, correct / 2)):
        return "DOUBLE_HALF"
    if _same(abs(value - correct), 1) and float(value).is_integer() and float(correct).is_integer():
        return "OFF_BY_ONE"
    if any(d != 0 and (_same(value, correct + d) or _same(value, correct - d)) for d in data):
        return "MISSING_OP"
    if correct != 0 and value != 0:
        ratio = value / correct
        if any(_same(ratio, 10.0 ** k) for k in (-3, -2, -1, 1, 2, 3)):
            return "MAGNITUDE"
    return None


def annotate(text, options, label):
    """Rows for the options table: (letter, raw, value, is_correct, misconception)."""
    data = numbers_in(text)
    correct = option_value(options.get(label, ""))
    rows = []
    for letter in "ABCDE":
        if letter not in options:
            continue
        value = option_value(options[letter])
        code = None if letter == label else rule_for(value, correct, data)
        rows.append((letter, options[letter], value, int(letter == label), code))
    return rows


def message(code):
    return MESSAGES.get(code, GENERIC)

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


def consecutive(values):
    """True when the options are a run of consecutive integers, like 10, 11, 12, 13, 14.

    Kangaroo often uses such options. Then a wrong option one away from the right
    one says nothing about the student's mistake.
    """
    numbers = sorted(v for v in values if v is not None)
    if len(numbers) < 4 or not all(float(v).is_integer() for v in numbers):
        return False
    steps = [b - a for a, b in zip(numbers, numbers[1:])]
    return sum(1 for s in steps if s == 1) >= len(steps) - 1


def rule_for(value, correct, data, options_consecutive=False):
    """Return the code of the first rule that explains a wrong value, or None.

    Very small numbers (0, 1, 2) match too many things by chance, so they only
    count for the rules that compare with the correct value.
    """
    if value is None or correct is None or _same(value, correct):
        return None
    if abs(value) > 2 and any(_same(value, d) for d in data):
        return "DATA_COPY"
    pairs = _pair_results(data)
    if any(_same(value, r) for r in pairs) and not any(_same(correct, r) for r in pairs):
        return "PARTIAL_STEP"
    if abs(correct) >= 3 and (_same(value, 2 * correct) or _same(value, correct / 2)):
        return "DOUBLE_HALF"
    if not options_consecutive and _same(abs(value - correct), 1) \
            and float(value).is_integer() and float(correct).is_integer():
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
    run = consecutive([option_value(raw) for raw in options.values()])
    rows = []
    for letter in "ABCDE":
        if letter not in options:
            continue
        value = option_value(options[letter])
        code = None if letter == label else rule_for(value, correct, data, run)
        rows.append((letter, options[letter], value, int(letter == label), code))
    return rows


def message(code):
    return MESSAGES.get(code, GENERIC)

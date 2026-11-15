#!/usr/bin/env python3
"""Write made-up problems in the M3Kang format, to develop without M3Kang.

    python3 tutor_synthetic.py                       # data/synthetic.jsonl, 480 problems
    python3 tutor_build.py all --input data/synthetic.jsonl --db data/tutor_synth.db \
        --hand data/synthetic_labels.csv --classifier --fake-embed
    python3 tutor_server.py --db data/tutor_synth.db

Ten templates, one per topic, in English and Catalan, at 8 levels. The wrong
options come from typical mistakes, like Kangaroo distractors. The extra field
"_topic" holds the true topic, so the topic classifier can be scored.

These are not Kangaroo problems and they are far easier to classify than the
real ones. Use them to test the code, never to report a result.
"""
import argparse
import json
import random

TOPICS = ["arithmetic", "numbers", "fractions", "algebra", "patterns",
          "plane_geometry", "solid_geometry", "counting", "logic", "measure"]
NAMES = ["Anna", "Pau", "Laia", "Marc", "Júlia", "Nil", "Ona", "Jan"]


def arithmetic(rng, size):
    a, b, c = rng.randint(3, 4 + size), rng.randint(4, 6 + 2 * size), rng.randint(2, 5 + size)
    name = rng.choice(NAMES)
    eng = (f"{name} has {a} bags with {b} apples in each bag and eats {c} apples. "
           f"How many apples are left altogether?")
    cat = (f"{name} té {a} bosses amb {b} pomes a cada bossa i es menja {c} pomes. "
           f"Quantes pomes li queden en total?")
    return eng, cat, a * b - c, [a * b, a * b + c, a + b - c, b]


def numbers(rng, size):
    m, n = rng.randint(3, 6 + size), rng.randint(40, 60 + 40 * size)
    eng = f"How many multiples of {m} are there among the whole numbers from 1 to {n}?"
    cat = f"Quants múltiples de {m} hi ha entre els nombres enters de l'1 al {n}?"
    return eng, cat, n // m, [n // m + 1, n // m - 1, n - m, m]


def fractions(rng, size):
    p, n = rng.choice([10, 20, 25, 40, 50, 60, 75]), rng.choice([20, 40, 60, 80, 120, 200][:3 + size // 2])
    eng = f"{p} percent of the {n} students of a school play football. How many students do not play football?"
    cat = f"El {p} per cent dels {n} alumnes d'una escola juguen a futbol. Quants alumnes no juguen a futbol?"
    return eng, cat, n * (100 - p) // 100, [n * p // 100, n - p, p, n]


def algebra(rng, size):
    sister, diff = rng.randint(4, 8 + 2 * size), rng.randint(2, 4 + size)
    total = 2 * sister + diff
    name = rng.choice(NAMES)
    eng = (f"{name} is {diff} years older than his sister. Together they are {total} years old. "
           f"How old is the sister?")
    cat = (f"En {name} té {diff} anys més que la seva germana. Entre tots dos sumen {total} anys. "
           f"Quants anys té la germana?")
    return eng, cat, sister, [sister + diff, total - diff, total // 2, diff]


def patterns(rng, size):
    a, d, n = rng.randint(2, 9), rng.randint(2, 3 + size), rng.randint(8, 10 + 6 * size)
    eng = (f"A sequence starts with {a} and each term is {d} more than the previous one. "
           f"What is the term in position {n} of the sequence?")
    cat = (f"Una successió comença amb {a} i cada terme és {d} unitats més gran que l'anterior. "
           f"Quin és el terme que ocupa la posició {n} de la successió?")
    return eng, cat, a + (n - 1) * d, [a + n * d, n * d, a + (n - 1) * d + 1, a + (n - 2) * d]


def plane_geometry(rng, size):
    width, length = rng.randint(2, 4 + size), rng.randint(6, 8 + 2 * size)
    perimeter = 2 * (width + length)
    eng = f"A rectangle has a perimeter of {perimeter} cm and a length of {length} cm. What is its area in cm²?"
    cat = f"Un rectangle té un perímetre de {perimeter} cm i una llargada de {length} cm. Quina és la seva àrea en cm²?"
    return eng, cat, width * length, [perimeter * length, length * length, width, 2 * width * length]


def solid_geometry(rng, size):
    n = rng.randint(3, 4 + size // 2)
    eng = (f"A cube with an edge of {n} cm is built from small cubes with an edge of 1 cm. Then all its faces "
           f"are painted red. How many small cubes have no painted faces?")
    cat = (f"Un cub de {n} cm d'aresta està fet amb cubs petits d'1 cm d'aresta. Després es pinten de vermell "
           f"totes les seves cares. Quants cubs petits no tenen cap cara pintada?")
    inner = (n - 2) ** 3
    return eng, cat, inner, [n ** 3, n ** 3 - inner, (n - 1) ** 3, 6 * n]


def counting(rng, size):
    a, b = rng.randint(3, 4 + size), rng.randint(3, 5 + size)
    name = rng.choice(NAMES)
    eng = (f"{name} has {a} T-shirts and {b} pairs of trousers. In how many different ways can {name} "
           f"choose one T-shirt and one pair of trousers?")
    cat = (f"{name} té {a} samarretes i {b} pantalons. De quantes maneres diferents pot triar "
           f"una samarreta i uns pantalons?")
    return eng, cat, a * b, [a + b, 2 * a * b, a * b - 1, a * a]


def logic(rng, size):
    n = rng.randint(5, 7 + 2 * size)
    eng = (f"{n} children stand in a line. The first child tells the truth. Each of the others says: "
           f"\"The child in front of me is lying.\" How many of the children are lying?")
    cat = (f"{n} nens fan una fila. El primer diu la veritat. Cadascun dels altres diu: "
           f"«El nen que tinc davant menteix.» Quants nens menteixen?")
    return eng, cat, n // 2, [n - n // 2, n - 1, 1, n]


def measure(rng, size):
    speed, minutes = rng.choice([60, 90, 120]), rng.choice([20, 30, 40, 80, 100, 140][:3 + size // 2])
    eng = f"A train travels at a constant speed of {speed} km/h. How many kilometres does it travel in {minutes} minutes?"
    cat = f"Un tren circula a una velocitat constant de {speed} km/h. Quants quilòmetres recorre en {minutes} minuts?"
    return eng, cat, speed * minutes // 60, [speed * minutes, speed + minutes, speed - minutes, speed * minutes // 30]


TEMPLATES = dict(zip(TOPICS, [arithmetic, numbers, fractions, algebra, patterns,
                              plane_geometry, solid_geometry, counting, logic, measure]))


def make_options(rng, correct, wrong):
    """Five different, non-negative values: the right one, then mistakes, then near misses."""
    values = [correct]
    for value in wrong:
        if value not in values and value >= 0:
            values.append(value)
    step = 2
    while len(values) < 5:
        for candidate in (correct + step, correct - step):
            if candidate >= 0 and candidate not in values and len(values) < 5:
                values.append(candidate)
        step += 1
    values = values[:5]
    rng.shuffle(values)
    label = "ABCDE"[values.index(correct)]
    return {letter: str(value) for letter, value in zip("ABCDE", values)}, label


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="data/synthetic.jsonl")
    p.add_argument("--papers", type=int, default=2, help="papers per level, 30 questions each")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)
    count = 0
    labels_path = args.out.rsplit(".", 1)[0] + "_labels.csv"
    with open(args.out, "w", encoding="utf-8") as out, open(labels_path, "w", encoding="utf-8") as labels:
        labels.write("id,topic\n")
        for level in range(8):
            for paper in range(args.papers):
                year = 2090 + paper
                for qnum in range(1, 31):
                    topic = TOPICS[(qnum + paper + level) % len(TOPICS)]
                    band = (qnum - 1) // 10
                    eng, cat, correct, wrong = TEMPLATES[topic](rng, level // 2 + band)
                    options, label = make_options(rng, correct, wrong)
                    for language, text in (("eng", eng), ("cat", cat)):
                        out.write(json.dumps({
                            "id": f"lvl-{level}_{year}_{qnum}", "language": language, "level": level,
                            "year": year, "text_only": True, "text": f"{qnum}. {text}",
                            "options": options, "label": label, "_topic": topic}, ensure_ascii=False) + "\n")
                    if count % 3 == 0:
                        labels.write(f"lvl-{level}_{year}_{qnum},{topic}\n")
                    count += 1
    print(f"Wrote {count} made-up problems, in English and Catalan, to {args.out}")
    print(f"Wrote the true topic of one problem in three to {labels_path}, as if labelled by hand")


if __name__ == "__main__":
    main()

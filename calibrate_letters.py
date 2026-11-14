#!/usr/bin/env python3
"""Measure the model's letter bias on training problems, for copilot/debias.py.

    python3 calibrate_letters.py --limit 3 --show   # look at what the server returns first
    python3 calibrate_letters.py                    # 100 problems, about 15 minutes on the board

For each letter it stores: the mean log probability the model gives it, minus
the log of how often that letter is the true answer in the training set. A new
problem's log probabilities minus this bias are fair to the five letters.

It only reads data/train.jsonl, so the validation score stays honest. The file
it writes, copilot/letter_bias.json, holds five numbers and no M3Kang data.

Then measure, like any other change:
    python3 eval.py --limit 50 --name debias
The accuracy printed here is on the same problems the bias was fitted on, so
it flatters the method. Only eval.py on validation counts.
"""
import argparse
import json
import math
import random
import sys
from collections import Counter

from copilot import debias
from copilot.config import CONFIG


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="data/train.jsonl")
    p.add_argument("--languages", default="eng")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--show", action="store_true", help="print each problem's log probabilities, and write nothing")
    p.add_argument("--out", default=debias.BIAS_PATH)
    args = p.parse_args()

    languages = set(args.languages.split(","))
    with open(args.input, encoding="utf-8") as f:
        problems = [json.loads(line) for line in f if line.strip()]
    problems = [x for x in problems if x["language"] in languages and x.get("options")]
    if not problems:
        sys.exit(f"No problems with options in {args.input} for {sorted(languages)}")
    true_counts = Counter(x["label"] for x in problems)
    random.Random(int(CONFIG["SEED"])).shuffle(problems)
    sample = problems[:args.limit]

    sums, used, rows = Counter(), 0, []
    for n, problem in enumerate(sample, 1):
        letter, logprobs, _timings = debias.ask(problem)
        if args.show:
            print(f"{problem['id']}: answered {letter}, true {problem['label']}, logprobs {logprobs}")
        if len(logprobs) >= 2:
            scores = debias.filled(logprobs)
            for key, value in scores.items():
                sums[key] += value
            rows.append((scores, letter, problem["label"]))
            used += 1
        if not args.show:
            print(f"\r{n}/{len(sample)}", end="", flush=True)
    print()
    if not used:
        sys.exit("The server returned no letter log probabilities. See the note at the top of copilot/debias.py.")
    if args.show:
        return

    total = sum(true_counts.values())
    bias = {letter: sums[letter] / used - math.log(max(true_counts[letter], 1) / total) for letter in debias.LETTERS}
    before = sum(letter == label for _scores, letter, label in rows)
    after = sum(debias.debiased(scores, bias) == label for scores, _letter, label in rows)
    answers_before = Counter(letter for _scores, letter, _label in rows)
    answers_after = Counter(debias.debiased(scores, bias) for scores, _letter, _label in rows)
    with open(args.out, "w") as f:
        json.dump({"bias": bias, "problems": used, "languages": sorted(languages)}, f, indent=2)
    print(f"Bias per letter: " + ", ".join(f"{k} {v:+.2f}" for k, v in bias.items()))
    print(f"Answers before: {dict(sorted(answers_before.items()))}")
    print(f"Answers after:  {dict(sorted(answers_after.items()))}")
    print(f"On these {used} training problems: {before} right before, {after} right after (fitted on them: optimistic)")
    print(f"Wrote {args.out}. Now run: python3 eval.py --limit 50 --name debias")


if __name__ == "__main__":
    main()

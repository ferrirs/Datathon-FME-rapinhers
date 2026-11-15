#!/usr/bin/env python3
"""Model hints: try them, write them ahead of time, and count how many are safe.

    python3 tutor_hints.py --try 10        # print 10 hints with their verdict; stores nothing
    python3 tutor_hints.py                 # write and store a hint for every problem that can have one
    python3 tutor_hints.py --ids demo.txt  # only these problems (one id per line): the ones of your demo
    python3 tutor_hints.py --report        # how many stored hints passed the checks, and why the rest failed
    python3 tutor_hints.py --review 20     # print 20 usable hints with their problems, to judge by hand

Why ahead of time: the board writes about 5 tokens per second, and the App Lab
app can't reach the model server at all. So the hints are written once, here,
and the tutor only reads them from the bank.

Only problems shown as text get a hint (no figure, five options we trust):
about 350 of the quiz. On the board a hint takes about 18 seconds (13 to read
the problem, 5 to write one sentence), so all of them take under two hours. On
a laptop with the same model it takes a few minutes. Stop it whenever you
like: it continues where it stopped.

Every hint goes through llmhint.check before it is stored as usable. A hint
that fails is stored too, marked as failed, so it is never written again and
never shown.

Start with --try, and read the hints. To compare languages:
    TUTOR_HINT_LANGUAGE=English python3 tutor_hints.py --try 10
"""
import argparse
import json
import random
import sys
import time
from collections import Counter

from copilot.tutor import llmhint
from copilot.tutor import settings as S
from copilot.tutor.db import connect, is_current
from copilot.tutor.textutil import utf8_console


def candidates(db, args):
    """Problems that can get a model hint: shown as text (no figure, five options we trust)."""
    where, values = "t.display = 'text' AND t.language = ? AND p.level <= ?", [S.LANGUAGE, S.MAX_LEVEL]
    if args.ids:
        with open(args.ids, encoding="utf-8") as f:
            wanted = [line.strip() for line in f if line.strip()]
        where += f" AND p.id IN ({','.join('?' * len(wanted))})"
        values += wanted
    elif args.level is not None:
        where += " AND p.level = ?"
        values.append(args.level)
    rows = db.execute(f"SELECT p.id FROM problems p JOIN problem_texts t ON t.id = p.id "
                      f"WHERE {where} ORDER BY p.level, p.band, p.id", values).fetchall()
    return [row["id"] for row in rows]


def texts_of(db, problem_id):
    rows = {r["language"]: r for r in db.execute("SELECT * FROM problem_texts WHERE id = ?", (problem_id,))}
    shown = rows.get(S.LANGUAGE) or next(iter(rows.values()))
    source = rows.get(S.VECTOR_LANGUAGE) or shown
    return shown, source


def one(db, problem_id):
    shown, source = texts_of(db, problem_id)
    label = db.execute("SELECT label FROM problems WHERE id = ?", (problem_id,)).fetchone()["label"]
    text, seconds, read = llmhint.generate(source["text"])
    passed, reason = llmhint.check(text, [shown["text"], source["text"]], json.loads(shown["options"]), label)
    return shown, text, passed, reason, seconds, read


def report(db):
    rows = db.execute("SELECT passed, reason, seconds FROM hints WHERE kind = 'first_step'").fetchall()
    if not rows:
        print("No hints stored yet.")
        return
    passed = sum(r["passed"] for r in rows)
    print(f"{len(rows)} hints stored, {passed} usable ({passed / len(rows):.0%})")
    for reason, n in Counter(r["reason"] for r in rows).most_common():
        print(f"  {reason:14} {n}")
    times = sorted(r["seconds"] for r in rows)
    print(f"Seconds per hint: median {times[len(times) // 2]:.1f}, worst {times[-1]:.1f}")
    print("A hint that fails a check is never shown. Now judge 20 usable ones by hand: "
          "python3 tutor_hints.py --review 20")


def review(db, n):
    rows = db.execute(
        """SELECT h.id, h.text, t.text AS problem FROM hints h
           JOIN problem_texts t ON t.id = h.id AND t.language = h.language
           WHERE h.passed = 1 AND h.kind = 'first_step' ORDER BY h.id""").fetchall()
    if not rows:
        print("No usable hints stored yet.")
        return
    for row in random.Random(S.SEED).sample(rows, min(n, len(rows))):
        print(f"\n[{row['id']}] {row['problem']}\n  hint: {row['text']}")
    print("\nFor each one, write down: is it about the problem? does it help? does it say the answer?")


def main():
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--try", dest="tries", type=int, default=0, help="print this many hints and store nothing")
    p.add_argument("--level", type=int, default=None, help="only this level")
    p.add_argument("--limit", type=int, default=0, help="stop after this many new hints (0 = all)")
    p.add_argument("--ids", default="", help="file with one problem id per line")
    p.add_argument("--report", action="store_true")
    p.add_argument("--review", type=int, default=0, help="print this many usable hints to judge by hand")
    args = p.parse_args()

    db = connect(args.db)
    if not is_current(db):
        sys.exit(f"{args.db} isn't a bank of this version. Build it first: python3 tutor_build.py all")
    if args.report:
        return report(db)
    if args.review:
        return review(db, args.review)
    ids = candidates(db, args)
    if not ids:
        sys.exit("No problem can get a hint. Build the bank first: python3 tutor_build.py all")
    if not llmhint.reachable():
        sys.exit(f"The language model doesn't answer at {llmhint.BASE}. Start it (README, step 5 or 7).")

    if args.tries:
        step = max(1, len(ids) // args.tries)  # spread over the levels
        for problem_id in ids[::step][:args.tries]:
            shown, text, passed, reason, seconds, read = one(db, problem_id)
            print(f"\n[{problem_id}] {shown['text'][:200]}")
            print(f"  hint: {text}")
            print(f"  {'USABLE' if passed else 'REJECTED: ' + reason}, {seconds:.1f} s, {read} tokens read")
        return

    done = {r["id"] for r in db.execute("SELECT id FROM hints WHERE kind = 'first_step' AND language = ?",
                                        (S.LANGUAGE,))}
    todo = [i for i in ids if i not in done]
    stored = len(ids) - len(todo)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} hints to write ({stored} already stored). "
          f"About {len(todo) * 18 / 60:.0f} minutes on the board, far less on a laptop.")
    start, usable = time.perf_counter(), 0
    for n, problem_id in enumerate(todo, 1):
        _shown, text, passed, reason, seconds, _read = one(db, problem_id)
        db.execute("INSERT OR REPLACE INTO hints VALUES (?, ?, 'first_step', ?, ?, ?, ?)",
                   (problem_id, S.LANGUAGE, text, int(passed), reason, seconds))
        db.commit()
        usable += passed
        if sys.stdout.isatty():
            print(f"\r{n}/{len(todo)}, {usable} usable, {time.perf_counter() - start:.0f} s", end="", flush=True)
    print()
    report(db)


if __name__ == "__main__":
    main()

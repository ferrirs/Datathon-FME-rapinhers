#!/usr/bin/env python3
"""Model hints: try them, generate them ahead of time, and count how many are safe.

    python3 tutor_hints.py --try 10              # print 10 hints with their verdict; stores nothing
    python3 tutor_hints.py --level 2 --limit 40  # generate and store hints for 40 problems of level 2
    python3 tutor_hints.py --ids demo_ids.txt    # one problem id per line: the problems of your demo
    python3 tutor_hints.py --report              # how many stored hints passed, and why the rest failed

Run it on the board, with the language model service up. A hint takes about
18 seconds there (13 to read the problem, 5 to write one sentence), so 40
problems take about 12 minutes. Generate the problems of your demo first.

Every hint goes through llmhint.check before it is stored as usable. A hint
that fails is stored too, marked as failed, so it is never generated again and
never shown. During a session, hints made on the spot are stored the same way.

Start with --try. Read the hints. If they aren't good enough in Catalan, set
TUTOR_HINT_LANGUAGE=English in config.env, or run the server with --no-model.
"""
import argparse
import json
import sys
import time
from collections import Counter

from copilot.tutor import llmhint
from copilot.tutor import settings as S
from copilot.tutor.db import connect


def candidates(db, args):
    if args.ids:
        with open(args.ids) as f:
            wanted = [line.strip() for line in f if line.strip()]
        marks = ",".join("?" * len(wanted))
        rows = db.execute(f"SELECT id FROM problems WHERE id IN ({marks})", wanted).fetchall()
    else:
        where, values = "t.servable = 1 AND t.language = ?", [S.LANGUAGE]
        if args.level is not None:
            where += " AND p.level = ?"
            values.append(args.level)
        rows = db.execute(f"SELECT p.id FROM problems p JOIN problem_texts t ON t.id = p.id "
                          f"WHERE {where} ORDER BY p.band, p.id", values).fetchall()
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
    print("A hint that fails a check is never shown. Read 20 of the usable ones by hand, "
          "and report how many really help.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--try", dest="tries", type=int, default=0, help="print this many hints and store nothing")
    p.add_argument("--level", type=int, default=None)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--ids", default="", help="file with one problem id per line")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    db = connect(args.db)
    if args.report:
        return report(db)
    ids = candidates(db, args)
    if not ids:
        sys.exit("No problems match. Build the bank first: python3 tutor_build.py all")

    if args.tries:
        for problem_id in ids[:args.tries]:
            shown, text, passed, reason, seconds, read = one(db, problem_id)
            print(f"\n[{problem_id}] {shown['text'][:160]}")
            print(f"  hint: {text}")
            print(f"  {'USABLE' if passed else 'REJECTED: ' + reason}, {seconds:.1f} s, {read} tokens read")
        return

    done = {r["id"] for r in db.execute("SELECT id FROM hints WHERE kind = 'first_step' AND language = ?",
                                        (S.LANGUAGE,))}
    todo = [i for i in ids if i not in done][:args.limit]
    print(f"{len(todo)} hints to generate, about {len(todo) * 18 / 60:.0f} minutes on the board")
    start, usable = time.perf_counter(), 0
    for n, problem_id in enumerate(todo, 1):
        _shown, text, passed, reason, seconds, _read = one(db, problem_id)
        db.execute("INSERT OR REPLACE INTO hints VALUES (?, ?, 'first_step', ?, ?, ?, ?)",
                   (problem_id, S.LANGUAGE, text, int(passed), reason, seconds))
        db.commit()  # stop it whenever you like: it continues where it stopped
        usable += passed
        print(f"\r{n}/{len(todo)}, {usable} usable, {time.perf_counter() - start:.0f} s", end="", flush=True)
    print()
    report(db)


if __name__ == "__main__":
    main()

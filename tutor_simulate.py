#!/usr/bin/env python3
"""Simulated students: does the adaptive engine do what we say it does?

    python3 tutor_simulate.py                         # data/tutor.db, 150 problems per student
    python3 tutor_simulate.py --db data/tutor_synth.db --problems 200

Each simulated student has a true ability per topic that the tutor can't see.
They answer through the same code as the web page, on a copy of the bank, so
the real students in the database are never touched. We then compare what the
tutor believes with the truth:

- How far is the estimated ability from the true one, and after how many problems?
- How many problems fall in the zone where the student succeeds 60% to 85% of the time?
- Which topics does the tutor call mastered, and is it right?
- Does a mastered topic come up less often? Does a forgotten one come back?

The students answer with the same difficulty model the tutor uses, so this
checks the engine, not whether M3Kang levels predict difficulty for real pupils.
No model and no board needed. Every attempt is written to results/tutor-sim.csv.
"""
import argparse
import csv
import os
import random
import shutil
import sys
import tempfile
from collections import Counter

from copilot.tutor import engine
from copilot.tutor import settings as S
from copilot.tutor.service import Tutor, TutorError

LEVEL = 2
ZONE = (0.60, 0.85)

# offsets are true ability minus the reference difficulty of the student's grade
STUDENTS = [
    {"name": "even", "about": "at grade level in every topic", "default": 0},
    {"name": "strong", "about": "well above grade level", "default": 250},
    {"name": "weak", "about": "below grade level", "default": -150},
    {"name": "uneven", "about": "strong in half the topics, weak in the rest", "default": 0, "split": 200},
    {"name": "hints", "about": "below grade level, asks for hints whenever a problem looks hard", "default": -150, "hints": True},
    {"name": "forgets", "about": "strong, then forgets one topic after 60 problems", "default": 250, "forget_at": 60},
]


def true_ability(spec, topic, topics, n_done):
    offset = spec["default"]
    if "split" in spec:
        offset = spec["split"] if topics.index(topic) % 2 == 0 else -spec["split"]
    if "forget_at" in spec and topic == topics[0] and n_done >= spec["forget_at"]:
        offset = -300
    return engine.reference_b(LEVEL) + offset


def simulate(tutor, spec, problems, rng, writer):
    topics = tutor.available
    student = tutor.start(spec["name"], LEVEL)["student_id"]
    served, in_zone, by_state = 0, 0, Counter()
    demoted_after = None
    for n in range(problems):
        try:
            step = tutor.next(student)
        except TutorError:
            break  # the bank ran out of unseen problems
        topic = step["topic"]["key"]
        row = tutor.db.execute("SELECT b, label FROM problems WHERE id = ?", (step["problem"]["id"],)).fetchone()
        state = tutor.db.execute("SELECT state FROM student_topic WHERE student_id = ? AND topic = ?",
                                 (student, topic)).fetchone()["state"]
        truth = true_ability(spec, topic, topics, n) if topic in topics else engine.reference_b(LEVEL)
        p = engine.p_correct(truth, row["b"])
        if spec.get("hints") and p < 0.7:
            # Leans on hints when the problem looks hard, and then usually gets there
            for _ in range(3 if p < 0.5 else 1):
                tutor.hint(step["attempt_id"])
            p = max(p, 0.8)
        wrong = [x for x in "ABCDE" if x != row["label"]]
        if rng.random() < p:
            result = tutor.answer(step["attempt_id"], row["label"])
        else:
            first = rng.choice(wrong)
            tutor.answer(step["attempt_id"], first)
            second_ok = rng.random() < 0.25 + 0.5 * (p - S.GUESS)
            second = row["label"] if second_ok else rng.choice([x for x in wrong if x != first])
            result = tutor.answer(step["attempt_id"], second)
        served += 1
        in_zone += ZONE[0] <= p <= ZONE[1]
        by_state[state] += 1
        if "forget_at" in spec and topic == topics[0] and n >= spec["forget_at"] and demoted_after is None \
                and result["topic"]["state"] != "mastered":
            demoted_after = n - spec["forget_at"] + 1
        writer.writerow([spec["name"], n + 1, step["problem"]["id"], topic, state, round(row["b"]),
                         round(truth), f"{p:.3f}", int(result["correct_first"]), int(result["correct"]),
                         result["score"], result["topic"]["state"]])

    profile = tutor.profile(student)
    errors, declared, truly, false_mastery = [], 0, 0, 0
    for t in profile["topics"]:
        truth = true_ability(spec, t["topic"], topics, served)
        errors.append(abs(t["theta"] - truth))
        really = engine.p_correct(truth, engine.reference_b(LEVEL)) >= S.MASTERY_P
        declared += t["state"] == "mastered"
        truly += really
        false_mastery += t["state"] == "mastered" and not really
    return {"name": spec["name"], "about": spec["about"], "served": served,
            "zone": in_zone / served if served else 0, "error": sum(errors) / len(errors),
            "declared": declared, "truly": truly, "false": false_mastery, "topics": len(profile["topics"]),
            "by_state": by_state, "demoted_after": demoted_after}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--problems", type=int, default=150, help="problems per simulated student")
    p.add_argument("--seed", type=int, default=S.SEED)
    p.add_argument("--out", default="results/tutor-sim.csv")
    args = p.parse_args()
    if not os.path.exists(args.db):
        sys.exit(f"{args.db} doesn't exist. Build it first: python3 tutor_build.py all")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, open(args.out, "w", newline="") as out:
        copy = os.path.join(tmp, "sim.db")
        shutil.copy(args.db, copy)
        tutor = Tutor(copy, live_hints=False)
        for table in ("students", "student_topic", "attempts", "hint_events"):
            tutor.db.execute(f"DELETE FROM {table}")
        tutor.db.commit()
        writer = csv.writer(out)
        writer.writerow(["student", "n", "problem", "topic", "state_before", "b", "true_theta", "p_true",
                         "correct_first", "correct", "score", "state_after"])
        rng = random.Random(args.seed)
        results = [simulate(tutor, spec, args.problems, rng, writer) for spec in STUDENTS]
        tutor.db.close()

    print(f"{len(results)} simulated students, level {LEVEL}, up to {args.problems} problems each\n")
    print(f"{'student':9} {'done':>5} {'in zone':>8} {'ability error':>14} {'mastered':>9} {'truly':>6} {'wrong':>6}")
    for r in results:
        print(f"{r['name']:9} {r['served']:>5} {r['zone']:>8.0%} {r['error']:>14.0f} "
              f"{r['declared']:>6}/{r['topics']:<2} {r['truly']:>6} {r['false']:>6}")
    print("\n  in zone: problems where the student's true chance of success was 60% to 85%")
    print("  ability error: mean distance between estimated and true ability, in Elo points, at the end")
    print("  wrong: topics called mastered that the student doesn't really master")
    print("\nShare of problems by the state of their topic when served:")
    for r in results:
        total = sum(r["by_state"].values()) or 1
        shares = ", ".join(f"{state} {r['by_state'][state] / total:.0%}" for state in engine.STATES)
        print(f"  {r['name']:9} {shares}")
    for r in results:
        if r["name"] == "forgets":
            after = r["demoted_after"]
            print("\nThe forgotten topic went back to practice "
                  + (f"{after} problems after it was forgotten." if after else "never: check the review calendar."))
    print(f"\nEvery attempt is in {args.out}")


if __name__ == "__main__":
    main()

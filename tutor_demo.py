#!/usr/bin/env python3
"""A student with a history, for the demo.

    python3 tutor_demo.py                          # "Demo", 1r d'ESO, 80 problems done
    python3 tutor_demo.py --name Laia --level 3 --problems 60
    python3 tutor_demo.py --forget Laia            # delete a student and their history
    python3 tutor_demo.py --list                   # who is in the bank

In three minutes of pitch nobody can master a topic. This script lets a made-up
student practise beforehand: strong in the first topics, weaker in the rest. On
stage, type the same name on the page: the map already shows mastered topics,
a review that is due, and the hint "a problem you already solved" has problems
to point at.

Run it on data/tutor.db before board/install_app.sh, which copies the bank into
the app and keeps the students that are already there. Say in the pitch that
this history is simulated.
"""
import argparse
import random
import sys

from copilot.tutor import engine
from copilot.tutor import settings as S
from copilot.tutor.service import Tutor, TutorError
from copilot.tutor.textutil import utf8_console


def forget(tutor, name):
    row = tutor.db.execute("SELECT student_id FROM students WHERE name = ?", (name,)).fetchone()
    if row is None:
        sys.exit(f"There is no student called {name}.")
    student = row["student_id"]
    tutor.db.execute("DELETE FROM hint_events WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE student_id = ?)",
                     (student,))
    for table in ("attempts", "student_topic", "students"):
        tutor.db.execute(f"DELETE FROM {table} WHERE student_id = ?", (student,))
    tutor.db.commit()
    print(f"{name} and their history are gone.")


def practise(tutor, name, level, problems, seed):
    if tutor.db.execute("SELECT 1 FROM students WHERE name = ?", (name,)).fetchone():
        sys.exit(f"{name} already exists. Choose another name, or: python3 tutor_demo.py --forget {name}")
    started = tutor.start(name, level)
    student, topics = started["student_id"], [t["topic"] for t in started["topics"]]
    rng = random.Random(seed)
    for _ in range(problems):
        try:
            step = tutor.next(student)
        except TutorError:
            break
        row = tutor.db.execute("SELECT b, label FROM problems WHERE id = ?", (step["problem"]["id"],)).fetchone()
        # Well above the grade in the first third of the topics, a little below in the rest
        strong = topics.index(step["topic"]["key"]) < max(1, len(topics) // 3)
        ability = engine.reference_b(level) + (350 if strong else -60)
        wrong = [x for x in "ABCDE" if x != row["label"]]
        if rng.random() < engine.p_correct(ability, row["b"]):
            tutor.answer(step["attempt_id"], row["label"])
        else:
            first = rng.choice(wrong)
            tutor.answer(step["attempt_id"], first)
            tutor.answer(step["attempt_id"], rng.choice([x for x in wrong if x != first] + [row["label"]]))
    profile = tutor.profile(student)
    print(f"{name}: {profile['done']} problems done, {profile['correct_first']} right at the first try")
    for topic in profile["topics"]:
        review = f", review in {topic['review_in']}" if topic["review_in"] is not None else ""
        print(f"  {topic['name'][:38]:38} {topic['state']}{review}")
    print(f"\nOn the page, type the name {name}. Say in the pitch that this history is simulated.")


def main():
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--name", default="Demo")
    p.add_argument("--level", type=int, default=2, help="0 = 5è de primària ... 5 = 4t d'ESO")
    p.add_argument("--problems", type=int, default=80)
    p.add_argument("--seed", type=int, default=S.SEED)
    p.add_argument("--forget", default="", metavar="NAME", help="delete this student")
    p.add_argument("--list", action="store_true", help="list the students")
    args = p.parse_args()

    try:
        tutor = Tutor(args.db, live_hints=False)
    except TutorError as error:
        sys.exit(str(error))
    if args.list:
        for row in tutor.db.execute("SELECT name, level, n_done FROM students ORDER BY name"):
            print(f"{row['name']}: level {row['level']}, {row['n_done']} problems done")
    elif args.forget:
        forget(tutor, args.forget)
    else:
        practise(tutor, args.name, args.level, args.problems, args.seed)


if __name__ == "__main__":
    main()

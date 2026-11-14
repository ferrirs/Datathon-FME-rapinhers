#!/usr/bin/env python3
"""Build the tutor's problem bank, data/tutor.db, from the M3Kang files.

    python3 tutor_build.py all                  # every step below, in order
    python3 tutor_build.py bank                 # problems, texts, difficulty
    python3 tutor_build.py vectors              # embeddings of the English text
    python3 tutor_build.py neighbors            # the 20 most similar problems of each one
    python3 tutor_build.py topics               # a topic for each problem
    python3 tutor_build.py options              # numeric options and typical mistakes
    python3 tutor_build.py stats                # what the bank holds

    python3 tutor_build.py clusters --k 12      # look at the data before fixing the topic list
    python3 tutor_build.py sample --n 100       # data/hand_labels.csv, to label by hand
    python3 tutor_build.py topics --hand data/hand_labels.csv   # use and score those labels

Run it on the board, with the embedding service up (step 7 of the README).
--fake-embed replaces the embedding server with a bag of words: for tests and
for a laptop without the server, never for the real bank.

Students and their history are kept when you rebuild the content.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import time
from array import array
from collections import Counter, defaultdict

from copilot.tutor import engine, topics as topic_tools
from copilot.tutor import settings as S
from copilot.tutor.db import connect
from copilot.tutor.diagnose import RULES, annotate
from copilot.tutor.textutil import hash_embed, strip_numbering

ID_PATTERN = re.compile(r"^lvl-(\d+)_(\d{4})_(\d+)$")
NEIGHBOURS = 20


def embedder(fake):
    if fake:
        return lambda texts: [hash_embed(t) for t in texts]
    from copilot.embed import embed
    return embed


def read_problems(paths):
    problems = []
    for path in paths:
        if not os.path.exists(path):
            print(f"  (no {path}, skipped)")
            continue
        with open(path, encoding="utf-8") as f:
            problems += [json.loads(line) for line in f if line.strip()]
    return problems


def load_vectors(db):
    vectors = {}
    for pid, blob in db.execute("SELECT id, vec FROM vectors"):
        vec = array("f")
        vec.frombytes(blob)
        vectors[pid] = list(vec)
    return vectors


def english_texts(db):
    """One text per problem for the embeddings: English when we have it."""
    texts = {}
    for pid, language, text in db.execute("SELECT id, language, text FROM problem_texts ORDER BY id"):
        if language == S.VECTOR_LANGUAGE or pid not in texts:
            texts[pid] = strip_numbering(text)
    return texts


# --- Steps -------------------------------------------------------------------

def build_bank(db, args):
    problems = read_problems(args.input)
    if not problems:
        sys.exit("No problems found. Run laptop/prepare_m3kang.py and copy data/*.jsonl to the board.")
    parsed = {}
    for p in problems:
        match = ID_PATTERN.match(p["id"])
        parsed[p["id"]] = int(match.group(3)) if match else None
    # The last question number of each paper tells us where its three parts end
    qmax = defaultdict(int)
    for p in problems:
        if parsed[p["id"]]:
            key = (p.get("level"), p.get("year"))
            qmax[key] = max(qmax[key], parsed[p["id"]])

    db.execute("DELETE FROM problem_texts")
    seen = set()
    for p in problems:
        pid, options = p["id"], p.get("options") or {}
        qnum = parsed[pid]
        level = int(p.get("level") or 0)
        band = engine.band_of(qnum, qmax[(p.get("level"), p.get("year"))])
        text_only = p.get("text_only")
        text_only = bool(options) if text_only is None else bool(text_only)
        if pid not in seen:
            seen.add(pid)
            db.execute(
                """INSERT INTO problems (id, level, year, qnum, band, text_only, label, b)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET level = excluded.level, year = excluded.year,
                       qnum = excluded.qnum, band = excluded.band, text_only = excluded.text_only,
                       label = excluded.label, b = excluded.b""",
                (pid, level, p.get("year"), qnum, band, int(text_only), p["label"], engine.initial_b(level, band)))
        image = f"{pid}_{p['language']}.png"
        has_image = os.path.isfile(os.path.join(args.images, image))
        # A student can answer when they see five options: read by OCR, or in the picture
        servable = has_image or (bool(options) and text_only)
        db.execute("INSERT OR REPLACE INTO problem_texts VALUES (?, ?, ?, ?, ?, ?)",
                   (pid, p["language"], p["text"], json.dumps(options, ensure_ascii=False),
                    image if has_image else None, int(servable)))
    db.execute("DELETE FROM problems WHERE id NOT IN (SELECT id FROM problem_texts)")
    db.commit()
    by_language = Counter(p["language"] for p in problems)
    print(f"Bank: {len(seen)} problems, texts by language: {dict(by_language)}")


def build_vectors(db, args):
    embed = embedder(args.fake_embed)
    texts = english_texts(db)
    done = {pid for (pid,) in db.execute("SELECT id FROM vectors")}
    todo = [pid for pid in sorted(texts) if pid not in done]
    start = time.perf_counter()
    for i in range(0, len(todo), 16):
        chunk = todo[i:i + 16]
        vectors = embed([texts[pid] for pid in chunk])
        db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                       [(pid, array("f", vec).tobytes()) for pid, vec in zip(chunk, vectors)])
        db.commit()  # commit each batch: stop it and run it again, it continues
        print(f"\r  {i + len(chunk)}/{len(todo)} problems embedded", end="", flush=True)
    print(f"\nVectors: {len(todo)} new, {len(done)} already there, {time.perf_counter() - start:.0f} s")


def build_neighbors(db, args):
    vectors = load_vectors(db)
    ids = sorted(vectors)
    start = time.perf_counter()
    db.execute("DELETE FROM neighbors")
    try:  # numpy is on the board inside App Lab, and usually on a laptop
        import numpy as np
        matrix = np.array([vectors[i] for i in ids], dtype=np.float32)
        sims = matrix @ matrix.T
        np.fill_diagonal(sims, -2.0)
        for row, pid in enumerate(ids):
            best = np.argsort(-sims[row])[:NEIGHBOURS]
            db.executemany("INSERT INTO neighbors VALUES (?, ?, ?, ?)",
                           [(pid, rank, ids[j], float(sims[row, j])) for rank, j in enumerate(best)])
    except ImportError:
        for n, pid in enumerate(ids):
            vec = vectors[pid]
            scored = sorted(((topic_tools.dot(vec, vectors[other]), other) for other in ids if other != pid),
                            reverse=True)[:NEIGHBOURS]
            db.executemany("INSERT INTO neighbors VALUES (?, ?, ?, ?)",
                           [(pid, rank, other, sim) for rank, (sim, other) in enumerate(scored)])
            if n % 50 == 0:
                print(f"\r  {n}/{len(ids)}", end="", flush=True)
        print()
    db.commit()
    print(f"Neighbours: {NEIGHBOURS} for each of {len(ids)} problems, {time.perf_counter() - start:.0f} s")


def read_hand_labels(path, known):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    labels = {r["id"]: r["topic"].strip() for r in rows if r.get("topic", "").strip()}
    unknown = sorted({t for t in labels.values() if t not in known})
    if unknown:
        sys.exit(f"Unknown topics in {path}: {unknown}. Use the keys of content/topics.json.")
    return labels


def build_topics(db, args):
    topics = topic_tools.load_topics()
    embed = embedder(args.fake_embed)
    prototypes = {t["key"]: embed(t["prototypes"]) for t in topics}
    vectors, texts = load_vectors(db), english_texts(db)
    hand = {pid: t for pid, t in read_hand_labels(args.hand, {t["key"] for t in topics}).items() if pid in vectors}
    seeds = [(topic, vectors[pid]) for pid, topic in hand.items()]

    if hand:
        labelled = [(pid, texts[pid], vectors[pid], topic) for pid, topic in hand.items()]
        hits, confusion = topic_tools.leave_one_out(labelled, topics, prototypes)
        print(f"Leave-one-out on the {len(hand)} hand labels: {hits}/{len(hand)} = {hits / len(hand):.0%}")
        for (truth, predicted), n in confusion.most_common(8):
            print(f"  {truth} taken for {predicted}: {n}")

    for pid in sorted(vectors):
        if pid in hand:
            topic, margin, source = hand[pid], 1.0, "hand"
        else:
            topic, margin = topic_tools.classify(texts[pid], vectors[pid], topics, prototypes, seeds)
            source = "auto"
        db.execute("UPDATE problems SET topic = ?, topic_margin = ?, topic_source = ? WHERE id = ?",
                   (topic, margin, source, pid))
    db.commit()
    sure = db.execute("SELECT COUNT(*) FROM problems WHERE topic_margin >= ? OR topic_source = 'hand'",
                      (S.MIN_TOPIC_MARGIN,)).fetchone()[0]
    print(f"Topics: {len(vectors)} problems labelled, {sure} above the margin {S.MIN_TOPIC_MARGIN}")


def build_options(db, _args):
    db.execute("DELETE FROM options")
    rows = db.execute(
        """SELECT p.id, p.label, t.text, t.options FROM problems p JOIN problem_texts t ON t.id = p.id
           WHERE t.options != '{}' ORDER BY p.id, (t.language = ?) DESC""", (S.VECTOR_LANGUAGE,)).fetchall()
    done = set()
    for row in rows:
        if row["id"] in done:  # options are the same in every language: read them once
            continue
        done.add(row["id"])
        db.executemany("INSERT INTO options VALUES (?, ?, ?, ?, ?, ?)",
                       [(row["id"],) + r for r in annotate(row["text"], json.loads(row["options"]), row["label"])])
    db.commit()
    print(f"Options: {len(done)} problems with options read")


def stats(db, _args):
    total = db.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
    print(f"\n{total} problems in the bank")
    print("\nTexts by language (servable = a student can answer it):")
    for language, n, servable in db.execute(
            "SELECT language, COUNT(*), SUM(servable) FROM problem_texts GROUP BY language"):
        print(f"  {language}: {n} texts, {servable} servable")

    print(f"\nProblems by topic and level (margin >= {S.MIN_TOPIC_MARGIN} or labelled by hand):")
    table = defaultdict(Counter)
    for topic, level, n in db.execute(
            "SELECT topic, level, COUNT(*) FROM problems WHERE topic_margin >= ? OR topic_source = 'hand' "
            "GROUP BY topic, level", (S.MIN_TOPIC_MARGIN,)):
        table[topic or "-"][level] = n
    levels = sorted({level for row in table.values() for level in row})
    print("  " + "topic".ljust(16) + "".join(f"L{level}".rjust(5) for level in levels) + "  total")
    for topic in sorted(table):
        print("  " + topic.ljust(16) + "".join(str(table[topic][level]).rjust(5) for level in levels)
              + str(sum(table[topic].values())).rjust(7))
    unsure = db.execute("SELECT COUNT(*) FROM problems WHERE topic_margin < ? AND topic_source != 'hand'",
                        (S.MIN_TOPIC_MARGIN,)).fetchone()[0]
    print(f"  not sure enough of the topic: {unsure}")

    print("\nWrong options explained by a rule, by level (numeric options only):")
    for level, wrong, numeric, explained in db.execute(
            """SELECT p.level, COUNT(*), SUM(o.value IS NOT NULL), SUM(o.misconception IS NOT NULL)
               FROM options o JOIN problems p ON p.id = o.id WHERE o.is_correct = 0 GROUP BY p.level"""):
        share = explained / numeric if numeric else 0
        print(f"  level {level}: {explained}/{numeric} numeric wrong options = {share:.0%} ({wrong} wrong options in all)")
    print("\nBy rule:")
    counts = dict(db.execute("SELECT misconception, COUNT(*) FROM options WHERE misconception IS NOT NULL GROUP BY 1"))
    for rule in RULES:
        print(f"  {rule.ljust(13)} {counts.get(rule, 0)}")
    hints = db.execute("SELECT COUNT(*), COALESCE(SUM(passed), 0) FROM hints").fetchone()
    print(f"\nModel hints stored: {hints[0]}, of which {hints[1]} passed the checks")


def clusters(db, args):
    vectors, texts = load_vectors(db), english_texts(db)
    ids = sorted(vectors)
    assigned = topic_tools.kmeans([vectors[i] for i in ids], args.k, seed=S.SEED)
    rng = random.Random(S.SEED)
    for cluster in range(args.k):
        members = [pid for pid, c in zip(ids, assigned) if c == cluster]
        print(f"\n=== Cluster {cluster}: {len(members)} problems ===")
        for pid in rng.sample(members, min(6, len(members))):
            print(f"  [{pid}] {texts[pid][:150]}")


def sample(db, args):
    """A CSV to label by hand: the same number of problems from each level."""
    topics = topic_tools.load_topics()
    by_level = defaultdict(list)
    for pid, level, guess in db.execute("SELECT id, level, topic FROM problems ORDER BY id"):
        by_level[level].append((pid, guess))
    rng = random.Random(S.SEED)
    texts = english_texts(db)
    per_level = max(1, args.n // max(1, len(by_level)))
    path = args.hand or "data/hand_labels.csv"
    if os.path.exists(path):
        sys.exit(f"{path} already exists. Delete it first, or pass --hand another.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "topic", "suggested", "text"])
        for level in sorted(by_level):
            for pid, guess in rng.sample(by_level[level], min(per_level, len(by_level[level]))):
                writer.writerow([pid, "", guess or "", texts.get(pid, "")])
    print(f"Wrote {path}. Fill in the 'topic' column with one of:")
    print("  " + ", ".join(t["key"] for t in topics))
    print("It holds M3Kang text: don't commit it (data/ is already in .gitignore).")


STEPS = {"bank": build_bank, "vectors": build_vectors, "neighbors": build_neighbors,
         "topics": build_topics, "options": build_options, "stats": stats,
         "clusters": clusters, "sample": sample}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=list(STEPS) + ["all"])
    p.add_argument("--input", nargs="+", default=["data/train.jsonl", "data/val.jsonl"])
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--images", default=S.IMAGES_DIR)
    p.add_argument("--hand", default="", help="CSV with id,topic labelled by hand")
    p.add_argument("--k", type=int, default=12, help="clusters to look at")
    p.add_argument("--n", type=int, default=100, help="problems to label by hand")
    p.add_argument("--fake-embed", action="store_true", help="bag of words instead of the embedding server")
    args = p.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    db = connect(args.db)
    if args.step == "all":
        if not args.hand and os.path.exists("data/hand_labels.csv"):
            args.hand = "data/hand_labels.csv"
        for name in ("bank", "vectors", "neighbors", "topics", "options", "stats"):
            print(f"\n--- {name} ---")
            STEPS[name](db, args)
    else:
        STEPS[args.step](db, args)
    db.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the tutor's problem bank, data/tutor.db, from the M3Kang files.

    python3 tutor_build.py all                  # every step below, in order
    python3 tutor_build.py bank                 # problems, texts, difficulty, how each one is shown
    python3 tutor_build.py vectors              # embeddings of the English text
    python3 tutor_build.py neighbors            # the 20 most similar problems of each one
    python3 tutor_build.py topics               # a topic for each problem
    python3 tutor_build.py options              # numeric options and typical mistakes
    python3 tutor_build.py stats                # what the bank holds: the numbers for the pitch

It reads data/train.jsonl, data/val.jsonl, data/images/ and, if it's there,
data/temes.json: the team's topics. Run it where the embedding server runs:
on the board (steps 6 and 7 of the README), or on a laptop with the same model.
It takes a few minutes, and it continues where it stopped.

Without data/temes.json it classifies the problems itself:

    python3 tutor_build.py clusters --k 12      # look at the data before fixing the topic list
    python3 tutor_build.py sample --n 100       # data/hand_labels.csv, to label by hand
    python3 tutor_build.py topics --hand data/hand_labels.csv   # use and score those labels

--fake-embed replaces the embedding server with a bag of words: for tests and
for a laptop without the server, never for the real bank.

Students and their history are kept when you rebuild the bank.
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
from copilot.tutor.db import connect, is_current, reset_content
from copilot.tutor.diagnose import RULES, annotate
from copilot.tutor.textutil import clean_text, hash_embed, strip_numbering, utf8_console

ID_PATTERN = re.compile(r"^lvl-(\d+)_(\d{4})_(\d+)$")
NUMERIC = re.compile(r"^[-−]?\d+(?:[.,]\d+)?(?:/\d+)?$")
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
    for pid, blob in db.execute("SELECT v.id, v.vec FROM vectors v JOIN problems p ON p.id = v.id"):
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


def meta(db, key, value=None):
    if value is None:
        row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    return value


# --- Reading the OCR with care --------------------------------------------------

def normal(value):
    return value.replace(",", ".").replace(" ", "").strip()


def options_agree(a, b):
    """Do two OCR readings of the same options say the same? Compared letter by letter."""
    return set(a) == set(b) and all(normal(a[k]) == normal(b[k]) for k in a)


def trusted_options(options, other):
    """Can the page show these five options as text?

    OCR reads the options from the image, and gets about 3% of the numeric ones wrong
    ("#8", "1 17"). Each problem was read twice, once per language, and numbers don't
    change with the language: when both readings are numbers, they must be the same.
    """
    if len(options) != 5 or any(not v.strip() or "#" in v for v in options.values()):
        return False
    numeric = all(NUMERIC.match(normal(v)) for v in options.values())
    other_numeric = len(other) == 5 and all(NUMERIC.match(normal(v)) for v in other.values())
    if numeric or other_numeric:
        return options_agree(options, other)
    return True


# --- Steps -------------------------------------------------------------------

def build_bank(db, args):
    problems = read_problems(args.input)
    if not problems:
        sys.exit("No problems found. Run laptop/prepare_m3kang.py and copy data/*.jsonl here.")
    reset_content(db)
    qnum = {}
    for p in problems:
        match = ID_PATTERN.match(p["id"])
        qnum[p["id"]] = int(match.group(3)) if match else None
    # The last question number seen at each level tells us how long its papers are (24 or 30):
    # per level, not per paper, because M3Kang doesn't hold every question of every paper
    qmax = defaultdict(int)
    for p in problems:
        if qnum[p["id"]]:
            qmax[p.get("level")] = max(qmax[p.get("level")], qnum[p["id"]])

    by_id = defaultdict(dict)
    for p in problems:
        by_id[p["id"]][p["language"]] = p
    shown = Counter()
    for pid, versions in by_id.items():
        first = next(iter(versions.values()))
        level = int(first.get("level") or 0)
        band = engine.band_of(qnum[pid], qmax[first.get("level")])
        text_only = first.get("text_only")
        text_only = bool(first.get("options")) if text_only is None else bool(text_only)
        db.execute(
            "INSERT INTO problems (id, level, year, qnum, band, text_only, label, b) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, level, first.get("year"), qnum[pid], band, int(text_only), first["label"],
             engine.initial_b(level, band)))
        for language, p in versions.items():
            options = p.get("options") or {}
            others = [v.get("options") or {} for lang, v in versions.items() if lang != language]
            image = f"{pid}_{language}.png"
            has_image = os.path.isfile(os.path.join(args.images, image))
            # Typeset the problem only when it needs no figure and its options can be trusted.
            # Otherwise the student reads the scanned problem, which is always right.
            checked = trusted_options(options, others[0]) if others else len(options) == 5
            if text_only and checked:
                display = "text"
            elif has_image:
                display = "image"
            else:
                display = "text" if text_only and len(options) == 5 else ""
            shown[(language, display)] += 1
            db.execute("INSERT INTO problem_texts VALUES (?, ?, ?, ?, ?, ?)",
                       (pid, language, clean_text(p["text"]), json.dumps(options, ensure_ascii=False),
                        image if has_image else None, display))
    db.execute("DELETE FROM vectors WHERE id NOT IN (SELECT id FROM problems)")
    db.commit()
    print(f"Bank: {len(by_id)} problems")
    for language in sorted({language for language, _display in shown}):
        print(f"  {language}: {shown[(language, 'text')]} shown as text, {shown[(language, 'image')]} as the "
              f"scanned problem, {shown[(language, '')]} can't be shown")
    if not any(display == "image" for _language, display in shown):
        print(f"  No images found in {args.images}: only problems without a figure can be shown.")


def build_vectors(db, args):
    kind = "fake" if args.fake_embed else "real"
    if meta(db, "vectors") not in (None, kind):
        db.execute("DELETE FROM vectors")  # never mix bag-of-words vectors with real ones
    meta(db, "vectors", kind)
    db.commit()
    embed = embedder(args.fake_embed)
    texts = english_texts(db)
    done = {pid for (pid,) in db.execute("SELECT id FROM vectors")}
    todo = [pid for pid in sorted(texts) if pid not in done]
    start = time.perf_counter()
    for i in range(0, len(todo), 16):
        chunk = todo[i:i + 16]
        try:
            vectors = embed([texts[pid] for pid in chunk])
        except OSError as error:
            sys.exit(f"\nThe embedding server doesn't answer ({error}). Start it (README, step 6 or 7), "
                     "then run this again: it continues where it stopped.")
        db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                       [(pid, array("f", vec).tobytes()) for pid, vec in zip(chunk, vectors)])
        db.commit()
        if sys.stdout.isatty():
            print(f"\r  {i + len(chunk)}/{len(todo)} problems embedded", end="", flush=True)
    if todo and sys.stdout.isatty():
        print()
    print(f"Vectors: {len(todo)} new, {len(done)} already there, {time.perf_counter() - start:.0f} s"
          + (" (bag of words, not the real model)" if args.fake_embed else ""))


def build_neighbors(db, _args):
    vectors = load_vectors(db)
    ids = sorted(vectors)
    start = time.perf_counter()
    db.execute("DELETE FROM neighbors")
    try:  # with numpy it takes a second; without it, plain Python does the same in a few minutes
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
            if n % 50 == 0 and sys.stdout.isatty():
                print(f"\r  {n}/{len(ids)}", end="", flush=True)
        if sys.stdout.isatty():
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


def clean_topics(db):
    """Fix what k-means got wrong, with the neighbours of each problem.

    k-means groups by vocabulary, so a problem about fence posts can land in "speed and
    routes". We look at the topics of its 10 nearest neighbours: with 6 or more in one
    other topic, the problem moves there. With fewer than 3 in its own topic, we aren't
    sure, and the problem doesn't count towards mastery (it can still be a similar problem).
    """
    topic = dict(db.execute("SELECT id, topic FROM problems"))
    moved = unsure = 0
    for pid, own in topic.items():
        near = [topic[n] for (n,) in db.execute(
            "SELECT neighbor_id FROM neighbors WHERE id = ? ORDER BY rank LIMIT ?", (pid, S.TOPIC_NEIGHBOURS))]
        if not near or own is None:
            continue
        best, votes = Counter(near).most_common(1)[0]
        source = "team"
        if best != own and best is not None and votes >= S.TOPIC_MOVE:
            own, source, moved = best, "neighbours", moved + 1
        agree = near.count(own) / len(near)
        unsure += agree < S.MIN_TOPIC_AGREE
        db.execute("UPDATE problems SET topic = ?, topic_margin = ?, topic_source = ?, topic_ok = ? WHERE id = ?",
                   (own, agree, source, int(agree >= S.MIN_TOPIC_AGREE), pid))
    return moved, unsure


def team_topics(db, temes, path):
    """Use the team's topics: data/temes.json, from the k-means groups they named by hand."""
    db.execute("DELETE FROM topics")
    for position, topic in enumerate(temes["topics"]):
        db.execute("INSERT INTO topics VALUES (?, ?, ?, ?, ?, ?)",
                   (str(topic["topic_id"]), position, topic["name_ca"], "", int(bool(topic.get("needs_image"))),
                    json.dumps(topic.get("methods_ca", []), ensure_ascii=False)))
    by_id = {pid: str(t) for pid, t in temes["topic_by_id"].items()}
    for (pid,) in db.execute("SELECT id FROM problems").fetchall():
        db.execute("UPDATE problems SET topic = ?, topic_margin = 1, topic_source = 'team', topic_ok = ? WHERE id = ?",
                   (by_id.get(pid), int(pid in by_id), pid))
    print(f"Topics: {len(temes['topics'])} team topics from {path}")
    if meta(db, "vectors") == "real":
        moved, unsure = clean_topics(db)
        print(f"  checked against the 10 nearest neighbours of each problem: {moved} moved to the topic "
              f"of their neighbours, {unsure} left out of mastery because we aren't sure of their topic")
    else:
        print("  not checked against the neighbours: the vectors aren't from the real model")
    db.commit()
    for topic in temes["topics"]:
        key = str(topic["topic_id"])
        total, sure = db.execute("SELECT COUNT(*), COALESCE(SUM(topic_ok), 0) FROM problems WHERE topic = ?",
                                 (key,)).fetchone()
        print(f"  {key:>2} {topic['name_ca']}: {total} problems, {sure} sure")


def build_topics(db, args):
    if os.path.exists(args.temes) and not args.classifier:
        with open(args.temes, encoding="utf-8") as f:
            temes = json.load(f)
        known = sum(1 for (pid,) in db.execute("SELECT id FROM problems") if pid in temes["topic_by_id"])
        total = db.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
        if known * 2 >= total:
            return team_topics(db, temes, args.temes)
        print(f"  {args.temes} covers {known} of the {total} problems of this bank: classifying instead")
    db.execute("DELETE FROM topics")  # the built-in topics of content/topics.json are used
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

    sure = 0
    for pid in sorted(vectors):
        if pid in hand:
            topic, margin, source = hand[pid], 1.0, "hand"
        else:
            topic, margin = topic_tools.classify(texts[pid], vectors[pid], topics, prototypes, seeds)
            source = "auto"
        ok = source == "hand" or margin >= S.MIN_TOPIC_MARGIN
        sure += ok
        db.execute("UPDATE problems SET topic = ?, topic_margin = ?, topic_source = ?, topic_ok = ? WHERE id = ?",
                   (topic, margin, source, int(ok), pid))
    db.commit()
    print(f"Topics: {len(vectors)} problems classified, {sure} sure (margin {S.MIN_TOPIC_MARGIN} or labelled by hand)")


def build_options(db, _args):
    """Numeric options and the typical mistake behind each wrong one.

    Only for problems whose options OCR read the same way in every language: a diagnosis
    built on a misread number would tell the student something false.
    """
    db.execute("DELETE FROM options")
    by_id = defaultdict(list)
    for row in db.execute(
            """SELECT p.id, p.label, t.text, t.options FROM problems p JOIN problem_texts t ON t.id = p.id
               ORDER BY p.id, (t.language = ?) DESC""", (S.VECTOR_LANGUAGE,)):
        by_id[row["id"]].append(row)
    done = skipped = 0
    for pid, rows in by_id.items():
        readings = [json.loads(r["options"]) for r in rows]
        first = readings[0]
        if len(first) != 5:
            continue
        if any(len(other) == 5 and not options_agree(first, other) for other in readings[1:]):
            numeric = all(NUMERIC.match(normal(v)) for v in first.values())
            if numeric:
                skipped += 1
                continue
        db.executemany("INSERT INTO options VALUES (?, ?, ?, ?, ?, ?)",
                       [(pid,) + r for r in annotate(rows[0]["text"], first, rows[0]["label"])])
        done += 1
    db.commit()
    print(f"Options: {done} problems with five options read, {skipped} left out because two readings disagree")


def stats(db, _args):
    lang, cap = S.LANGUAGE, S.MAX_LEVEL
    total = db.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
    count = lambda where, *values: db.execute(  # noqa: E731
        f"SELECT COUNT(*) FROM problems p JOIN problem_texts t ON t.id = p.id AND t.language = ? "
        f"WHERE p.level <= ? AND {where}", (lang, cap) + values).fetchone()[0]
    quiz = count("t.display != ''")
    print(f"\n{total} problems in the bank. The quiz: level <= {cap}, shown in '{lang}'")
    print(f"  {quiz} problems a student can answer")
    print(f"  {count("t.display = 'text'")} shown as text, with the full hint ladder")
    print(f"  {count("t.display = 'image'")} shown as the scanned problem (a figure, or options that OCR "
          f"couldn't read for sure)")
    print(f"  {count("t.display != '' AND p.topic_ok = 1")} sure enough of their topic to count towards mastery")

    names = dict(db.execute("SELECT key, name FROM topics"))
    print("\nProblems of the quiz by topic and level:")
    table = defaultdict(Counter)
    for topic, level, n in db.execute(
            """SELECT p.topic, p.level, COUNT(*) FROM problems p
               JOIN problem_texts t ON t.id = p.id AND t.language = ? AND t.display != ''
               WHERE p.level <= ? AND p.topic_ok = 1 GROUP BY p.topic, p.level""", (lang, cap)):
        table[topic or "-"][level] = n
    levels = list(range(cap + 1))
    print("  " + "topic".ljust(40) + "".join(f"L{level}".rjust(5) for level in levels) + "  total")
    for topic in sorted(table, key=lambda t: (len(t), t)):
        label = f"{topic} {names.get(topic, '')}".strip()[:39]
        print("  " + label.ljust(40) + "".join(str(table[topic][level]).rjust(5) for level in levels)
              + str(sum(table[topic].values())).rjust(7))

    numeric, explained = db.execute(
        """SELECT COALESCE(SUM(o.value IS NOT NULL), 0), COALESCE(SUM(o.misconception IS NOT NULL), 0)
           FROM options o JOIN problems p ON p.id = o.id WHERE o.is_correct = 0 AND p.level <= ?""", (cap,)).fetchone()
    print(f"\nWrong numeric options explained by a typical mistake: {explained}/{numeric} = "
          f"{explained / max(numeric, 1):.0%}")
    counts = dict(db.execute(
        "SELECT o.misconception, COUNT(*) FROM options o JOIN problems p ON p.id = o.id "
        "WHERE o.misconception IS NOT NULL AND p.level <= ? GROUP BY 1", (cap,)))
    print("  " + ", ".join(f"{rule} {counts.get(rule, 0)}" for rule in RULES))

    # The easier problem the tutor would pick: the same topic first, then the most similar.
    # Outer columns stay out of the subquery's ORDER BY: SQLite 3.46 on the board rejects them there.
    easier = """FROM neighbors n JOIN problems q ON q.id = n.neighbor_id
                JOIN problem_texts u ON u.id = q.id AND u.language = :lang AND u.display != ''
                WHERE n.id = p.id AND q.b < p.b AND q.level <= :cap AND n.sim >= :min AND n.sim < :dup"""
    rows = db.execute(
        f"""SELECT p.topic,
                   CASE WHEN EXISTS (SELECT 1 {easier} AND q.topic = p.topic) THEN p.topic
                        ELSE (SELECT q.topic {easier} ORDER BY n.sim DESC LIMIT 1) END AS easier_topic
            FROM problems p JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.display != ''
            WHERE p.level <= :cap""", {"min": S.MIN_SIM, "dup": S.DUP_SIM, "cap": cap, "lang": lang}).fetchall()
    found = [r for r in rows if r["easier_topic"] is not None]
    twins = db.execute("SELECT COUNT(DISTINCT id) FROM neighbors WHERE sim >= ?", (S.DUP_SIM,)).fetchone()[0]
    print(f"\nProblems with a similar, easier problem (similarity {S.MIN_SIM} to {S.DUP_SIM}): "
          f"{len(found)}/{len(rows)} = {len(found) / max(len(rows), 1):.0%}, "
          f"of the same topic {sum(r['easier_topic'] == r['topic'] for r in found) / max(len(found), 1):.0%}")
    print(f"Problems with a twin, the same question at another level (similarity >= {S.DUP_SIM}): {twins}")
    if meta(db, "vectors") != "real":
        print("  These two numbers mean nothing here: the vectors aren't from the real model.")
    hints, passed = db.execute("SELECT COUNT(*), COALESCE(SUM(passed), 0) FROM hints").fetchone()
    print(f"\nModel hints stored: {hints}, of which {passed} passed the checks and can be shown")


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
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=list(STEPS) + ["all"])
    p.add_argument("--input", nargs="+", default=["data/train.jsonl", "data/val.jsonl"])
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--images", default=S.IMAGES_DIR)
    p.add_argument("--temes", default=S.TEMES_PATH, help="the team's topics (default data/temes.json)")
    p.add_argument("--classifier", action="store_true", help="classify even if data/temes.json exists")
    p.add_argument("--hand", default="", help="for the classifier: CSV with id,topic labelled by hand")
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
    elif args.step != "bank" and not is_current(db):
        sys.exit(f"{args.db} was built by an older version. Run: python3 tutor_build.py all")
    else:
        STEPS[args.step](db, args)
    db.close()


if __name__ == "__main__":
    main()

"""The tutor itself: what the web page calls.

    tutor = Tutor("data/tutor.db")
    student = tutor.start("Marta", level=2)
    step = tutor.next(student["student_id"])        # a problem, never its answer
    tutor.hint(step["attempt_id"])                  # one rung up the hint ladder
    tutor.answer(step["attempt_id"], "C")           # right, or a diagnosis and a second try

Every step except the model hint is SQLite and Python: well under a second on
the board. The model hint runs in a thread, and the page polls status().
"""
import json
import os
import random
import threading
import time
import urllib.error

from . import engine, llmhint, matrix
from . import settings as S
from .db import connect
from .diagnose import GENERIC, message as diagnosis_message
from .textutil import numbers_in, split_question, strip_numbering
from .topics import load_cards, load_topics

FLASH_SECONDS = 1.5


class TutorError(Exception):
    """A request the tutor can't serve: the page shows the message."""


class Tutor:
    def __init__(self, db_path=S.DB_PATH, images_dir=S.IMAGES_DIR, language=S.LANGUAGE,
                 llm=llmhint, live_hints=S.LIVE_HINTS, warm_cache=S.WARM_CACHE):
        self.db = connect(db_path, check_same_thread=False)
        self.db_path = db_path
        self.images_dir = images_dir
        self.llm = llm
        self.live_hints = live_hints
        self.warm_cache = warm_cache
        self.lock = threading.RLock()       # one request at a time touches the database
        self.llm_lock = threading.Lock()    # the model server has one slot
        self.jobs = {}                      # attempt_id -> {"status", "text"}
        self.flash = None                   # (frame, until)
        self.active_student = None
        self.topics = {t["key"]: t for t in load_topics()}
        self.cards = load_cards()
        self.language = self._pick_language(language)
        self.available = self._available_topics()

    # --- Setup ---------------------------------------------------------------

    def _pick_language(self, wanted):
        counts = dict(self.db.execute(
            "SELECT language, COUNT(*) FROM problem_texts WHERE servable = 1 GROUP BY language"))
        if not counts:
            raise TutorError("The bank is empty. Run tutor_build.py first.")
        return wanted if wanted in counts else max(counts, key=counts.get)

    def _eligible(self):
        """Problems sure enough of their topic to count towards mastery."""
        return "(p.topic_margin >= :margin OR p.topic_source = 'hand')"

    def _available_topics(self):
        rows = self.db.execute(
            f"""SELECT p.topic, COUNT(*) FROM problems p
                JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.servable = 1
                WHERE {self._eligible()} GROUP BY p.topic""",
            {"lang": self.language, "margin": S.MIN_TOPIC_MARGIN}).fetchall()
        return [topic for topic, count in rows if topic in self.topics and count > 0]

    # --- Students ------------------------------------------------------------

    def start(self, name, level):
        name = (name or "").strip()[:40]
        if not name:
            raise TutorError("Escriu un nom.")
        level = min(7, max(0, int(level)))
        with self.lock:
            row = self.db.execute("SELECT * FROM students WHERE name = ?", (name,)).fetchone()
            if row is None:
                cursor = self.db.execute("INSERT INTO students (name, level) VALUES (?, ?)", (name, level))
                student_id = cursor.lastrowid
            else:
                student_id = row["student_id"]
                level = row["level"]
            for topic in self.available:
                self.db.execute(
                    "INSERT OR IGNORE INTO student_topic (student_id, topic, theta) VALUES (?, ?, ?)",
                    (student_id, topic, engine.initial_theta(level)))
            self.db.commit()
            self.active_student = student_id
            return self.profile(student_id)

    def _student(self, student_id):
        row = self.db.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
        if row is None:
            raise TutorError("No conec aquest alumne. Torna a començar.")
        return row

    def _topic_rows(self, student_id):
        rows = self.db.execute("SELECT * FROM student_topic WHERE student_id = ?", (student_id,)).fetchall()
        return [dict(r) for r in rows if r["topic"] in self.available]

    def profile(self, student_id):
        with self.lock:
            student = self._student(student_id)
            topics = []
            for row in sorted(self._topic_rows(student_id), key=lambda r: self.available.index(r["topic"])):
                due_in = None
                if row["state"] == "mastered" and row["review_due_at"] is not None:
                    due_in = max(0, row["review_due_at"] - student["n_done"])
                topics.append({
                    "topic": row["topic"], "name": self.topics[row["topic"]]["name"],
                    "short": self.topics[row["topic"]]["short"], "state": row["state"],
                    "theta": round(row["theta"]), "attempts": row["n_attempts"],
                    "progress": round(engine.progress(row["theta"], student["level"]), 3),
                    "review_in": due_in})
            done, right = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(correct_first), 0) FROM attempts "
                "WHERE student_id = ? AND status = 'done'", (student_id,)).fetchone()
            return {"student_id": student_id, "name": student["name"], "level": student["level"],
                    "done": done, "correct_first": right, "topics": topics}

    # --- Choosing the next problem -------------------------------------------

    def next(self, student_id):
        with self.lock:
            student = self._student(student_id)
            self.active_student = student_id
            open_attempt = self.db.execute(
                "SELECT * FROM attempts WHERE student_id = ? AND status != 'done' "
                "ORDER BY attempt_id DESC LIMIT 1", (student_id,)).fetchone()
            if open_attempt is not None:
                return self._step(open_attempt)

            rng = random.Random(f"{S.SEED}-{student_id}-{student['n_done']}")
            rows = self._topic_rows(student_id)
            if not rows:
                raise TutorError("No hi ha problemes disponibles en aquesta llengua.")
            by_topic = {r["topic"]: r for r in rows}

            problem_id, is_repair = None, False
            if student["repair_for"]:
                problem_id = self._repair_problem(student_id, student["repair_for"])
                is_repair = problem_id is not None
            if problem_id is None:
                last = [t for t in student["last_topics"].split(",") if t]
                candidates = list(rows)
                while candidates and problem_id is None:
                    topic = engine.choose_topic(candidates, student["n_done"], last, rng)
                    problem_id = self._problem_for(student_id, topic, by_topic[topic]["theta"], rng)
                    if problem_id is None:  # the student has done every problem of this topic
                        candidates = [c for c in candidates if c["topic"] != topic]
            if problem_id is None:
                raise TutorError("Has fet tots els problemes del banc. Enhorabona!")

            problem = self.db.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
            topic = problem["topic"]
            if topic not in by_topic:  # a repair problem from a topic we don't track
                self.db.execute(
                    "INSERT OR IGNORE INTO student_topic (student_id, topic, theta) VALUES (?, ?, ?)",
                    (student_id, topic, engine.initial_theta(student["level"])))
                theta, state = engine.initial_theta(student["level"]), "new"
            else:
                theta, state = by_topic[topic]["theta"], by_topic[topic]["state"]
            cursor = self.db.execute(
                """INSERT INTO attempts (student_id, problem_id, topic, started_at, p_expected,
                                         theta_before, is_review, is_repair)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (student_id, problem_id, topic, time.time(), engine.p_correct(theta, problem["b"]),
                 theta, int(state == "mastered"), int(is_repair)))
            self.db.execute("UPDATE students SET repair_for = NULL WHERE student_id = ?", (student_id,))
            self.db.commit()
            attempt = self.db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (cursor.lastrowid,)).fetchone()
            self._warm(attempt)
            return self._step(attempt)

    def _problem_for(self, student_id, topic, theta, rng):
        """The unseen problem of this topic whose difficulty is nearest to the target."""
        rows = self.db.execute(
            f"""SELECT p.id FROM problems p
                JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.servable = 1
                WHERE p.topic = :topic AND {self._eligible()}
                  AND p.id NOT IN (SELECT problem_id FROM attempts WHERE student_id = :student)
                ORDER BY ABS(p.b - :target), p.id LIMIT 5""",
            {"lang": self.language, "topic": topic, "margin": S.MIN_TOPIC_MARGIN,
             "student": student_id, "target": engine.target_b(theta)}).fetchall()
        return rng.choice(rows)["id"] if rows else None

    def _repair_problem(self, student_id, failed_id):
        """After two wrong answers: the most similar problem that is easier."""
        failed = self.db.execute("SELECT topic, b FROM problems WHERE id = ?", (failed_id,)).fetchone()
        if failed is None:
            return None
        row = self.db.execute(
            """SELECT n.neighbor_id FROM neighbors n
               JOIN problems p ON p.id = n.neighbor_id
               JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.servable = 1
               WHERE n.id = :failed AND p.b <= :b
                 AND p.id NOT IN (SELECT problem_id FROM attempts WHERE student_id = :student)
               ORDER BY (p.topic = :topic) DESC, n.sim DESC LIMIT 1""",
            {"lang": self.language, "failed": failed_id, "b": failed["b"] - 40,
             "student": student_id, "topic": failed["topic"]}).fetchone()
        return row["neighbor_id"] if row else None

    # --- What the page gets --------------------------------------------------

    def _text(self, problem_id, language=None):
        row = self.db.execute("SELECT * FROM problem_texts WHERE id = ? AND language = ?",
                              (problem_id, language or self.language)).fetchone()
        if row is None:
            row = self.db.execute("SELECT * FROM problem_texts WHERE id = ? LIMIT 1", (problem_id,)).fetchone()
        return row

    def _public_problem(self, problem_id):
        """A problem without its label, so the page can't give the answer away."""
        row = self._text(problem_id)
        level = self.db.execute("SELECT level FROM problems WHERE id = ?", (problem_id,)).fetchone()["level"]
        return {"id": problem_id, "text": strip_numbering(row["text"]), "options": json.loads(row["options"]),
                "image": "/img/" + row["image"] if row["image"] else None, "level": level}

    def _step(self, attempt):
        topic = self.topics.get(attempt["topic"])
        return {"attempt_id": attempt["attempt_id"], "status": attempt["status"],
                "problem": self._public_problem(attempt["problem_id"]),
                "topic": {"key": attempt["topic"], "name": topic["name"] if topic else attempt["topic"]},
                "is_review": bool(attempt["is_review"]), "is_repair": bool(attempt["is_repair"]),
                "rung": attempt["rung"], "max_rung": S.MAX_RUNG,
                "discarded": [x for x in attempt["discarded"] if x],
                "first_answer": attempt["first_answer"]}

    def _attempt(self, attempt_id, must_be_open=True):
        row = self.db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise TutorError("No trobo aquest problema. Demana'n un de nou.")
        if must_be_open and row["status"] == "done":
            raise TutorError("Aquest problema ja està tancat.")
        return row

    # --- Hints ---------------------------------------------------------------

    def hint(self, attempt_id):
        """One rung up. A rung with nothing to say is skipped, and doesn't cost anything."""
        with self.lock:
            attempt = self._attempt(attempt_id)
            if self.jobs.get(attempt_id, {}).get("status") == "busy":
                return {"rung": attempt["rung"], "kind": "model", "busy": True}
            rung = attempt["rung"]
            while rung < S.MAX_RUNG:
                rung += 1
                payload = self._rung(attempt, rung)
                if payload is None:
                    continue
                counted = 0 if payload.get("busy") or payload["kind"] == "answer" else 1
                self.db.execute("UPDATE attempts SET rung = ?, hints_used = hints_used + ? WHERE attempt_id = ?",
                                (rung, counted, attempt_id))
                self.db.execute("INSERT INTO hint_events VALUES (?, ?, ?, ?, ?)",
                                (attempt_id, rung, payload["kind"], payload.get("ref"), time.time()))
                self.db.commit()
                payload.update(rung=rung, max_rung=S.MAX_RUNG)
                if payload["kind"] == "answer":
                    payload["result"] = self._finish(self._attempt(attempt_id), False, False)
                return payload
            raise TutorError("No queden més pistes.")

    def _rung(self, attempt, rung):
        problem_id = attempt["problem_id"]
        if rung == 1:   # understand the question: code only
            text = self._text(problem_id)["text"]
            context, question = split_question(text)
            data = [f"{n:g}" for n in numbers_in(text)]
            return {"kind": "understand", "question": question, "context": context, "data": data}
        if rung == 2:   # a strategy and an analogy, written by the team
            cards = self.cards.get(attempt["topic"])
            if not cards:
                return None
            seen = self.db.execute(
                "SELECT COUNT(*) FROM hint_events h JOIN attempts a ON a.attempt_id = h.attempt_id "
                "WHERE a.student_id = ? AND a.topic = ? AND h.kind = 'strategy'",
                (attempt["student_id"], attempt["topic"])).fetchone()[0]
            return dict(cards[seen % len(cards)], kind="strategy")
        if rung == 3:   # a similar problem: one the student solved, or an easier one
            return self._related(attempt)
        if rung == 4:   # ask the student to rule options out
            if not json.loads(self._text(problem_id)["options"]):
                return None
            return {"kind": "discard"}
        if rung == 5:   # one sentence from the model, if it passes the checks
            return self._model_hint(attempt)
        label, value = self._label(problem_id)
        easier = self._easier_example(attempt)
        return {"kind": "answer", "label": label, "value": value, "example": easier}

    def _related(self, attempt):
        row = self.db.execute(
            """SELECT n.neighbor_id, n.sim FROM neighbors n
               JOIN attempts a ON a.problem_id = n.neighbor_id
               WHERE n.id = ? AND a.student_id = ? AND a.correct_first = 1 AND a.status = 'done'
               ORDER BY n.sim DESC LIMIT 1""", (attempt["problem_id"], attempt["student_id"])).fetchone()
        if row is not None:
            label, value = self._label(row["neighbor_id"])
            return {"kind": "solved_before", "ref": row["neighbor_id"],
                    "problem": self._public_problem(row["neighbor_id"]), "label": label, "value": value}
        easier = self._easier_example(attempt)
        if easier is None:
            return None
        return dict(easier, kind="easier_example")

    def _easier_example(self, attempt):
        """The nearest easier problem, with its answer: a worked example from M3Kang."""
        b = self.db.execute("SELECT b FROM problems WHERE id = ?", (attempt["problem_id"],)).fetchone()["b"]
        row = self.db.execute(
            """SELECT n.neighbor_id FROM neighbors n
               JOIN problems p ON p.id = n.neighbor_id
               JOIN problem_texts t ON t.id = p.id AND t.language = ? AND t.servable = 1
               WHERE n.id = ? AND p.b < ? ORDER BY n.sim DESC LIMIT 1""",
            (self.language, attempt["problem_id"], b)).fetchone()
        if row is None:
            return None
        label, value = self._label(row["neighbor_id"])
        return {"ref": row["neighbor_id"], "problem": self._public_problem(row["neighbor_id"]),
                "label": label, "value": value}

    def _label(self, problem_id):
        label = self.db.execute("SELECT label FROM problems WHERE id = ?", (problem_id,)).fetchone()["label"]
        options = json.loads(self._text(problem_id)["options"])
        return label, options.get(label)

    def _stored_hint(self, problem_id):
        row = self.db.execute("SELECT text, passed FROM hints WHERE id = ? AND kind = 'first_step' "
                              "ORDER BY (language = ?) DESC LIMIT 1", (problem_id, self.language)).fetchone()
        return row

    def _model_hint(self, attempt):
        stored = self._stored_hint(attempt["problem_id"])
        if stored is not None:
            return {"kind": "model", "text": stored["text"]} if stored["passed"] else None
        if not self.live_hints:
            return None
        attempt_id = attempt["attempt_id"]
        self.jobs[attempt_id] = {"status": "busy", "text": None}
        self.flash = (matrix.wait(), time.time() + 120)
        threading.Thread(target=self._generate, args=(attempt_id, attempt["problem_id"]), daemon=True).start()
        return {"kind": "model", "busy": True}

    def _source_text(self, problem_id):
        """The model reads English best, so it gets the English text when we have it."""
        return self._text(problem_id, S.VECTOR_LANGUAGE)["text"]

    def _generate(self, attempt_id, problem_id):
        job = self.jobs[attempt_id]
        try:
            with self.llm_lock:
                text, seconds, _read = self.llm.generate(self._source_text(problem_id))
            with self.lock:
                label = self.db.execute("SELECT label FROM problems WHERE id = ?", (problem_id,)).fetchone()["label"]
                shown = self._text(problem_id)
                passed, reason = self.llm.check(text, [shown["text"], self._source_text(problem_id)],
                                                json.loads(shown["options"]), label)
                self.db.execute("INSERT OR REPLACE INTO hints VALUES (?, ?, 'first_step', ?, ?, ?, ?)",
                                (problem_id, self.language, text, int(passed), reason, seconds))
                if passed:
                    self.db.execute("UPDATE attempts SET hints_used = hints_used + 1 WHERE attempt_id = ?",
                                    (attempt_id,))
                self.db.commit()
            job.update(status="done" if passed else "rejected", text=text if passed else None)
        except (OSError, urllib.error.URLError, KeyError, ValueError) as error:
            job.update(status="failed", text=None, error=str(error))
        finally:
            self.flash = None

    def _warm(self, attempt):
        """Let the model read the problem while the student reads it too."""
        if not (self.warm_cache and self.live_hints) or self._stored_hint(attempt["problem_id"]) is not None:
            return
        text = self._source_text(attempt["problem_id"])

        def run():
            try:
                with self.llm_lock:
                    self.llm.warm(text)
            except (OSError, urllib.error.URLError, KeyError, ValueError):
                pass  # no model server: the ladder simply skips the model rung

        threading.Thread(target=run, daemon=True).start()

    def status(self, attempt_id):
        """The page polls this while the model writes."""
        job = self.jobs.get(attempt_id)
        if job is None:
            return {"busy": False, "kind": "model", "text": None}
        if job["status"] == "busy":
            return {"busy": True, "kind": "model"}
        return {"busy": False, "kind": "model", "text": job["text"], "rejected": job["status"] != "done"}

    def discard(self, attempt_id, letter):
        """The student rules an option out. We only tell them how it went at the end:
        saying 'not that one' now would give the answer away."""
        letter = letter.upper()
        with self.lock:
            attempt = self._attempt(attempt_id)
            if letter not in "ABCDE" or len(letter) != 1:
                raise TutorError("Tria una opció de la A a la E.")
            marked = set(attempt["discarded"])
            marked.symmetric_difference_update({letter})
            self.db.execute("UPDATE attempts SET discarded = ? WHERE attempt_id = ?",
                            ("".join(sorted(marked)), attempt_id))
            self.db.commit()
            return {"discarded": sorted(marked)}

    # --- Answers -------------------------------------------------------------

    def answer(self, attempt_id, letter):
        letter = (letter or "").upper()
        if len(letter) != 1 or letter not in "ABCDE":
            raise TutorError("Tria una opció de la A a la E.")
        with self.lock:
            attempt = self._attempt(attempt_id)
            label, _value = self._label(attempt["problem_id"])
            correct = letter == label
            if attempt["status"] == "open":
                self.db.execute("UPDATE attempts SET first_answer = ?, tries = 1 WHERE attempt_id = ?",
                                (letter, attempt_id))
                if correct:
                    self.db.execute("UPDATE attempts SET final_answer = ? WHERE attempt_id = ?", (letter, attempt_id))
                    return self._finish(self._attempt(attempt_id), True, True)
                self.db.execute("UPDATE attempts SET status = 'retry' WHERE attempt_id = ?", (attempt_id,))
                self.db.commit()
                self.flash = (matrix.cross(), time.time() + FLASH_SECONDS)
                return {"correct": False, "retry": True, "answer": letter,
                        "diagnosis": self._diagnosis(attempt["problem_id"], letter)}
            if letter == attempt["first_answer"]:
                raise TutorError("Aquesta ja l'has provada. Tria'n una altra.")
            self.db.execute("UPDATE attempts SET final_answer = ?, tries = 2 WHERE attempt_id = ?",
                            (letter, attempt_id))
            return self._finish(self._attempt(attempt_id), False, correct)

    def _diagnosis(self, problem_id, letter):
        row = self.db.execute("SELECT misconception FROM options WHERE id = ? AND letter = ?",
                              (problem_id, letter)).fetchone()
        code = row["misconception"] if row else None
        return {"code": code, "message": diagnosis_message(code) if code else GENERIC}

    def _finish(self, attempt, correct_first, correct_final):
        """Close the attempt: update the rating, the topic state and the review calendar."""
        student = self._student(attempt["student_id"])
        topic_row = self.db.execute("SELECT * FROM student_topic WHERE student_id = ? AND topic = ?",
                                    (student["student_id"], attempt["topic"])).fetchone()
        topic = dict(topic_row)
        problem = self.db.execute("SELECT b FROM problems WHERE id = ?", (attempt["problem_id"],)).fetchone()
        hints = attempt["hints_used"]
        s = engine.score(correct_first, correct_final, hints)
        expected = engine.p_correct(topic["theta"], problem["b"])
        before, state_before = topic["theta"], topic["state"]
        topic["theta"] = engine.update_theta(topic["theta"], problem["b"], s, topic["n_attempts"])
        n_done = student["n_done"] + 1
        topic = engine.next_state(topic, engine.is_clean(correct_first, hints), correct_first, n_done, student["level"])

        self.db.execute(
            """UPDATE student_topic SET theta = ?, n_attempts = ?, recent = ?, state = ?,
                      review_interval = ?, review_due_at = ? WHERE student_id = ? AND topic = ?""",
            (topic["theta"], topic["n_attempts"], topic["recent"], topic["state"], topic["review_interval"],
             topic["review_due_at"], student["student_id"], attempt["topic"]))
        # What we learn in one topic also moves the topics we still know little about
        self.db.execute(
            """UPDATE student_topic SET theta = theta + ? / ((1 + n_attempts) * (1 + n_attempts))
               WHERE student_id = ? AND topic != ? AND state != 'mastered'""",
            (S.SHARE * (topic["theta"] - before), student["student_id"], attempt["topic"]))
        last = ([t for t in student["last_topics"].split(",") if t] + [attempt["topic"]])[-5:]
        # One repair problem after a failure, but never a chain of them
        repair = attempt["problem_id"] if not correct_final and not attempt["is_repair"] else None
        self.db.execute("UPDATE students SET n_done = ?, last_topics = ?, repair_for = ? WHERE student_id = ?",
                        (n_done, ",".join(last), repair, student["student_id"]))
        if S.K_PROBLEM:
            self.db.execute("UPDATE problems SET b = b + ? WHERE id = ?",
                            (S.K_PROBLEM * (expected - s), attempt["problem_id"]))
        self.db.execute(
            """UPDATE attempts SET status = 'done', finished_at = ?, correct_first = ?, correct_final = ?,
                      score = ?, theta_after = ? WHERE attempt_id = ?""",
            (time.time(), int(correct_first), int(correct_final), s, topic["theta"], attempt["attempt_id"]))
        self.db.commit()
        self.jobs.pop(attempt["attempt_id"], None)
        self.flash = (matrix.tick() if correct_final else matrix.cross(), time.time() + FLASH_SECONDS)

        label, value = self._label(attempt["problem_id"])
        return {"correct": correct_final, "correct_first": correct_first, "retry": False,
                "label": label, "value": value, "score": round(s, 2),
                "discarded_correct": label in attempt["discarded"],
                "topic": {"key": attempt["topic"], "state_before": state_before, "state": topic["state"],
                          "theta_change": round(topic["theta"] - before)},
                "profile": self.profile(student["student_id"])}

    # --- LED matrix ----------------------------------------------------------

    def frame(self):
        """What the matrix should show now: a tick or a cross for a moment, else the profile."""
        if self.flash and time.time() < self.flash[1]:
            return self.flash[0]
        with self.lock:
            if self.active_student is None:
                return matrix.blank()
            student = self._student(self.active_student)
            rows = sorted(self._topic_rows(self.active_student), key=lambda r: self.available.index(r["topic"]))
            return matrix.profile([(engine.progress(r["theta"], student["level"]), r["state"] == "mastered")
                                   for r in rows])

    def image_path(self, name):
        path = os.path.join(self.images_dir, os.path.basename(name))
        return path if os.path.isfile(path) else None

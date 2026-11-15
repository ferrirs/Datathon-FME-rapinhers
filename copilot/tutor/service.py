"""The tutor itself: what the web page calls.

    tutor = Tutor("data/tutor.db")
    student = tutor.start("Marta", level=2)
    step = tutor.next(student["student_id"])        # a problem, never its answer
    tutor.hint(step["attempt_id"])                  # one rung up the hint ladder
    tutor.answer(step["attempt_id"], "C")           # right, or a diagnosis and a second try

Every step is SQLite and Python: well under a second on the board. The only
exception is a hint written on the spot by the model, which is off unless
TUTOR_LIVE_HINTS=1: it runs in a thread, and the page polls status().
"""
import json
import os
import random
import threading
import time
import urllib.error

from . import engine, llmhint, matrix
from . import settings as S
from .db import connect, is_current
from .diagnose import GENERIC, message as diagnosis_message
from .textutil import numbers_in, split_question, strip_numbering
from .topics import load_analogies, load_cards, load_topics

FLASH_SECONDS = 1.5


class TutorError(Exception):
    """A request the tutor can't serve: the page shows the message."""


class Tutor:
    def __init__(self, db_path=S.DB_PATH, images_dir=S.IMAGES_DIR, language=S.LANGUAGE,
                 llm=llmhint, live_hints=S.LIVE_HINTS, warm_cache=S.WARM_CACHE):
        self.db = connect(db_path, check_same_thread=False)
        if not is_current(self.db):
            raise TutorError("This bank was built by an older version. Build it again: python3 tutor_build.py all")
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
        self.topics, self.cards = self._load_topics()
        self.language = self._pick_language(language)
        self.available = self._topics_up_to(S.MAX_LEVEL, 1)
        if not self.available:
            raise TutorError("No problem of the bank has a topic. Build it again: python3 tutor_build.py all")

    # --- Setup ---------------------------------------------------------------

    def _load_topics(self):
        """The team's topics, stored by tutor_build.py from data/temes.json, or the built-in ones.

        Returns ({key: {"name", "position"}}, {key: [card, ...]}). A card is
        {"title", "body", "analogy"}. A team topic gives its method sentences as titles,
        and an analogy from content/analogies_ca.json when there is one for its name.
        """
        rows = self.db.execute("SELECT * FROM topics ORDER BY position").fetchall()
        if not rows:
            return {t["key"]: {"name": t["name"], "position": i} for i, t in enumerate(load_topics())}, load_cards()
        analogies = load_analogies()
        topics, cards = {}, {}
        for row in rows:
            topics[row["key"]] = {"name": row["name"], "position": row["position"]}
            cards[row["key"]] = [{"title": method, "body": "", "analogy": analogies.get(row["name"], "")}
                                 for method in json.loads(row["methods"] or "[]")]
        return topics, cards

    def _pick_language(self, wanted):
        counts = dict(self.db.execute(
            "SELECT language, COUNT(*) FROM problem_texts WHERE display != '' GROUP BY language"))
        if not counts:
            raise TutorError("The bank is empty. Build it first: python3 tutor_build.py all")
        return wanted if wanted in counts else max(counts, key=counts.get)

    def _topics_up_to(self, level, at_least):
        """Topics with enough problems a student can see, up to a level, in display order."""
        rows = dict(self.db.execute(
            """SELECT p.topic, COUNT(*) FROM problems p
               JOIN problem_texts t ON t.id = p.id AND t.language = ? AND t.display != ''
               WHERE p.topic_ok = 1 AND p.level <= ? GROUP BY p.topic""", (self.language, level)).fetchall())
        found = [key for key, count in rows.items() if key in self.topics and count >= at_least]
        return sorted(found, key=lambda key: self.topics[key]["position"])

    # --- Students ------------------------------------------------------------

    def start(self, name, level):
        name = (name or "").strip()[:40]
        if not name:
            raise TutorError("Escriu el teu nom.")
        level = min(S.MAX_LEVEL, max(0, int(level)))
        with self.lock:
            row = self.db.execute("SELECT * FROM students WHERE name = ?", (name,)).fetchone()
            if row is None:
                student_id = self.db.execute("INSERT INTO students (name, level) VALUES (?, ?)",
                                             (name, level)).lastrowid
            else:
                student_id, level = row["student_id"], row["level"]
            if not self._topic_rows(student_id):
                # Only the topics with problems near the student's grade: no angles in 5è de primària
                topics = self._topics_up_to(min(S.MAX_LEVEL, level + 1), S.MIN_TOPIC_PROBLEMS) or self.available
                self.db.executemany(
                    "INSERT OR REPLACE INTO student_topic (student_id, topic, theta) VALUES (?, ?, ?)",
                    [(student_id, topic, engine.initial_theta(level)) for topic in topics])
            self.db.commit()
            self.active_student = student_id
            return self.profile(student_id)

    def _student(self, student_id):
        row = self.db.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
        if row is None:
            raise TutorError("No conec aquest alumne. Torna a començar.")
        return row

    def _topic_rows(self, student_id):
        """The student's topics, in display order: the columns of the LED matrix."""
        rows = self.db.execute("SELECT * FROM student_topic WHERE student_id = ?", (student_id,)).fetchall()
        rows = [dict(r) for r in rows if r["topic"] in self.topics]
        return sorted(rows, key=lambda r: self.topics[r["topic"]]["position"])

    def _profile_frame(self, rows, level):
        return matrix.profile([(engine.progress(r["theta"], level), r["state"] == "mastered") for r in rows])

    def profile(self, student_id):
        with self.lock:
            student = self._student(student_id)
            rows = self._topic_rows(student_id)
            topics = []
            for row in rows:
                due_in = None
                if row["state"] == "mastered" and row["review_due_at"] is not None:
                    due_in = max(0, row["review_due_at"] - student["n_done"])
                topics.append({
                    "topic": row["topic"], "name": self.topics[row["topic"]]["name"], "state": row["state"],
                    "theta": round(row["theta"]), "attempts": row["n_attempts"],
                    "progress": round(engine.progress(row["theta"], student["level"]), 3),
                    "review_in": due_in})
            done, right = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(correct_first), 0) FROM attempts "
                "WHERE student_id = ? AND status = 'done'", (student_id,)).fetchone()
            return {"student_id": student_id, "name": student["name"], "level": student["level"],
                    "done": done, "correct_first": right, "topics": topics,
                    "matrix": self._profile_frame(rows, student["level"])}

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
            by_topic = {r["topic"]: r for r in rows}

            problem_id, is_repair = None, False
            if student["repair_for"]:
                problem_id = self._repair_problem(student, student["repair_for"], list(by_topic))
                is_repair = problem_id is not None
            if problem_id is None:
                last = [t for t in student["last_topics"].split(",") if t]
                candidates = list(rows)
                while candidates and problem_id is None:
                    topic = engine.choose_topic(candidates, student["n_done"], last, rng)
                    problem_id = self._problem_for(student, topic, by_topic[topic]["theta"], rng)
                    if problem_id is None:  # the student has done every problem of this topic
                        candidates = [c for c in candidates if c["topic"] != topic]
            if problem_id is None:
                raise TutorError("Has fet tots els problemes del teu nivell. Enhorabona!")

            problem = self.db.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
            topic = by_topic[problem["topic"]]
            cursor = self.db.execute(
                """INSERT INTO attempts (student_id, problem_id, topic, started_at, p_expected,
                                         theta_before, is_review, is_repair)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (student_id, problem_id, problem["topic"], time.time(),
                 engine.p_correct(topic["theta"], problem["b"]), topic["theta"],
                 int(topic["state"] == "mastered"), int(is_repair)))
            self.db.execute("UPDATE students SET repair_for = NULL WHERE student_id = ?", (student_id,))
            self.db.commit()
            attempt = self.db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (cursor.lastrowid,)).fetchone()
            self._warm(attempt)
            return self._step(attempt)

    @staticmethod
    def _level_cap(student):
        return min(S.MAX_LEVEL, student["level"] + S.LEVELS_ABOVE)

    # SQL: problems the student shouldn't get again. Their own, and the twins of their own:
    # the same question printed in the paper of another grade.
    _SEEN = ("SELECT problem_id FROM attempts WHERE student_id = :student "
             "UNION SELECT n.neighbor_id FROM neighbors n JOIN attempts a ON a.problem_id = n.id "
             "WHERE a.student_id = :student AND n.sim >= :dup_sim")

    def _problem_for(self, student, topic, theta, rng):
        """One of the five unseen problems of this topic whose difficulty is nearest to the target."""
        rows = self.db.execute(
            f"""SELECT p.id FROM problems p
                JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.display != ''
                WHERE p.topic = :topic AND p.topic_ok = 1 AND p.level <= :cap
                  AND p.id NOT IN ({self._SEEN})
                ORDER BY ABS(p.b - :target), p.id LIMIT 5""",
            {"lang": self.language, "topic": topic, "cap": self._level_cap(student),
             "student": student["student_id"], "target": engine.target_b(theta),
             "dup_sim": S.DUP_SIM}).fetchall()
        return rng.choice(rows)["id"] if rows else None

    def _repair_problem(self, student, failed_id, topics):
        """After two wrong answers: the most similar problem that is easier."""
        failed = self.db.execute("SELECT topic, b FROM problems WHERE id = ?", (failed_id,)).fetchone()
        if failed is None:
            return None
        row = self.db.execute(
            f"""SELECT n.neighbor_id FROM neighbors n
                JOIN problems p ON p.id = n.neighbor_id
                JOIN problem_texts t ON t.id = p.id AND t.language = :lang AND t.display != ''
                WHERE n.id = :failed AND p.b <= :b AND p.level <= :cap
                  AND n.sim >= :min_sim AND n.sim < :dup_sim
                  AND p.topic IN ({",".join(f":t{i}" for i in range(len(topics)))})
                  AND p.id NOT IN ({self._SEEN})
                ORDER BY (p.topic = :topic) DESC, n.sim DESC LIMIT 1""",
            {"lang": self.language, "failed": failed_id, "b": failed["b"] - 40, "cap": self._level_cap(student),
             "min_sim": S.MIN_SIM, "dup_sim": S.DUP_SIM, "student": student["student_id"],
             "topic": failed["topic"], **{f"t{i}": t for i, t in enumerate(topics)}}).fetchone()
        return row["neighbor_id"] if row else None

    # --- What the page gets --------------------------------------------------

    def _text(self, problem_id, language=None):
        row = self.db.execute("SELECT * FROM problem_texts WHERE id = ? AND language = ?",
                              (problem_id, language or self.language)).fetchone()
        if row is None:
            row = self.db.execute("SELECT * FROM problem_texts WHERE id = ? LIMIT 1", (problem_id,)).fetchone()
        return row

    def _public_problem(self, problem_id):
        """A problem without its label, so the page can't give the answer away.

        mode 'text': the text and the five options, typeset by the page. The image is
        there too, so the student can look at the original.
        mode 'image': the scanned problem is what the student reads, options included.
        OCR often misreads drawn options ("ALL", "A△△O"), so we don't show its guess.
        """
        row = self._text(problem_id)
        level = self.db.execute("SELECT level FROM problems WHERE id = ?", (problem_id,)).fetchone()["level"]
        mode = "text" if row["display"] == "text" else "image"
        return {"id": problem_id, "mode": mode, "text": strip_numbering(row["text"]),
                "options": json.loads(row["options"]) if mode == "text" else {},
                "image": "/img/" + row["image"] if row["image"] else None, "level": level}

    def _label(self, problem_id):
        """(letter, value). The value only when the page shows values: see _public_problem."""
        label = self.db.execute("SELECT label FROM problems WHERE id = ?", (problem_id,)).fetchone()["label"]
        row = self._text(problem_id)
        value = json.loads(row["options"]).get(label) if row["display"] == "text" else None
        return label, value

    def _step(self, attempt):
        return {"attempt_id": attempt["attempt_id"], "status": attempt["status"],
                "problem": self._public_problem(attempt["problem_id"]),
                "topic": {"key": attempt["topic"], "name": self.topics[attempt["topic"]]["name"]},
                "is_review": bool(attempt["is_review"]), "is_repair": bool(attempt["is_repair"]),
                "rung": attempt["rung"], "max_rung": S.MAX_RUNG,
                "discarded": list(attempt["discarded"]), "first_answer": attempt["first_answer"]}

    def _attempt(self, attempt_id):
        row = self.db.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if row is None:
            raise TutorError("No trobo aquest problema. Demana'n un de nou.")
        if row["status"] == "done":
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
                payload.update(rung=rung, max_rung=S.MAX_RUNG, last=self._is_last_hint(attempt, rung))
                if payload["kind"] == "answer":
                    payload["result"] = self._finish(self._attempt(attempt_id), False, False)
                return payload
            raise TutorError("No queden més pistes.")

    def _is_last_hint(self, attempt, rung):
        """True when the next click on the hint button shows the answer."""
        if rung >= S.MAX_RUNG - 1:
            return True
        return rung == S.MAX_RUNG - 2 and not self._model_may_speak(attempt["problem_id"])

    def _rung(self, attempt, rung):
        problem_id = attempt["problem_id"]
        if rung == 1:   # understand the question: code only
            text = self._text(problem_id)["text"]
            _context, question = split_question(text)
            data = [str(int(n)) if float(n).is_integer() else f"{n:.10g}" for n in numbers_in(text)]
            return {"kind": "understand", "question": question, "data": data}
        if rung == 2:   # the method of the topic, written by the team
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
            return {"kind": "discard"}
        if rung == 5:   # one sentence from the model, if it passed the checks
            return self._model_hint(attempt)
        label, value = self._label(problem_id)
        return {"kind": "answer", "label": label, "value": value, "example": self._easier_example(attempt)}

    def _related(self, attempt):
        row = self.db.execute(
            """SELECT n.neighbor_id FROM neighbors n
               JOIN attempts a ON a.problem_id = n.neighbor_id
               WHERE n.id = ? AND a.student_id = ? AND a.correct_first = 1 AND a.status = 'done'
                 AND n.sim >= ? AND n.sim < ?
               ORDER BY n.sim DESC LIMIT 1""",
            (attempt["problem_id"], attempt["student_id"], S.MIN_SIM, S.DUP_SIM)).fetchone()
        if row is not None:
            label, value = self._label(row["neighbor_id"])
            return {"kind": "solved_before", "ref": row["neighbor_id"],
                    "problem": self._public_problem(row["neighbor_id"]), "label": label, "value": value}
        easier = self._easier_example(attempt)
        return dict(easier, kind="easier_example") if easier else None

    def _easier_example(self, attempt):
        """The nearest easier problem, with its answer: a worked example from M3Kang.

        Easier means a lower difficulty. Similar enough means MIN_SIM, and the same topic comes first.
        """
        b = self.db.execute("SELECT b FROM problems WHERE id = ?", (attempt["problem_id"],)).fetchone()["b"]
        row = self.db.execute(
            """SELECT n.neighbor_id FROM neighbors n
               JOIN problems p ON p.id = n.neighbor_id
               JOIN problem_texts t ON t.id = p.id AND t.language = ? AND t.display != ''
               WHERE n.id = ? AND p.b < ? AND p.level <= ? AND n.sim >= ? AND n.sim < ?
               ORDER BY (p.topic = ?) DESC, n.sim DESC LIMIT 1""",
            (self.language, attempt["problem_id"], b, S.MAX_LEVEL, S.MIN_SIM, S.DUP_SIM,
             attempt["topic"])).fetchone()
        if row is None:
            return None
        label, value = self._label(row["neighbor_id"])
        return {"ref": row["neighbor_id"], "problem": self._public_problem(row["neighbor_id"]),
                "label": label, "value": value}

    def _stored_hint(self, problem_id):
        return self.db.execute("SELECT text, passed FROM hints WHERE id = ? AND kind = 'first_step' "
                               "ORDER BY (language = ?) DESC LIMIT 1", (problem_id, self.language)).fetchone()

    def _model_may_speak(self, problem_id):
        """Is there, or could there be, a model hint for this problem?

        The model only reads text, so it never hints a problem that needs its figure. And a
        hint is only shown after a check against the correct option, which needs the options.
        """
        if self._text(problem_id)["display"] != "text":
            return False
        stored = self._stored_hint(problem_id)
        return bool(stored["passed"]) if stored is not None else self.live_hints

    def _model_hint(self, attempt):
        problem_id = attempt["problem_id"]
        if not self._model_may_speak(problem_id):
            return None
        stored = self._stored_hint(problem_id)
        if stored is not None:
            return {"kind": "model", "text": stored["text"]}
        attempt_id = attempt["attempt_id"]
        self.jobs[attempt_id] = {"status": "busy", "text": None}
        self.flash = (matrix.wait(), time.time() + 120)
        threading.Thread(target=self._generate, args=(attempt_id, problem_id), daemon=True).start()
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
        problem_id = attempt["problem_id"]
        if not (self.warm_cache and self.live_hints) or self._stored_hint(problem_id) is not None \
                or not self._model_may_speak(problem_id):
            return
        text = self._source_text(problem_id)

        def run():
            try:
                with self.llm_lock:
                    self.llm.warm(text)
            except (OSError, urllib.error.URLError, KeyError, ValueError):
                pass  # no model server: the hint will say so

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
        letter = (letter or "").upper()
        if len(letter) != 1 or letter not in "ABCDE":
            raise TutorError("Tria una opció de la A a la E.")
        with self.lock:
            attempt = self._attempt(attempt_id)
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
            self.active_student = attempt["student_id"]
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
                return {"correct": False, "retry": True, "answer": letter, "flash": matrix.cross(),
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
        topic = dict(self.db.execute("SELECT * FROM student_topic WHERE student_id = ? AND topic = ?",
                                     (student["student_id"], attempt["topic"])).fetchone())
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
        flash = matrix.tick() if correct_final else matrix.cross()
        self.flash = (flash, time.time() + FLASH_SECONDS)

        label, value = self._label(attempt["problem_id"])
        return {"correct": correct_final, "correct_first": correct_first, "retry": False,
                "label": label, "value": value, "score": round(s, 2), "flash": flash,
                "discarded_correct": label in attempt["discarded"],
                "topic": {"key": attempt["topic"], "state_before": state_before, "state": topic["state"],
                          "theta_change": round(topic["theta"] - before)},
                "profile": self.profile(student["student_id"])}

    # --- LED matrix ----------------------------------------------------------

    def frame(self):
        """What the matrix should show now: a tick or a cross for a moment, the profile
        of the student who is practising, or a kangaroo while nobody is."""
        if self.flash and time.time() < self.flash[1]:
            return self.flash[0]
        with self.lock:
            if self.active_student is None:
                return matrix.idle()
            student = self._student(self.active_student)
            return self._profile_frame(self._topic_rows(self.active_student), student["level"])

    def image_path(self, name):
        path = os.path.join(self.images_dir, os.path.basename(name))
        return path if os.path.isfile(path) else None

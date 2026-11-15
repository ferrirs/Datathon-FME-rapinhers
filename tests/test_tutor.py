"""Tests for the tutor. No board, no model server and no M3Kang needed:

    python3 -m unittest discover -s tests -v

They build a small bank from made-up problems, with a bag-of-words embedding.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from copilot.tutor import diagnose, engine, llmhint, matrix  # noqa: E402
from copilot.tutor import settings as S  # noqa: E402
from copilot.tutor.service import Tutor, TutorError  # noqa: E402
from copilot.tutor.textutil import numbers_in, option_value, split_question, strip_numbering  # noqa: E402


class FakeModel:
    """Stands in for the language model: answers at once, and counts the calls."""
    check = staticmethod(llmhint.check)

    def __init__(self, text="Fes una llista de les bosses i les pomes."):
        self.text, self.warmed, self.generated = text, 0, 0

    def warm(self, _text):
        self.warmed += 1
        return 0

    def generate(self, _text):
        self.generated += 1
        return self.text, 0.01, 5


class TextTests(unittest.TestCase):
    def test_numbers_skip_the_question_number(self):
        self.assertEqual(numbers_in("13. For 3 days, Joy caught 12 mice and 1/2 a fish."), [3.0, 12.0, 0.5])
        self.assertEqual(strip_numbering("7) What is 2 + 2?"), "What is 2 + 2?")

    def test_decimal_comma_and_minus(self):
        self.assertEqual(numbers_in("La temperatura és de −4 graus i puja 3,5."), [-4.0, 3.5])

    def test_option_value(self):
        self.assertEqual(option_value("12 cm"), 12.0)
        self.assertEqual(option_value("36 cm²"), 36.0)
        self.assertEqual(option_value("1/2"), 0.5)
        self.assertEqual(option_value("25%"), 25.0)
        self.assertIsNone(option_value("a triangle"))
        self.assertIsNone(option_value("3 and 4"))

    def test_split_question(self):
        context, question = split_question("5. Anna has 3 bags. How many apples are left? Choose one.")
        self.assertEqual(question, "How many apples are left?")
        self.assertIn("Anna has 3 bags.", context)


class EngineTests(unittest.TestCase):
    def test_guessing_floor(self):
        self.assertAlmostEqual(engine.p_correct(1000, 1000), 0.6)
        self.assertGreater(engine.p_correct(0, 3000), 0.2 - 1e-9)
        self.assertLess(engine.p_correct(0, 3000), 0.21)

    def test_target_difficulty_gives_target_probability(self):
        for theta in (800, 1000, 1500):
            self.assertAlmostEqual(engine.p_correct(theta, engine.target_b(theta)), S.TARGET_P)

    def test_score(self):
        self.assertEqual(engine.score(True, True, 0), 1.0)
        self.assertAlmostEqual(engine.score(True, True, 2), 0.6)
        self.assertEqual(engine.score(True, True, 5), S.HINT_FLOOR)
        self.assertEqual(engine.score(False, True, 0), S.GUESS)
        self.assertEqual(engine.score(False, False, 0), 0.0)

    def test_lucky_guess_on_a_hard_problem_moves_little(self):
        easy = engine.update_theta(1000, 900, 1.0, 10) - 1000
        hard = engine.update_theta(1000, 2500, 1.0, 10) - 1000
        self.assertGreater(hard, easy)          # a surprise moves more...
        wrong_easy = 1000 - engine.update_theta(1000, 600, 0.0, 10)
        wrong_hard = 1000 - engine.update_theta(1000, 2500, 0.0, 10)
        self.assertGreater(wrong_easy, 3 * wrong_hard)   # ...and failing an easy one costs most

    def test_bands(self):
        self.assertEqual([engine.band_of(q, 30) for q in (1, 10, 11, 20, 21, 30)], [1, 1, 2, 2, 3, 3])
        self.assertEqual([engine.band_of(q, 24) for q in (8, 9, 16, 17)], [1, 2, 2, 3])
        self.assertEqual(engine.band_of(None, 0), 2)

    def topic(self, **changes):
        base = {"topic": "x", "theta": 1000.0, "n_attempts": 0, "recent": "", "state": "new",
                "review_interval": None, "review_due_at": None}
        base.update(changes)
        return base

    def test_two_lucky_answers_are_not_mastery(self):
        topic = self.topic(theta=2000.0)
        for n in (1, 2):
            topic = engine.next_state(topic, True, True, n, level=0)
        self.assertEqual(topic["state"], "learning")

    def test_mastery_then_spaced_review(self):
        topic = self.topic(theta=2000.0)
        for n in range(1, 6):
            topic = engine.next_state(topic, True, True, n, level=0)
        self.assertEqual(topic["state"], "mastered")
        self.assertEqual(topic["review_due_at"], 5 + S.REVIEW_FIRST)
        self.assertEqual(engine.topic_weight(topic, 6), 0.0)                    # not due yet
        self.assertGreater(engine.topic_weight(topic, 5 + S.REVIEW_FIRST), 0)   # due
        passed = engine.next_state(topic, True, True, 11, level=0)
        self.assertEqual(passed["review_interval"], 2 * S.REVIEW_FIRST)         # the gap doubles
        failed = engine.next_state(topic, False, False, 11, level=0)
        self.assertEqual(failed["state"], "consolidating")                      # forgotten: practise again

    def test_hints_do_not_count_as_mastery(self):
        topic = self.topic(theta=2000.0)
        for n in range(1, 9):
            topic = engine.next_state(topic, engine.is_clean(True, 3), True, n, level=0)
        self.assertNotEqual(topic["state"], "mastered")

    def test_never_more_than_three_of_a_topic_in_a_row(self):
        topics = [self.topic(topic="a", state="learning"), self.topic(topic="b", state="consolidating")]
        rng = random.Random(1)
        for _ in range(50):
            self.assertEqual(engine.choose_topic(topics, 3, ["a", "a", "a"], rng), "b")

    def test_weak_topics_come_up_more(self):
        topics = [self.topic(topic="weak", state="learning"),
                  self.topic(topic="done", state="mastered", review_due_at=99)]
        rng = random.Random(1)
        picks = [engine.choose_topic(topics, 3, [], rng) for _ in range(50)]
        self.assertEqual(set(picks), {"weak"})

    def test_everything_mastered_still_picks_something(self):
        topics = [self.topic(topic="a", state="mastered", review_due_at=30),
                  self.topic(topic="b", state="mastered", review_due_at=20)]
        self.assertEqual(engine.choose_topic(topics, 3, [], random.Random(1)), "b")


class DiagnoseTests(unittest.TestCase):
    def test_square_example(self):
        rows = diagnose.annotate("A square has a perimeter of 36 cm. What is its area?",
                                 {"A": "36 cm²", "B": "72 cm²", "C": "81 cm²", "D": "144 cm²", "E": "9 cm²"}, "C")
        codes = {letter: code for letter, _raw, _value, _ok, code in rows}
        self.assertEqual(codes["A"], "DATA_COPY")
        self.assertIsNone(codes["C"])

    def test_rules(self):
        self.assertEqual(diagnose.rule_for(12, 10, [3, 4, 2]), "PARTIAL_STEP")   # 3 x 4, forgot the rest
        self.assertEqual(diagnose.rule_for(20, 10, [7]), "DOUBLE_HALF")
        self.assertEqual(diagnose.rule_for(11, 10, [7]), "OFF_BY_ONE")
        self.assertEqual(diagnose.rule_for(17, 10, [7]), "MISSING_OP")
        self.assertEqual(diagnose.rule_for(1000, 10, [7]), "MAGNITUDE")
        self.assertIsNone(diagnose.rule_for(13.7, 10, [7]))
        self.assertIsNone(diagnose.rule_for(None, 10, [7]))
        self.assertIsNone(diagnose.rule_for(11, 10, [7], options_consecutive=True))
        self.assertIsNone(diagnose.rule_for(2, 5, [2, 9]))      # 2 is in the data, but too small to mean much

    def test_consecutive_options(self):
        self.assertTrue(diagnose.consecutive([10, 11, 12, 13, 14]))
        self.assertTrue(diagnose.consecutive([10, 11, 12, 13, 15]))
        self.assertFalse(diagnose.consecutive([10, 12, 13, 14, 20]))
        self.assertFalse(diagnose.consecutive([1, 2, None]))

    def test_messages_never_contain_a_number(self):
        for text in list(diagnose.MESSAGES.values()) + [diagnose.GENERIC]:
            self.assertEqual(numbers_in(text), [])


class HintCheckTests(unittest.TestCase):
    TEXT = "Anna has 3 bags with 4 apples in each bag and eats 2 apples. How many apples are left?"
    OPTIONS = {"A": "8", "B": "9", "C": "10", "D": "12", "E": "14"}

    def check(self, hint):
        return llmhint.check(hint, [self.TEXT], self.OPTIONS, "C")

    def test_good_hint_passes(self):
        self.assertEqual(self.check("First find how many apples are in all the bags."), (True, "ok"))

    def test_leaks(self):
        self.assertEqual(self.check("The bags hold 12 apples, so 10 apples are left.")[1], "leaks_value")
        self.assertEqual(self.check("Think about the apples: the answer is easy.")[1], "states_answer")
        self.assertEqual(self.check("Look at the apples and pick C) now.")[1], "leaks_letter")

    def test_a_number_of_the_problem_is_not_a_leak(self):
        self.assertTrue(self.check("Multiply the 3 bags by the 4 apples first.")[0])
        self.assertTrue(self.check("There are more than 100 ways to count apples.")[0])  # 100 is not 10

    def test_rejects_rubbish(self):
        self.assertEqual(self.check("")[1], "empty")
        self.assertEqual(self.check("word " * 60)[1], "too_long")
        self.assertEqual(self.check("Zebras enjoy quiet mornings.")[1], "off_topic")

    def test_clean(self):
        self.assertEqual(llmhint.clean('\n"Hint: Count the bags."\nMore text'), "Count the bags.")


class BuildTests(unittest.TestCase):
    """How the bank is built from the M3Kang files: what is shown as text, and the topics."""

    def test_clean_text(self):
        from copilot.tutor.textutil import clean_text
        self.assertEqual(clean_text("17. La Sara té 16 boles.  \nQuantes en té\n ara?"), "17. La Sara té 16 boles. Quantes en té ara?")

    def test_numeric_options_must_agree_between_the_two_ocr_readings(self):
        import tutor_build
        same = {"A": "4", "B": "5", "C": "16", "D": "17", "E": "21"}
        self.assertTrue(tutor_build.trusted_options(same, dict(same)))
        self.assertTrue(tutor_build.trusted_options({**same, "B": "3,5"}, {**same, "B": "3.5"}))
        self.assertFalse(tutor_build.trusted_options(same, {**same, "D": "1 17"}))   # one reading is wrong
        self.assertFalse(tutor_build.trusted_options({**same, "E": "#8"}, same))
        self.assertFalse(tutor_build.trusted_options({"A": "4", "B": "5"}, same))      # not five
        self.assertFalse(tutor_build.trusted_options(same, {}))                        # nothing to check against
        words = {"A": "dilluns", "B": "dimarts", "C": "dimecres", "D": "dijous", "E": "divendres"}
        self.assertTrue(tutor_build.trusted_options(words, {k: v + "x" for k, v in words.items()}))

    def build(self, problems, images=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = os.path.join(tmp.name, "p.jsonl")
        with open(data, "w", encoding="utf-8") as f:
            for p in problems:
                for language in ("eng", "cat"):
                    options = p.get(language, p["options"])
                    f.write(json.dumps({"id": p["id"], "language": language, "level": p.get("level", 1), "year": 2020,
                                        "text_only": p["text_only"], "text": p["text"], "options": options,
                                        "label": "C"}) + "\n")
        for name in images:
            open(os.path.join(tmp.name, name), "wb").close()
        path = os.path.join(tmp.name, "bank.db")
        subprocess.run([sys.executable, "tutor_build.py", "all", "--input", data, "--db", path, "--images", tmp.name,
                        "--fake-embed", "--classifier"], cwd=ROOT, check=True, capture_output=True)
        return path, tmp.name

    def test_text_or_scanned_problem(self):
        five = {"A": "10", "B": "12", "C": "13", "D": "14", "E": "15"}
        path, images = self.build([
            {"id": "lvl-1_2020_1", "text_only": True, "text": "1. How many apples are left?", "options": five},
            {"id": "lvl-1_2020_2", "text_only": False, "text": "2. Which piece completes the cube?",
             "options": {"A": "ALL", "B": "A△△O"}},
            {"id": "lvl-1_2020_3", "text_only": True, "text": "3. How many digits has the number?", "options": five,
             "cat": {**five, "D": "1 14"}},
            {"id": "lvl-1_2020_4", "text_only": False, "text": "4. No image for this one.", "options": {}},
        ], images=["lvl-1_2020_1_cat.png", "lvl-1_2020_2_cat.png", "lvl-1_2020_3_cat.png"])
        tutor = Tutor(path, images_dir=images, language="cat")
        self.addCleanup(tutor.db.close)
        first = tutor._public_problem("lvl-1_2020_1")
        self.assertEqual((first["mode"], first["options"]["C"], first["image"]), ("text", "13", "/img/lvl-1_2020_1_cat.png"))
        self.assertEqual(tutor._label("lvl-1_2020_1"), ("C", "13"))
        figure = tutor._public_problem("lvl-1_2020_2")
        self.assertEqual((figure["mode"], figure["options"]), ("image", {}))      # OCR's guess is never shown
        self.assertEqual(tutor._label("lvl-1_2020_2"), ("C", None))
        self.assertEqual(tutor._public_problem("lvl-1_2020_3")["mode"], "image")  # the two readings disagree
        shown = {r[0] for r in tutor.db.execute("SELECT id FROM problem_texts WHERE language = 'cat' AND display != ''")}
        self.assertNotIn("lvl-1_2020_4", shown)                                   # nothing to show
        self.assertFalse(tutor._model_may_speak("lvl-1_2020_2"))                  # the model can't see the figure
        diagnosed = {r[0] for r in tutor.db.execute("SELECT DISTINCT id FROM options")}
        self.assertEqual(diagnosed, {"lvl-1_2020_1"})                             # only options we are sure of

    def test_neighbours_fix_a_problem_in_the_wrong_topic(self):
        import tutor_build
        from copilot.tutor.db import connect, reset_content
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = connect(os.path.join(tmp.name, "t.db"))
        self.addCleanup(db.close)
        reset_content(db)
        ids = [f"p{i}" for i in range(12)]
        for i, pid in enumerate(ids):   # p0 says "speed", its neighbours say "words"; p11 has mixed neighbours
            db.execute("INSERT INTO problems (id, level, topic) VALUES (?, 1, ?)",
                       (pid, "speed" if i in (0, 11) else ("words" if i < 8 else "angles")))
        for rank, other in enumerate(ids[1:11]):
            db.execute("INSERT INTO neighbors VALUES ('p0', ?, ?, 0.8)", (rank, other))
            mixed = (ids[1:6] + ids[8:11] + ["p8", "p0"])[rank]       # 5 words, 4 angles, 1 speed
            db.execute("INSERT INTO neighbors VALUES ('p11', ?, ?, 0.8)", (rank, mixed))
        moved, _unsure = tutor_build.clean_topics(db)
        self.assertEqual(moved, 1)
        row = db.execute("SELECT topic, topic_source, topic_ok FROM problems WHERE id = 'p0'").fetchone()
        self.assertEqual(tuple(row), ("words", "neighbours", 1))                  # 7 of 10 neighbours said so
        row = db.execute("SELECT topic, topic_ok FROM problems WHERE id = 'p11'").fetchone()
        self.assertEqual(tuple(row), ("speed", 0))                                # nobody agrees: left out of mastery

    def test_copying_a_new_bank_keeps_the_students(self):
        from copilot.tutor.db import copy_bank
        five = {"A": "10", "B": "12", "C": "13", "D": "14", "E": "15"}
        problems = [{"id": f"lvl-1_2020_{i}", "text_only": True, "text": f"{i}. How many apples are left of {i}?",
                     "options": five} for i in range(1, 8)]
        old, images = self.build(problems)
        tutor = Tutor(old, images_dir=images, language="cat")
        student = tutor.start("Marta", 1)["student_id"]
        step = tutor.next(student)
        tutor.answer(step["attempt_id"], "C")
        tutor.db.close()
        new, new_images = self.build(problems + [{"id": "lvl-1_2020_9", "text_only": True,
                                                  "text": "9. How many pears are left?", "options": five}])
        demo = Tutor(new, images_dir=new_images, language="cat")     # a demo student made on the new bank
        guest = demo.start("Demo", 1)["student_id"]
        for _ in range(3):
            step = demo.next(guest)
            demo.answer(step["attempt_id"], "C")
        demo.db.close()
        self.assertEqual(copy_bank(new, old), 2)
        tutor = Tutor(old, images_dir=images, language="cat")
        self.addCleanup(tutor.db.close)
        self.assertEqual(tutor.profile(student)["done"], 1)                      # Marta kept her history
        self.assertEqual(tutor.start("Demo", 1)["done"], 3)                      # Demo came along, with theirs
        self.assertEqual(tutor.db.execute("SELECT COUNT(*) FROM problems").fetchone()[0], 8)
        self.assertEqual(copy_bank(new, old), 2)                                 # again: nobody is duplicated

    def test_a_bank_of_an_older_version_is_refused(self):
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "old.db")
        sqlite3.connect(path).close()
        with self.assertRaises(TutorError):
            Tutor(path)


class MatrixTests(unittest.TestCase):
    def test_idle_frame_is_a_kangaroo_that_never_flashes(self):
        self.assertEqual(len(matrix.idle()), 104)
        self.assertGreater(sum(1 for v in matrix.idle() if v), 25)

    def test_frames_have_104_values_in_range(self):
        frames = [matrix.tick(), matrix.cross(), matrix.wait(), matrix.blank(),
                  matrix.profile([(0.0, False), (0.5, False), (1.0, True)] * 4)]
        for frame in frames:
            self.assertEqual(len(frame), 104)
            self.assertTrue(all(0 <= v <= 7 for v in frame))

    def test_mastered_column_is_full(self):
        frame = matrix.profile([(1.0, True)])
        column = [frame[r * 13 + 6] for r in range(8)]
        self.assertEqual(column, [7] * 8)


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The bag-of-words vectors of the made-up bank aren't on bge-small's scale
        cls.saved = (S.MIN_SIM, S.DUP_SIM)
        S.MIN_SIM, S.DUP_SIM = 0.3, 0.999
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bank = os.path.join(cls.tmp.name, "bank.db")
        data = os.path.join(cls.tmp.name, "synthetic.jsonl")
        run = lambda *args: subprocess.run([sys.executable, *args], cwd=ROOT, check=True, capture_output=True)
        run("tutor_synthetic.py", "--out", data)
        run("tutor_build.py", "all", "--input", data, "--db", cls.bank, "--fake-embed", "--classifier",
            "--hand", data.replace(".jsonl", "_labels.csv"), "--images", cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        S.MIN_SIM, S.DUP_SIM = cls.saved
        cls.tmp.cleanup()

    def setUp(self):
        import shutil
        self.path = os.path.join(self.tmp.name, f"{self.id()}.db")
        shutil.copy(self.bank, self.path)
        self.model = FakeModel()
        self.tutor = Tutor(self.path, images_dir=self.tmp.name, language="cat", llm=self.model,
                           live_hints=True, warm_cache=False)
        self.student = self.tutor.start("Marta", 2)["student_id"]

    def tearDown(self):
        self.tutor.db.close()

    def label(self, step):
        return self.tutor.db.execute("SELECT label FROM problems WHERE id = ?", (step["problem"]["id"],)).fetchone()[0]

    def wrong(self, step, skip=""):
        return next(x for x in "ABCDE" if x != self.label(step) and x not in skip)

    def test_the_page_never_gets_the_label(self):
        step = self.tutor.next(self.student)
        self.assertNotIn("label", json.dumps(step))
        self.assertEqual(len(step["problem"]["options"]), 5)
        self.assertIn("topic", step)

    def test_right_first_time(self):
        step = self.tutor.next(self.student)
        result = self.tutor.answer(step["attempt_id"], self.label(step))
        self.assertTrue(result["correct_first"])
        self.assertEqual(result["score"], 1.0)
        self.assertGreater(result["topic"]["theta_change"], 0)
        self.assertEqual(result["profile"]["done"], 1)

    def test_wrong_then_second_try(self):
        step = self.tutor.next(self.student)
        first = self.tutor.answer(step["attempt_id"], self.wrong(step))
        self.assertTrue(first["retry"])
        self.assertNotIn("label", first)                       # no answer yet
        self.assertEqual(numbers_in(first["diagnosis"]["message"]), [])
        with self.assertRaises(TutorError):                    # the same wrong option again
            self.tutor.answer(step["attempt_id"], first["answer"])
        second = self.tutor.answer(step["attempt_id"], self.label(step))
        self.assertTrue(second["correct"])
        self.assertFalse(second["correct_first"])
        self.assertEqual(second["score"], S.GUESS)

    def test_two_wrong_answers_bring_an_easier_similar_problem(self):
        step = self.tutor.next(self.student)
        first = self.wrong(step)
        self.tutor.answer(step["attempt_id"], first)
        result = self.tutor.answer(step["attempt_id"], self.wrong(step, skip=first))
        self.assertFalse(result["correct"])
        self.assertLess(result["topic"]["theta_change"], 0)
        b = lambda pid: self.tutor.db.execute("SELECT b FROM problems WHERE id = ?", (pid,)).fetchone()[0]
        repair = self.tutor.next(self.student)
        self.assertTrue(repair["is_repair"])
        self.assertLess(b(repair["problem"]["id"]), b(step["problem"]["id"]))

    def test_next_returns_the_open_problem(self):
        step = self.tutor.next(self.student)
        self.assertEqual(self.tutor.next(self.student)["attempt_id"], step["attempt_id"])

    def test_hint_ladder_in_order_and_never_the_answer_early(self):
        step = self.tutor.next(self.student)
        label = self.label(step)
        value = step["problem"]["options"][label]
        kinds = []
        for _ in range(S.MAX_RUNG):
            hint = self.tutor.hint(step["attempt_id"])
            if hint.get("busy"):
                for _ in range(200):
                    status = self.tutor.status(step["attempt_id"])
                    if not status["busy"]:
                        break
                    import time
                    time.sleep(0.01)
                hint = dict(status, kind="model")
            kinds.append(hint["kind"])
            if hint["kind"] == "answer":
                self.assertEqual(hint["label"], label)
                self.assertFalse(hint["result"]["correct"])
                break
            if hint["kind"] in ("understand", "strategy", "discard", "model"):
                self.assertNotIn(f'"{value}"', json.dumps([hint.get("text"), hint.get("title")]))
        self.assertEqual(kinds, ["understand", "strategy", "easier_example", "discard", "model", "answer"])
        self.assertEqual(self.model.generated, 1)
        with self.assertRaises(TutorError):
            self.tutor.hint(step["attempt_id"])

    def test_hints_lower_the_score(self):
        step = self.tutor.next(self.student)
        self.tutor.hint(step["attempt_id"])
        self.tutor.hint(step["attempt_id"])
        result = self.tutor.answer(step["attempt_id"], self.label(step))
        self.assertAlmostEqual(result["score"], 0.6)

    def test_related_hint_uses_a_problem_the_student_solved(self):
        solved = set()
        for _ in range(40):                                    # build some history first
            step = self.tutor.next(self.student)
            self.tutor.answer(step["attempt_id"], self.label(step))
            solved.add(step["problem"]["id"])
        for _ in range(30):
            step = self.tutor.next(self.student)
            self.tutor.hint(step["attempt_id"])
            self.tutor.hint(step["attempt_id"])
            hint = self.tutor.hint(step["attempt_id"])
            if hint["kind"] == "solved_before":
                self.assertIn(hint["problem"]["id"], solved)
                self.assertNotEqual(hint["problem"]["id"], step["problem"]["id"])
                return
            self.tutor.answer(step["attempt_id"], self.label(step))
        self.fail("no hint ever pointed at a problem the student had solved")

    def test_rejected_model_hint_is_not_shown_and_not_charged(self):
        self.model.text = "La resposta és molt fàcil."
        step = self.tutor.next(self.student)
        for _ in range(4):
            self.tutor.hint(step["attempt_id"])
        self.assertTrue(self.tutor.hint(step["attempt_id"])["busy"])
        import time
        for _ in range(200):
            status = self.tutor.status(step["attempt_id"])
            if not status["busy"]:
                break
            time.sleep(0.01)
        self.assertIsNone(status["text"])
        self.assertTrue(status["rejected"])
        used = self.tutor.db.execute("SELECT hints_used FROM attempts WHERE attempt_id = ?",
                                     (step["attempt_id"],)).fetchone()[0]
        self.assertEqual(used, 4)

    def test_no_model_skips_the_model_rung(self):
        tutor = Tutor(self.path, images_dir=self.tmp.name, language="cat", live_hints=False)
        student = tutor.start("Pau", 0)["student_id"]
        step = tutor.next(student)
        kinds = []
        while not kinds or kinds[-1] != "answer":
            kinds.append(tutor.hint(step["attempt_id"])["kind"])
        self.assertLessEqual(len(kinds), 5)
        self.assertNotIn("model", kinds)
        tutor.db.close()

    def test_discard_is_recorded_and_judged_only_at_the_end(self):
        step = self.tutor.next(self.student)
        label = self.label(step)
        marked = self.tutor.discard(step["attempt_id"], label)
        self.assertEqual(marked, {"discarded": [label]})       # no verdict now: that would leak
        result = self.tutor.answer(step["attempt_id"], label)
        self.assertTrue(result["discarded_correct"])

    def test_never_the_same_problem_twice_and_topics_interleave(self):
        seen, topics = [], []
        for _ in range(60):
            step = self.tutor.next(self.student)
            seen.append(step["problem"]["id"])
            topics.append(step["topic"]["key"])
            self.tutor.answer(step["attempt_id"], self.label(step))
        self.assertEqual(len(seen), len(set(seen)))
        runs = max(len(list(group)) for _key, group in __import__("itertools").groupby(topics))
        self.assertLessEqual(runs, S.MAX_IN_A_ROW)

    def test_a_strong_student_masters_topics_and_they_come_back_less(self):
        for _ in range(120):
            step = self.tutor.next(self.student)
            self.tutor.answer(step["attempt_id"], self.label(step))
        states = [t["state"] for t in self.tutor.profile(self.student)["topics"]]
        self.assertGreaterEqual(states.count("mastered"), 8)
        reviews = self.tutor.db.execute("SELECT COUNT(*) FROM attempts WHERE is_review = 1").fetchone()[0]
        self.assertGreater(reviews, 0)

    def test_matrix_frame_follows_the_student(self):
        self.assertEqual(len(self.tutor.frame()), 104)
        step = self.tutor.next(self.student)
        self.tutor.answer(step["attempt_id"], self.label(step))
        self.assertEqual(self.tutor.frame(), matrix.tick())    # a tick right after a good answer

    def test_twins_are_never_hints_nor_served_twice(self):
        # Make two problems "the same" (as when one question appears at two levels)
        first = self.tutor.next(self.student)
        twin = self.tutor.db.execute("SELECT neighbor_id FROM neighbors WHERE id = ? AND rank = 0",
                                     (first["problem"]["id"],)).fetchone()[0]
        self.tutor.db.execute("UPDATE neighbors SET sim = 0.999 WHERE (id = ? AND neighbor_id = ?) "
                              "OR (id = ? AND neighbor_id = ?)", (first["problem"]["id"], twin, twin, first["problem"]["id"]))
        self.tutor.db.commit()
        self.tutor.answer(first["attempt_id"], self.label(first))
        for _ in range(80):
            step = self.tutor.next(self.student)
            self.assertNotEqual(step["problem"]["id"], twin)
            self.tutor.answer(step["attempt_id"], self.label(step))

    def test_level_above_five_is_never_served(self):
        for _ in range(60):
            step = self.tutor.next(self.student)
            self.assertLessEqual(step["problem"]["level"], S.MAX_LEVEL)
            self.tutor.answer(step["attempt_id"], self.label(step))

    def test_a_young_student_only_gets_topics_with_problems_near_their_grade(self):
        # Take one topic away from the lower grades, as "Angles" in M3Kang
        self.tutor.db.execute("UPDATE problems SET topic_ok = 0 WHERE topic = 'algebra' AND level <= 3")
        self.tutor.db.commit()
        young = self.tutor.start("Nil", 0)
        self.assertNotIn("algebra", [t["topic"] for t in young["topics"]])
        self.assertEqual(len(young["topics"]), 9)
        self.assertEqual(len(young["matrix"]), 104)
        for _ in range(40):
            step = self.tutor.next(young["student_id"])
            self.assertNotEqual(step["topic"]["key"], "algebra")
            self.assertLessEqual(step["problem"]["level"], 0 + S.LEVELS_ABOVE)
            first = self.wrong(step)
            self.tutor.answer(step["attempt_id"], first)
            self.tutor.answer(step["attempt_id"], self.wrong(step, skip=first))   # fails: repair problems too

    def test_a_stored_hint_is_shown_without_the_model(self):
        tutor = Tutor(self.path, images_dir=self.tmp.name, language="cat", live_hints=False)
        self.addCleanup(tutor.db.close)
        student = tutor.start("Ona", 2)["student_id"]
        step = tutor.next(student)
        tutor.db.execute("INSERT INTO hints VALUES (?, 'cat', 'first_step', 'Compta primer les bosses.', 1, 'ok', 5.0)",
                         (step["problem"]["id"],))
        tutor.db.commit()
        hints = []
        while not hints or hints[-1]["kind"] != "answer":
            hints.append(tutor.hint(step["attempt_id"]))
        model = [h for h in hints if h["kind"] == "model"]
        self.assertEqual([h["text"] for h in model], ["Compta primer les bosses."])
        self.assertEqual([h["last"] for h in hints[-2:]], [True, True])           # the page warns before the answer

    def test_no_student_no_profile_a_kangaroo(self):
        fresh = Tutor(self.path, images_dir=self.tmp.name, language="cat")
        self.addCleanup(fresh.db.close)
        self.assertEqual(fresh.frame(), matrix.idle())

    def test_same_name_resumes_the_same_student(self):
        self.assertEqual(self.tutor.start("Marta", 5)["student_id"], self.student)
        self.assertEqual(self.tutor.start("Marta", 5)["level"], 2)


if __name__ == "__main__":
    unittest.main()

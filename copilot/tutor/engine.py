"""The adaptive engine: an Elo rating per topic, with a guessing floor.

Pure functions, no database and no model, so the simulator and the tests can
run them anywhere. tutor/service.py stores what these functions return.
"""
import math

from . import settings as S

STATES = ("new", "learning", "consolidating", "mastered")
WEIGHTS = {"new": 3.0, "learning": 4.0, "consolidating": 2.0, "mastered": 0.0}
REVIEW_WEIGHT = 3.0


def initial_b(level, band):
    """Difficulty of a problem before anyone has answered it. Level 0 to 7, band 1 to 3."""
    return 1000.0 + 120.0 * level + 80.0 * (band - 1)


def band_of(qnum, qmax):
    """Kangaroo papers have three equal parts worth 3, 4 and 5 points."""
    if not qnum or not qmax:
        return 2
    return min(3, max(1, math.ceil(3 * qnum / qmax)))


def initial_theta(level):
    return 1000.0 + 120.0 * level


def reference_b(level):
    """A band-2 problem of the student's own grade: the yardstick for mastery."""
    return initial_b(level, 2)


def p_correct(theta, b):
    """Chance of a right answer. Never below GUESS: with five options, luck gives 20%."""
    return S.GUESS + (1.0 - S.GUESS) / (1.0 + 10.0 ** ((b - theta) / 400.0))


def target_b(theta, p=None):
    """The difficulty at which this student succeeds with probability p."""
    p = S.TARGET_P if p is None else p
    return theta + 400.0 * math.log10((1.0 - S.GUESS) / (p - S.GUESS) - 1.0)


def score(correct_first, correct_final, hints):
    """1 for a clean first answer, less with hints, 0.2 (a guess) for a second try."""
    if correct_first:
        return max(1.0 - S.HINT_PENALTY * hints, S.HINT_FLOOR)
    return S.GUESS if correct_final else 0.0


def k_factor(n_attempts):
    """Large while we know little about the student, then it settles."""
    return S.K_BASE + S.K_EXTRA / (1.0 + S.K_DECAY * n_attempts)


def update_theta(theta, b, s, n_attempts):
    return theta + k_factor(n_attempts) * (s - p_correct(theta, b))


def is_clean(correct_first, hints):
    """A right first answer with at most one hint counts as knowing it."""
    return bool(correct_first) and hints <= 1


def mastery_theta(level):
    """The ability at which a student passes the reference problem with MASTERY_P."""
    return reference_b(level) - (target_b(0.0, S.MASTERY_P))


def progress(theta, level):
    """0 to 1: how close the topic is to mastery. Used for the bars and the LED matrix.

    A new student starts at about a fifth of the way, and reaches 1 at mastery_theta.
    """
    start = initial_theta(level) - 60.0
    return min(1.0, max(0.0, (theta - start) / (mastery_theta(level) - start)))


def next_state(topic, clean, correct_first, n_done, level):
    """Update one student_topic row (a dict) after an attempt. theta is already updated.

    n_done is the number of problems the student has finished, this one included:
    reviews are counted in problems, not days, because sessions are short.
    """
    topic = dict(topic)
    was_mastered = topic["state"] == "mastered"
    topic["n_attempts"] += 1
    topic["recent"] = (topic["recent"] + ("1" if clean else "0"))[-4:]

    if was_mastered:
        if clean:  # review passed: wait twice as long before the next one
            topic["review_interval"] = min(S.REVIEW_MAX, 2 * (topic["review_interval"] or S.REVIEW_FIRST))
            topic["review_due_at"] = n_done + topic["review_interval"]
        else:      # forgotten: back to practice
            topic["state"] = "consolidating"
            topic["review_interval"] = topic["review_due_at"] = None
        return topic

    mastered = (topic["n_attempts"] >= S.MIN_ATTEMPTS
                and topic["recent"].count("1") >= 3
                and p_correct(topic["theta"], reference_b(level)) >= S.MASTERY_P)
    if mastered:
        topic["state"] = "mastered"
        topic["review_interval"] = S.REVIEW_FIRST
        topic["review_due_at"] = n_done + S.REVIEW_FIRST
    elif topic["n_attempts"] < S.MIN_ATTEMPTS or not correct_first:
        topic["state"] = "learning"
    else:
        topic["state"] = "consolidating"
    return topic


def topic_weight(topic, n_done):
    if topic["state"] == "mastered":
        due = topic["review_due_at"] is not None and n_done >= topic["review_due_at"]
        return REVIEW_WEIGHT if due else 0.0
    return WEIGHTS[topic["state"]]


def choose_topic(topics, n_done, last_topics, rng):
    """Pick the next topic. topics: student_topic rows; last_topics: most recent last.

    Weak topics come up more often, mastered ones only when a review is due,
    and never more than MAX_IN_A_ROW of the same topic.
    """
    weights = {t["topic"]: topic_weight(t, n_done) for t in topics}
    tail = last_topics[-S.MAX_IN_A_ROW:]
    if len(tail) == S.MAX_IN_A_ROW and len(set(tail)) == 1 and len(weights) > 1:
        weights[tail[0]] = 0.0
    if not any(weights.values()):
        # Everything is mastered and nothing is due: review the one due soonest
        waiting = [t for t in topics if t["state"] == "mastered" and weights.get(t["topic"]) is not None
                   and not (len(tail) == S.MAX_IN_A_ROW and tail[0] == t["topic"] and len(set(tail)) == 1)]
        waiting = waiting or list(topics)
        return min(waiting, key=lambda t: (t["review_due_at"] or 0, t["topic"]))["topic"]
    names = sorted(weights)
    return rng.choices(names, weights=[weights[n] for n in names], k=1)[0]

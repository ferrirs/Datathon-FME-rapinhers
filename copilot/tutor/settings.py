"""Tutor settings. Every value can be overridden in config.env or the environment."""
import os

from ..config import CONFIG, ROOT


def _get(key, default):
    return os.environ.get(key, CONFIG.get(key, default))


def _path(key, default):
    value = _get(key, default)
    return value if os.path.isabs(value) else os.path.join(ROOT, value)


DB_PATH = _path("TUTOR_DB", "data/tutor.db")
IMAGES_DIR = _path("TUTOR_IMAGES", "data/images")
PORT = int(_get("TUTOR_PORT", "8090"))
LANGUAGE = _get("TUTOR_LANGUAGE", "cat")          # language shown to the student
VECTOR_LANGUAGE = "eng"                           # bge-small is an English model
HINT_LANGUAGE = _get("TUTOR_HINT_LANGUAGE", "Catalan")   # language the model writes hints in
SEED = int(CONFIG.get("SEED", "42"))

# Adaptive engine
GUESS = 0.2             # five options
TARGET_P = 0.70         # expected success of the problem we pick
MASTERY_P = float(_get("TUTOR_MASTERY_P", "0.70"))   # needed on a reference problem of the student's grade
MIN_ATTEMPTS = 5        # evidence needed before a topic can be mastered
REVIEW_FIRST = 6        # first review, in problems done after mastering
REVIEW_MAX = 48
MAX_IN_A_ROW = 3        # interleaving: never more of the same topic in a row
SHARE = float(_get("TUTOR_SHARE", "0.5"))        # how much one topic's news moves the untested ones
K_BASE = float(_get("TUTOR_K_BASE", "32"))
K_EXTRA = float(_get("TUTOR_K_EXTRA", "96"))
K_DECAY = float(_get("TUTOR_K_DECAY", "0.2"))
MAX_LEVEL = int(_get("TUTOR_MAX_LEVEL", "5"))      # levels shown to students: 0-5 = 5è primària to 4t ESO
# bge-small similarities between Kangaroo problems are high: the median nearest neighbour is 0.83.
# Measured on 911 English problems: at 0.75, 80% have an easier similar problem, 80% of the same topic.
MIN_SIM = float(_get("TUTOR_MIN_SIM", "0.75"))     # a "similar problem" hint needs at least this similarity
# Some problems appear at several levels with the same text (15 groups in M3Kang). Above this
# similarity two problems count as the same one: never shown as a hint, never served twice.
DUP_SIM = float(_get("TUTOR_DUP_SIM", "0.95"))
TEMES_PATH = _path("TUTOR_TEMES", "data/temes.json")   # the team's topics; if present, they replace the classifier
MIN_TOPIC_MARGIN = float(_get("TUTOR_MIN_TOPIC_MARGIN", "0.03"))   # classifier: margin over the second topic
# Team topics come from k-means, which leaves some problems in the wrong group. We look at the
# 10 nearest neighbours of each problem: with 6 or more in one other topic, the problem moves
# there; with fewer than 3 in its own, it doesn't count towards mastery.
TOPIC_NEIGHBOURS = 10
TOPIC_MOVE = 6
MIN_TOPIC_AGREE = float(_get("TUTOR_MIN_TOPIC_AGREE", "0.3"))
MIN_TOPIC_PROBLEMS = 4  # a student only gets a topic with this many problems near their grade
LEVELS_ABOVE = 2        # never a problem more than two grades above the student's
K_PROBLEM = float(_get("TUTOR_K_PROBLEM", "0"))   # >0 lets problem difficulty learn from answers

# Hints
MAX_RUNG = 6
HINT_PENALTY = 0.2
HINT_FLOOR = 0.4
HINT_MAX_TOKENS = 40
HINT_MAX_WORDS = 40
# The App Lab app runs in a container that can't reach the model servers (they listen on the
# board's 127.0.0.1 only), so by default the tutor only shows hints stored in the bank by
# tutor_hints.py. Set TUTOR_LIVE_HINTS=1 where the model is reachable, to write hints on the spot.
LIVE_HINTS = _get("TUTOR_LIVE_HINTS", "0") == "1"
WARM_CACHE = _get("TUTOR_WARM_CACHE", "1") == "1"
LLM_HOST = _get("TUTOR_LLM_HOST", "127.0.0.1")

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
MASTERY_P = float(_get("TUTOR_MASTERY_P", "0.75"))   # needed on a reference problem of the student's grade
MIN_ATTEMPTS = 5        # evidence needed before a topic can be mastered
REVIEW_FIRST = 6        # first review, in problems done after mastering
REVIEW_MAX = 48
MAX_IN_A_ROW = 3        # interleaving: never more of the same topic in a row
SHARE = float(_get("TUTOR_SHARE", "0.5"))        # how much one topic's news moves the untested ones
K_BASE = float(_get("TUTOR_K_BASE", "24"))
K_EXTRA = float(_get("TUTOR_K_EXTRA", "96"))
K_DECAY = float(_get("TUTOR_K_DECAY", "0.2"))
MIN_TOPIC_MARGIN = float(_get("TUTOR_MIN_TOPIC_MARGIN", "0.03"))
K_PROBLEM = float(_get("TUTOR_K_PROBLEM", "0"))   # >0 lets problem difficulty learn from answers

# Hints
MAX_RUNG = 6
HINT_PENALTY = 0.2
HINT_FLOOR = 0.4
HINT_MAX_TOKENS = 40
HINT_MAX_WORDS = 40
WARM_CACHE = _get("TUTOR_WARM_CACHE", "1") == "1"
LIVE_HINTS = _get("TUTOR_LIVE_HINTS", "1") == "1"

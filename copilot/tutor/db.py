"""The tutor database: one SQLite file, data/tutor.db.

It holds M3Kang text, so it must never be committed (.gitignore excludes *.db).
The official retrieval index, data/index.db, is a different file and only has
training problems. The tutor may use every problem: it never scores the model.
"""
import sqlite3

SCHEMA = """
-- Content: built once by tutor_build.py, then read-only
CREATE TABLE IF NOT EXISTS problems (
    id TEXT PRIMARY KEY,            -- 'lvl-0_2015_13', the same in every language
    level INTEGER, year INTEGER, qnum INTEGER, band INTEGER,
    text_only INTEGER, label TEXT,
    topic TEXT, topic_margin REAL DEFAULT 0, topic_source TEXT DEFAULT '',
    b REAL                          -- difficulty, Elo scale
);
CREATE INDEX IF NOT EXISTS problems_by_topic ON problems (topic, b);
CREATE TABLE IF NOT EXISTS problem_texts (
    id TEXT, language TEXT, text TEXT,
    options TEXT,                   -- JSON {"A": "12", ...}, or '{}' when OCR found none
    image TEXT,                     -- file name inside the images folder, or NULL
    servable INTEGER,               -- 1 when a student can answer it (options or image)
    PRIMARY KEY (id, language)
);
CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, vec BLOB);
CREATE TABLE IF NOT EXISTS neighbors (
    id TEXT, rank INTEGER, neighbor_id TEXT, sim REAL,
    PRIMARY KEY (id, rank)
);
CREATE INDEX IF NOT EXISTS neighbors_by_neighbor ON neighbors (neighbor_id);
CREATE TABLE IF NOT EXISTS options (
    id TEXT, letter TEXT, raw TEXT, value REAL,
    is_correct INTEGER, misconception TEXT,
    PRIMARY KEY (id, letter)
);
CREATE TABLE IF NOT EXISTS hints (
    id TEXT, language TEXT, kind TEXT,      -- kind: 'first_step'
    text TEXT, passed INTEGER, reason TEXT, seconds REAL,
    PRIMARY KEY (id, language, kind)
);

-- Student state: written during a session
CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY, name TEXT UNIQUE, level INTEGER,
    n_done INTEGER DEFAULT 0, repair_for TEXT, last_topics TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS student_topic (
    student_id INTEGER, topic TEXT, theta REAL,
    n_attempts INTEGER DEFAULT 0, recent TEXT DEFAULT '',
    state TEXT DEFAULT 'new', review_interval INTEGER, review_due_at INTEGER,
    PRIMARY KEY (student_id, topic)
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id INTEGER PRIMARY KEY, student_id INTEGER, problem_id TEXT, topic TEXT,
    status TEXT DEFAULT 'open',     -- open, retry, done
    started_at REAL, finished_at REAL,
    first_answer TEXT, final_answer TEXT, tries INTEGER DEFAULT 0,
    rung INTEGER DEFAULT 0, hints_used INTEGER DEFAULT 0, discarded TEXT DEFAULT '',
    correct_first INTEGER, correct_final INTEGER, score REAL,
    p_expected REAL, theta_before REAL, theta_after REAL,
    is_review INTEGER DEFAULT 0, is_repair INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS attempts_by_student ON attempts (student_id, problem_id);
CREATE TABLE IF NOT EXISTS hint_events (
    attempt_id INTEGER, rung INTEGER, kind TEXT, ref_problem_id TEXT, shown_at REAL
);
"""

CONTENT_TABLES = ("problems", "problem_texts", "vectors", "neighbors", "options")


def connect(path, check_same_thread=True):
    db = sqlite3.connect(path, check_same_thread=check_same_thread)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db

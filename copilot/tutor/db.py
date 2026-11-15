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
    topic_ok INTEGER DEFAULT 1,     -- 0: too unsure of its topic to count towards mastery
    b REAL                          -- difficulty, Elo scale
);
CREATE INDEX IF NOT EXISTS problems_by_topic ON problems (topic, b);
CREATE TABLE IF NOT EXISTS problem_texts (
    id TEXT, language TEXT, text TEXT,
    options TEXT,                   -- JSON {"A": "12", ...} as OCR read them, or '{}'
    image TEXT,                     -- file name inside the images folder, or NULL
    display TEXT,                   -- how the student sees it: 'text', 'image', or '' (can't be shown)
    PRIMARY KEY (id, language)
);
CREATE TABLE IF NOT EXISTS topics (
    key TEXT PRIMARY KEY, position INTEGER, name TEXT, short TEXT,
    needs_image INTEGER, methods TEXT              -- JSON list of sentences, the strategy rung
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

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

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

CONTENT_TABLES = ("problems", "problem_texts", "vectors", "neighbors", "options", "topics")
SCHEMA_VERSION = 3


def connect(path, check_same_thread=True):
    db = sqlite3.connect(path, check_same_thread=check_same_thread)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def is_current(db):
    """False for a bank built by an older version of tutor_build.py: build it again."""
    return db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def reset_content(db):
    """Drop the problem bank and create it again, empty.

    Students and their history stay. So do the vectors: they take the longest to compute,
    and they only depend on the English text.
    """
    for table in CONTENT_TABLES:
        if table != "vectors":
            db.execute(f"DROP TABLE IF EXISTS {table}")
    db.executescript(SCHEMA)
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()


def copy_bank(source, target):
    """Put the problem bank of one file into another, and keep the students of the other.

    board/install_app.sh uses it: the bank is built in data/tutor.db, and the App Lab app
    has its own copy, with the students who practised on it. Students of the source that
    the target doesn't know by name come along too: that's how the demo student gets in.
    Returns the number of students in the target.
    """
    db = connect(target)
    db.execute("ATTACH DATABASE ? AS new", (source,))
    for table in CONTENT_TABLES + ("hints", "meta"):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    db.executescript(SCHEMA)
    for table in CONTENT_TABLES + ("hints", "meta"):
        db.execute(f"INSERT INTO {table} SELECT * FROM new.{table}")

    attempt_columns = [r["name"] for r in db.execute("PRAGMA table_info(attempts)")
                       if r["name"] not in ("attempt_id", "student_id")]
    columns = ", ".join(attempt_columns)
    newcomers = db.execute("SELECT * FROM new.students WHERE name NOT IN (SELECT name FROM students)").fetchall()
    for student in newcomers:
        new_id = db.execute(
            "INSERT INTO students (name, level, n_done, repair_for, last_topics, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (student["name"], student["level"], student["n_done"], student["repair_for"],
             student["last_topics"], student["created_at"])).lastrowid
        db.execute(
            """INSERT INTO student_topic SELECT ?, topic, theta, n_attempts, recent, state, review_interval, review_due_at
               FROM new.student_topic WHERE student_id = ?""", (new_id, student["student_id"]))
        db.execute(f"INSERT INTO attempts (student_id, {columns}) SELECT ?, {columns} FROM new.attempts "
                   "WHERE student_id = ? ORDER BY attempt_id", (new_id, student["student_id"]))
    db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()
    db.execute("DETACH DATABASE new")
    students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    db.close()
    return students

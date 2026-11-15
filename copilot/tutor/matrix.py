"""Frames for the 8x13 LED matrix: lists of 104 brightness values, 0 to 7, row by row.

Everything shown is decided here, in Python. The sketch only draws the frame.
Nothing flashes: a tick or a cross stays for a moment, then the profile comes back.
"""
ROWS, COLS = 8, 13
ON, DIM = 7, 2

TICK = [".............",
        "...........#.",
        "..........#..",
        ".........#...",
        "..#.....#....",
        "...#...#.....",
        "....#.#......",
        ".....#......."]
CROSS = [".............",
         "...#.....#...",
         "....#...#....",
         ".....#.#.....",
         "......#......",
         ".....#.#.....",
         "....#...#....",
         "...#.....#..."]
WAIT = [".............",
        ".....###.....",
        "....#...#....",
        "........#....",
        ".......#.....",
        "......#......",
        ".............",
        "......#......"]


KANGAROO = ["........#.#..",
            "........###..",
            "........####.",
            ".......###...",
            "......####.#.",
            "#....#####...",
            ".########....",
            "......#####.."]


def blank():
    return [0] * (ROWS * COLS)


def from_art(art, level=ON):
    frame = blank()
    for row, line in enumerate(art[:ROWS]):
        for col, char in enumerate(line[:COLS]):
            if char == "#":
                frame[row * COLS + col] = level
    return frame


def profile(columns):
    """One bar per topic, growing from the bottom. columns: [(progress 0..1, mastered)].

    A mastered topic is a full, bright column. The others are dimmer, so the
    jury can tell them apart from across the room.
    """
    frame = blank()
    columns = columns[:COLS]
    offset = (COLS - len(columns)) // 2
    for i, (value, mastered) in enumerate(columns):
        height = ROWS if mastered else min(ROWS - 1, int(round(value * (ROWS - 1))))
        for h in range(height):
            frame[(ROWS - 1 - h) * COLS + offset + i] = ON if mastered else DIM + 2
        if height == 0:
            frame[(ROWS - 1) * COLS + offset + i] = 1  # a faint dot: the topic exists
    return frame


def tick():
    return from_art(TICK)


def cross():
    return from_art(CROSS)


def wait():
    return from_art(WAIT, level=4)


def idle():
    """A kangaroo, while nobody is practising."""
    return from_art(KANGAROO, level=5)

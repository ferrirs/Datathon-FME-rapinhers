"""Cangur Tutor, the App Lab app: the web page, its API, and the LED matrix.

The web_ui brick serves assets/ (the page, its fonts and the problem images) on
port 7000, and the routes below call the tutor in this same process. A loop
sends the tutor's current frame to the sketch, which draws it on the 8x13 matrix.

App Lab runs this file in a container that only sees the app folder (as /app).
So don't copy files by hand: board/install_app.sh puts the tutor code,
config.env, the problem bank and the images where this file expects them.
Then start the app from App Lab and open http://<board-ip>:7000, or over USB:

    adb forward tcp:7000 tcp:7000   ->   http://127.0.0.1:7000

From the container, the model servers of the board can't be reached: they
listen on the board's 127.0.0.1 only. The tutor doesn't need them. Every hint
comes from the bank, where tutor_hints.py stored the ones that passed the checks.

The routes are the same as in tutor_server.py, so the page works with both.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # copilot/ was copied here by board/install_app.sh

import numpy as np  # noqa: E402
from arduino.app_bricks.web_ui import WebUI  # noqa: E402
from arduino.app_utils import App, Bridge, Frame  # noqa: E402

from copilot.tutor import llmhint  # noqa: E402
from copilot.tutor import settings as S  # noqa: E402
from copilot.tutor.service import Tutor, TutorError  # noqa: E402

LIVE = S.LIVE_HINTS and llmhint.reachable()
TUTOR = Tutor(os.path.join(HERE, "data", "tutor.db"), live_hints=LIVE)
print(f"Cangur Tutor: problems in '{TUTOR.language}', {len(TUTOR.available)} topics")
print("Model hints: stored ones" + (", and written on the spot when none is stored" if LIVE else " only"))


def run(function):
    """Call the tutor. A TutorError becomes {"error": ...}, which the page shows to the student."""
    try:
        return function()
    except TutorError as error:
        return {"error": str(error)}
    except (KeyError, ValueError) as error:
        return {"error": f"Petició no vàlida: {error}"}


# Plain functions with typed parameters: web_ui (FastAPI) reads their signatures to
# fill in the path parameters, so don't wrap them in a decorator.
def start(name: str, level: str):
    return run(lambda: TUTOR.start(name, int(level)))


def next_problem(student: str):
    return run(lambda: TUTOR.next(int(student)))


def profile(student: str):
    return run(lambda: TUTOR.profile(int(student)))


def hint(attempt: str):
    return run(lambda: TUTOR.hint(int(attempt)))


def status(attempt: str):
    return run(lambda: TUTOR.status(int(attempt)))


def answer(attempt: str, letter: str):
    return run(lambda: TUTOR.answer(int(attempt), letter))


def discard(attempt: str, letter: str):
    return run(lambda: TUTOR.discard(int(attempt), letter))


def health():
    return {"status": "ok", "language": TUTOR.language, "topics": TUTOR.available}


ui = WebUI()
ui.expose_api("GET", "/api/start/{name}/{level}", start)
ui.expose_api("GET", "/api/next/{student}", next_problem)
ui.expose_api("GET", "/api/profile/{student}", profile)
ui.expose_api("GET", "/api/hint/{attempt}", hint)
ui.expose_api("GET", "/api/status/{attempt}", status)
ui.expose_api("GET", "/api/answer/{attempt}/{letter}", answer)
ui.expose_api("GET", "/api/discard/{attempt}/{letter}", discard)
ui.expose_api("GET", "/api/health", health)

last_frame = None


def loop():
    """Send the tutor's frame to the matrix when it changes, about three times a second at most.

    Nothing here may raise: an exception in this loop stops the whole app.
    """
    global last_frame
    try:
        frame = TUTOR.frame()
        if frame != last_frame:
            grid = np.array(frame, dtype=np.uint8).reshape(8, 13)
            Bridge.call("draw", Frame(grid).to_board_bytes())
            last_frame = frame
    except Exception as error:  # noqa: BLE001 - the sketch may not be ready yet: try again
        print(f"LED matrix: {error}")
        time.sleep(2)
    time.sleep(0.3)


App.run(user_loop=loop)

"""Cangur matrix: the LED matrix half of Cangur Tutor.

The tutor itself runs outside App Lab (tutor_server.py, port 8090) and decides
what the matrix shows: one bar per topic, a tick, a cross, or a question mark
while the model writes. This app only asks for the current frame a few times a
second and passes it to the sketch.

Not tested on a board yet. Check first that this app can reach the tutor:
its log should not say "tutor unreachable". If App Lab runs this code in a
container where 127.0.0.1 is not the board, start the tutor with
--host 0.0.0.0 and put the board's address in TUTOR_URL below.
"""
import json
import time
import urllib.request

import numpy as np
from arduino.app_utils import App, Bridge, Frame

TUTOR_URL = "http://127.0.0.1:8090/api/matrix"
last = None
warned = False


def loop():
    global last, warned
    try:
        with urllib.request.urlopen(TUTOR_URL, timeout=2) as response:
            frame = json.loads(response.read())["frame"]
        warned = False
    except (OSError, ValueError, KeyError) as error:
        if not warned:
            print(f"tutor unreachable at {TUTOR_URL}: {error}")
            warned = True
        frame = None
    if frame is not None and frame != last:
        grid = np.array(frame, dtype=np.uint8).reshape(8, 13)
        Bridge.call("draw", Frame(grid).to_board_bytes())
        last = frame
    time.sleep(0.3)  # about three frames a second: nothing on the matrix flashes faster


App.run(user_loop=loop)

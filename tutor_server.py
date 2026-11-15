#!/usr/bin/env python3
"""Cangur Tutor without App Lab: the same page and the same API, on port 8090.

    python3 tutor_server.py                        # data/tutor.db
    python3 tutor_server.py --host 0.0.0.0         # open it to the network
    python3 tutor_server.py --db data/tutor_synth.db

For a laptop, or for a board where App Lab gives trouble on demo day. The
interface of the demo is the App Lab app in app/cangur-tutor, which adds the
LED matrix: board/install_app.sh sets it up.

Open http://127.0.0.1:8090. From a laptop, over USB and with Wi-Fi off:

    adb forward tcp:8090 tcp:8090

Standard library only.
"""
import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from copilot.tutor import llmhint
from copilot.tutor import settings as S
from copilot.tutor.service import Tutor, TutorError
from copilot.tutor.textutil import utf8_console

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tutor_web")
TUTOR = None


def api(path):
    """/api/<action>/<arg>/...: the same routes as the App Lab app. Every answer is JSON."""
    parts = [unquote(p) for p in path.strip("/").split("/")[1:]]
    action, args = (parts[0], parts[1:]) if parts else ("", [])
    if action == "start" and len(args) == 2:
        return TUTOR.start(args[0], args[1])
    if action in ("next", "profile", "hint", "status") and len(args) == 1:
        return getattr(TUTOR, action)(int(args[0]))
    if action in ("answer", "discard") and len(args) == 2:
        return getattr(TUTOR, action)(int(args[0]), args[1])
    if action == "matrix":
        return {"rows": 8, "cols": 13, "frame": TUTOR.frame()}
    if action == "health":
        return {"status": "ok", "language": TUTOR.language, "topics": TUTOR.available}
    return None


def page_file(path):
    """A file of tutor_web/, and nothing outside it."""
    name = "index.html" if path in ("", "/") else path.lstrip("/")
    full = os.path.realpath(os.path.join(WEB, name))
    return full if full.startswith(os.path.realpath(WEB) + os.sep) and os.path.isfile(full) else None


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, code=200):
        self.send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def send_file(self, path, content_type=None):
        with open(path, "rb") as f:
            self.send(200, f.read(), content_type or mimetypes.guess_type(path)[0] or "application/octet-stream")

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path.startswith("/api/"):
                result = api(url.path)
                # Errors go as {"error": ...} with code 200, like in the App Lab app
                return self.send_json(result if result is not None else {"error": "Aquesta ruta no existeix."})
            if url.path.startswith("/img/"):
                image = TUTOR.image_path(unquote(url.path[len("/img/"):]))
                return self.send_file(image, "image/jpeg") if image else self.send_json({"error": "No image"}, 404)
            found = page_file(unquote(url.path))
            if found:
                return self.send_file(found)
            self.send_json({"error": "Not found"}, 404)
        except TutorError as error:
            self.send_json({"error": str(error)})
        except (KeyError, ValueError):
            self.send_json({"error": "Falta un paràmetre o no és vàlid."})

    def log_message(self, *_args):
        pass


def main():
    global TUTOR
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=S.DB_PATH)
    p.add_argument("--images", default=S.IMAGES_DIR)
    p.add_argument("--language", default=S.LANGUAGE, help="language of the problems shown, e.g. cat or eng")
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it to your network")
    p.add_argument("--port", type=int, default=S.PORT)
    p.add_argument("--live-hints", action="store_true",
                   help="let the model write a hint on the spot when none is stored (needs the model server)")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"{args.db} doesn't exist. Build it first: python3 tutor_build.py all")
    live = (args.live_hints or S.LIVE_HINTS) and llmhint.reachable()
    try:
        TUTOR = Tutor(args.db, images_dir=args.images, language=args.language, live_hints=live)
    except TutorError as error:
        sys.exit(str(error))
    print(f"Problems in '{TUTOR.language}', {len(TUTOR.available)} topics")
    print("Model hints: stored ones" + (", and written on the spot when none is stored" if live else " only"))
    print(f"Open http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()

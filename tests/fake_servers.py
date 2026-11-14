#!/usr/bin/env python3
"""Stand-ins for the two llama.cpp servers, to run the code on a laptop.

    python3 tests/fake_servers.py        # ports 8081 (language model) and 8082 (embeddings)

They speak the same API, so predict.py, eval.py, tutor_build.py and the tutor
run unchanged. They know no maths: the "model" prefers D, and the embeddings
are a bag of words. Use them to test that the code runs, never for a result.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from copilot.config import CONFIG  # noqa: E402
from copilot.tutor.textutil import hash_embed  # noqa: E402

LETTER_LOGPROBS = {"D": -0.6, "A": -1.2, "B": -2.6, "C": -2.9, "E": -3.1}


def chat(payload):
    text = payload["messages"][-1]["content"]
    if isinstance(text, list):
        text = " ".join(part.get("text", "") for part in text)
    timings = {"prompt_n": len(text.split()), "prompt_per_second": 11.0, "predicted_n": 1, "predicted_per_second": 5.0}
    if "grammar" in payload:
        top = [{"token": k, "logprob": v} for k, v in LETTER_LOGPROBS.items()]
        return {"choices": [{"message": {"content": "D"}, "logprobs": {"content": [{"token": "D", "top_logprobs": top}]}}],
                "timings": timings}
    first_words = " ".join(text.replace("Problem:", "").split()[:4])
    return {"choices": [{"message": {"content": f"Torna a llegir «{first_words}» i escriu què saps."}}], "timings": timings}


class Handler(BaseHTTPRequestHandler):
    def reply(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({"status": "ok"})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/embeddings"):
            texts = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
            return self.reply({"data": [{"index": i, "embedding": hash_embed(t)} for i, t in enumerate(texts)]})
        self.reply(chat(payload))

    def log_message(self, *_args):
        pass


def serve(port):
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    ports = [int(CONFIG["LLM_PORT"]), int(CONFIG["EMBED_PORT"])]
    for port in ports:
        threading.Thread(target=serve, args=(port,), daemon=True).start()
    print(f"Fake model on {ports[0]} and fake embeddings on {ports[1]}. They know no maths. Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print()

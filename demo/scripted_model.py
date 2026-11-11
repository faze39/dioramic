"""Demo only: a tiny OpenAI-compatible endpoint that plays a fixed script, so the
dioramic demo runs the real Hermes agent loop without a model API key.

Turn 1: call dioramic_render with the scene spec file given on the command line.
Turn 2: after the result, call dioramic_tweak with the changes file.
Turn 3: reply with a short summary built from the tool results.
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SCENE = json.load(open(sys.argv[2]))
CHANGES = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None


def _text(m):
    c = m.get("content") or ""
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c


def plan(messages):
    results = []
    for m in messages:
        if m.get("role") == "tool":
            try:
                results.append(json.loads(_text(m)))
            except ValueError:
                results.append({"error": _text(m)[:200]})
    if not results:
        return ("dioramic_render", {"scene": SCENE})
    last = results[-1]
    if "error" in last:
        return ("text", "the render failed: " + json.dumps(last)[:300])
    if len(results) == 1 and CHANGES:
        return ("dioramic_tweak", {"scene_id": last["scene_id"], "changes": CHANGES})
    lines = [f"- {r['scene_id']}: {r['frames']} frames in {r['render_seconds']}s -> {r['clip']}" for r in results]
    return ("text", "rendered in blender:\n" + "\n".join(lines))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": "scripted", "object": "model"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        kind, payload = plan(req.get("messages", []))
        created = int(time.time())
        if kind == "text":
            msg, finish = {"role": "assistant", "content": payload}, "stop"
        else:
            call = {"index": 0, "id": f"call_{created}_{len(req.get('messages', []))}", "type": "function",
                    "function": {"name": kind, "arguments": json.dumps(payload)}}
            msg, finish = {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in ({"id": "c1", "object": "chat.completion.chunk", "created": created, "model": "scripted",
                       "choices": [{"index": 0, "delta": msg, "finish_reason": None}]},
                      {"id": "c1", "object": "chat.completion.chunk", "created": created, "model": "scripted",
                       "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}):
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        for c in msg.get("tool_calls") or []:
            c.pop("index", None)
        self._json({"id": "c1", "object": "chat.completion", "created": created, "model": "scripted",
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": usage})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()

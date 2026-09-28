"""Two isolated SSE requests: split Unicode packets and burst text snapshots."""
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if "after_seq=99" in self.path:
            sid = self.path.split("/sessions/")[1].split("/")[0]
            run_id, response_id = str(uuid.uuid4()), str(uuid.uuid4())
            events = []
            frames = []
            for sequence, content in enumerate(("中", "中文", "中文😀"), start=1):
                event = {"seq": sequence, "stage": "response.delta", "session_id": sid,
                         "event_id": str(uuid.uuid4()), "run_id": run_id, "revision": 1,
                         "payload": {"response": {"response_id": response_id,
                                                  "chunk_seq": sequence, "text": content, "status": "streaming"}}}
                events.append(event)
                recovery = ({"version": 1, "checkpoint": {"session_id": sid,
                             "event_base_seq": 0, "events": [event], "runs": {}}}
                            if sequence == 1 else {"version": sequence, "deltas": [
                                {"base_version": sequence - 1, "version": sequence,
                                 "changes": [{"op": "append", "path": ["events"], "value": [event]}]}]})
                page = {"session_id": sid, "last_seq": sequence, "events": [event],
                        "recovery": recovery, "has_running_run": True}
                frames.append(("data: " + json.dumps(page, ensure_ascii=False) + "\n\n").encode())
            self.wfile.write(b"".join(frames))
            self.wfile.flush()
            return
        for sequence in range(3):
            value = json.dumps({"sample": "中文😀 **未闭合", "sequence": sequence, "sent_at": time.time()}, ensure_ascii=False)
            data = ("id: " + str(sequence) + "\nevent: session\ndata: " + value + "\n\n").encode()
            cut = data.index("中".encode()) + 1
            self.wfile.write(data[:cut]); self.wfile.flush()
            time.sleep(.02)
            self.wfile.write(data[cut:]); self.wfile.flush()
            time.sleep(.2)

with HTTPServer(("127.0.0.1", 0), Handler) as server:
    print("http://127.0.0.1:" + str(server.server_port), flush=True)
    server.timeout = 180
    server.handle_request()
    server.handle_request()

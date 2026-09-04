"""One isolated HTTP request, with Unicode split across transport packets."""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
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

"""QA-only fence: one intended parse and one accounted provider request."""
import threading

QUESTION = "刚才保存的 RAG 知识卡存好了吗？实际保存了几张？"


class OneRequestFence:
    def __init__(self, directory, emit):
        self.directory, self.emit = directory, emit
        self.lock = threading.RLock()
        self.parses = self.wires = 0

    def stop(self, reason):
        with self.lock:
            marker = self.directory / "STOP"
            if not marker.exists():
                marker.write_text(reason + "\n")
            self.emit("one_request_stop", reason=reason)

    def admit_parse(self, schema, payload):
        with self.lock:
            if ((self.directory / "STOP").exists() or self.parses != 0 or schema != "IntentDecision"
                    or payload.get("current_inputs") != [QUESTION]):
                self.stop("STOP: no retry, background call or other model work authorized")
                raise AssertionError("Only one intended status parse is authorized")
            self.parses += 1

    def admit_wire(self, *, host, expected_host, method, number, request_id):
        with self.lock:
            if ((self.directory / "STOP").exists() or self.wires != 0 or self.parses != 1
                    or host != expected_host or method != "POST" or number != 30 or not request_id):
                self.stop("STOP: unexpected or duplicate external request blocked before transport")
                raise AssertionError("Unaccounted or extra external request forbidden")
            self.wires += 1
            self.emit("single_wire_admitted", number=number, request_id=request_id, host=host)
            # This marker prevents additional work while the one request returns.
            self.stop("STOP: original total budget 30/30 admitted; no further remote requests")

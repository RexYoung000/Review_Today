"""Exercise the QA spending fence without an SDK or network connection."""
import json
from pathlib import Path
import tempfile

from fence import OneRequestFence, QUESTION


def main():
    directory = Path(tempfile.mkdtemp(prefix="review-today-last-request-guard-", dir="/tmp"))
    events = []
    def emit(kind, **values):
        events.append(dict(type=kind, **values))
    def expect_block(function):
        try:
            function()
        except AssertionError:
            return
        raise AssertionError("Spending fence did not block")
    def wire(fence, **overrides):
        args = dict(host="provider.example", expected_host="provider.example", method="POST", number=30, request_id="local-selftest")
        fence.admit_wire(**(args | overrides))
    def new(name):
        target = directory / name
        target.mkdir()
        return OneRequestFence(target, emit)

    fence = new("single")
    fence.admit_parse("IntentDecision", dict(current_inputs=[QUESTION]))
    wire(fence)
    assert (fence.parses, fence.wires) == (1, 1) and (fence.directory / "STOP").exists()
    expect_block(lambda: wire(fence))
    expect_block(lambda: OneRequestFence(fence.directory, emit).admit_parse("IntentDecision", dict(current_inputs=[QUESTION])))
    for name, change in (("unaccounted", dict(number=None)), ("wrong_number", dict(number=29)),
                         ("wrong_host", dict(host="other.example")), ("missing_identity", dict(request_id=None))):
        fence = new(name)
        fence.admit_parse("IntentDecision", dict(current_inputs=[QUESTION]))
        expect_block(lambda: wire(fence, **change))
        assert fence.wires == 0
    for name, schema, question in (("other_work", "SessionSummary", QUESTION), ("other_input", "IntentDecision", "继续讲解")):
        fence = new(name)
        expect_block(lambda: fence.admit_parse(schema, dict(current_inputs=[question])))
        assert fence.parses == fence.wires == 0
    result = dict(outcome="PASS", directory=str(directory), real_model_requests=0,
        checked=["single admission", "second transport", "process restart", "unaccounted transport",
                 "wrong counter", "wrong destination", "missing identity", "other model work", "different input"])
    (Path(__file__).parent / "guard-selftest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

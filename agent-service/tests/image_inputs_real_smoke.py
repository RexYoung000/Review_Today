"""Opt-in real Flash image turn and text followup using a synthetic fixture."""
import argparse
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", required=True, action="store_true")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite prior evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-today-image-live-") as directory:
        os.environ["REVIEW_TODAY_HARNESS_DB"] = str(Path(directory) / "checkpoint.sqlite3")
        os.environ["REVIEW_TODAY_JEV_TEST"] = "0"
        os.environ["REVIEW_TODAY_SEARCH_PROVIDER"] = "none"
        os.environ["REVIEW_TODAY_BROWSER_FALLBACK"] = "0"
        from agent_service.config import PROVIDER
        from agent_service.conversation import ConversationHarness
        from agent_service.conversation_store import ConversationStore
        from agent_service.harness_store import HarnessStore
        from agent_service.schemas import SessionMessageRequest
        from agent_service.openai_client import parse_model
        from agent_service.image_inputs import ImageAttachment
        if PROVIDER != "deepseek":
            raise SystemExit("Requires the existing DeepSeek provider; no configuration was changed")
        image = ImageAttachment(name=args.image.name, mime_type="image/png", data_base64=base64.b64encode(args.image.read_bytes()).decode())
        h = ConversationHarness(ConversationStore(HarnessStore(os.environ["REVIEW_TODAY_HARNESS_DB"])))
        result = dict(fixture="synthetic, manually authored learning slide", image=image.metadata(),
                      provider=PROVIDER, calls=[], turns=[], result="running")

        def record(system, prompt, schema, **kwargs):
            start = time.monotonic()
            entry = dict(schema=schema.__name__, model=kwargs.get("model"), image_count=len(kwargs.get("images", [])))
            result["calls"].append(entry)
            try:
                value = parse_model(system, prompt, schema, **kwargs)
                return value
            except Exception as exc:
                entry["error"] = getattr(exc, "code", type(exc).__name__)
                raise
            finally:
                entry["elapsed_ms"] = round((time.monotonic() - start) * 1000)

        sid = str(uuid.uuid4())
        def send(text, attachment=None):
            accepted = h.accept(sid, SessionMessageRequest(client_message_id=str(uuid.uuid4()), content=text,
                content_type="image" if attachment else "text", image=attachment))
            h.drain(sid)
            state = h.store.get(sid); run = state["runs"][accepted.run_id]
            turn = dict(input=text, status=run["status"], elapsed_ms=run.get("elapsed_ms"), intent=run.get("intent"),
                readings=[m["image_reading"] for m in state["messages"] if m.get("image_reading")],
                replies=[m["content"] for m in state["messages"] if m["role"] == "coach" and m["run_id"] == accepted.run_id],
                calls=run.get("model_calls", []),
                failures=[dict(stage=e["stage"], code=e.get("error_code"), summary=e["user_summary"])
                          for e in state["events"] if e["run_id"] == accepted.run_id and e.get("error_code")])
            result["turns"].append(turn)
            print(json.dumps(dict(status=turn["status"], elapsed_ms=turn["elapsed_ms"], calls=len(turn["calls"])), ensure_ascii=False), flush=True)
            assert turn["status"] == "completed" and turn["replies"], "turn failed"
        try:
            with patch("agent_service.conversation.parse_model", side_effect=record), patch.object(h, "_schedule_summary"):
                send("请读图。先逐字列出图片文字，保留数字和否定词；再用两句话解释箭头关系；最后说明看不清或不确定的部分。不需要联网、出题或保存。", image)
                assert result["turns"][0]["readings"]
                image_calls = sum(c["image_count"] for c in result["calls"])
                send("图中写的是可以编造答案，还是不应编造答案？只引用对应原句。")
                assert sum(c["image_count"] for c in result["calls"]) == image_calls, "text followup unexpectedly resubmitted pixels"
            result["result"] = "transport_and_followup_passed"
        except Exception as exc:
            result.update(result="failed", failure=str(exc))
            raise
        finally:
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

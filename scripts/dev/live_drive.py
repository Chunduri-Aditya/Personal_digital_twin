"""Drive the running app (http://127.0.0.1:7861 by default) with gradio_client and print returned values verbatim.

Usage (from the project root, PYTHONUTF8=1; add --port 7871 for a UI-agent instance):
  python scripts/dev/live_drive.py view_api
  python scripts/dev/live_drive.py status
  python scripts/dev/live_drive.py warm ask
  python scripts/dev/live_drive.py ask "message" [--history-file data/hist.json] [--q8] [--temp 1.0] [--checker]
                                    [--save-history data/hist.json] [--condition persona]
  python scripts/dev/live_drive.py decide_b1 "situation" [--say] [--condition demographic]
  python scripts/dev/live_drive.py decide_b2 "situation" "A" "B" [--say] [--condition persona]
  python scripts/dev/live_drive.py eval_live CANDIDATE_KEY [Q-NN] [--condition persona]
  python scripts/dev/live_drive.py act "request" [--polish]
  python scripts/dev/live_drive.py polish "text"
  python scripts/dev/live_drive.py see path/to/image.jpg
  python scripts/dev/live_drive.py eval_show
  python scripts/dev/live_drive.py free_gpu

--condition is appended as the LAST positional argument only when given (docs/PLAN_UNIFIED.md 3.4), so the
phase-1 calls keep their exact shape.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from gradio_client import Client, handle_file

DEFAULT_PORT = 7861
CONDITIONS = ("demographic", "persona", "interview")


def show(label, value):
    print(f"=== {label} ===")
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=1, default=str))
    else:
        print(value)
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"app port (default {DEFAULT_PORT})")
    ap.add_argument("--history-file")
    ap.add_argument("--save-history")
    ap.add_argument("--q8", action="store_true")
    ap.add_argument("--checker", action="store_true")
    ap.add_argument("--temp", type=float, default=1.0)
    ap.add_argument("--polish", action="store_true")
    ap.add_argument("--say", action="store_true", help="call /say_it after decide_b1/decide_b2 (same session)")
    ap.add_argument("--condition", choices=CONDITIONS,
                    help="appended as the last positional input of /ask, /decide_b1, /decide_b2, /eval_live")
    a = ap.parse_args()

    url = f"http://127.0.0.1:{a.port}"
    cond = [a.condition] if a.condition else []
    c = Client(url, verbose=False)
    t0 = time.perf_counter()

    if a.cmd == "view_api":
        c.view_api(all_endpoints=True)
    elif a.cmd == "status":
        md, df = c.predict(api_name="/status")
        show("status_md", md)
        show("telemetry_df", df)
    elif a.cmd == "warm":
        show("warm", c.predict(a.args[0], api_name="/warm"))
    elif a.cmd == "free_gpu":
        show("free_gpu", c.predict(api_name="/free_gpu"))
    elif a.cmd == "ask":
        history = []
        if a.history_file:
            history = json.load(open(a.history_file, encoding="utf-8"))
        job = c.submit(a.args[0], history, a.q8, a.temp, a.checker, *cond, api_name="/ask")
        final = job.result()
        outs = job.outputs()
        chatbot, trace_md, checker_md, hint_md, textbox = final
        show("n_stream_outputs", len(outs))
        show("chatbot (final)", chatbot)
        reply = ""
        if chatbot:
            last = chatbot[-1]
            content = last.get("content")
            if isinstance(content, list):
                reply = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            else:
                reply = str(content)
        show("reply_text", reply)
        show("trace_md", trace_md)
        show("checker_md", checker_md)
        show("hint_md", hint_md)
        show("textbox", repr(textbox))
        if a.save_history:
            json.dump(chatbot, open(a.save_history, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            show("saved_history", a.save_history)
    elif a.cmd == "decide_b1":
        md, js = c.predict(a.args[0], *cond, api_name="/decide_b1")
        show("result_md", md)
        show("result_json", js)
        if a.say:
            show("say_it", c.predict(api_name="/say_it"))
    elif a.cmd == "decide_b2":
        md, js = c.predict(a.args[0], a.args[1], a.args[2], *cond, api_name="/decide_b2")
        show("result_md", md)
        show("result_json", js)
        if a.say:
            show("say_it", c.predict(api_name="/say_it"))
    elif a.cmd == "say_it":
        show("say_it", c.predict(api_name="/say_it"))
    elif a.cmd == "eval_live":
        candidate = a.args[0] if a.args else "stheno_q4"
        qid = a.args[1] if len(a.args) > 1 else "Q-01"
        show("eval_live", c.predict(candidate, qid, *cond, api_name="/eval_live"))
    elif a.cmd == "act":
        answer, trace_md = c.predict(a.args[0], api_name="/act")
        show("answer", answer)
        show("trace_md", trace_md)
        with open("data/act_answer.txt", "w", encoding="utf-8") as f:
            f.write(answer or "")
        if a.polish:
            show("polish", c.predict(answer, api_name="/polish"))
    elif a.cmd == "polish":
        text = a.args[0]
        if text.startswith("@"):
            text = open(text[1:], encoding="utf-8").read()
        show("polish_input", text)
        show("polish", c.predict(text, api_name="/polish"))
    elif a.cmd == "see":
        desc, react, trace_md = c.predict(handle_file(a.args[0]), api_name="/see")
        show("description", desc)
        show("reaction", react)
        show("trace_md", trace_md)
    elif a.cmd == "eval_show":
        summary, retrieval = c.predict(api_name="/eval_show")
        show("summary_df", summary)
        show("retrieval_df", retrieval)
    else:
        print("unknown cmd", a.cmd)
        return 2
    print(f"=== wall {time.perf_counter() - t0:.1f} s ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""P4 decide lane, visual review r1 (read-only, no app boot): DEMO CONTRACT diff of twin/ui/decide.py against
scripts/dev/finish/backup_pre_c/twin/ui/decide.py. Only elem_classes/elem_id additions, layout wrappers and private
(api_name=False, model-free) events may differ. Also checks the DEMO.md sections 3-4 bold labels and every old elem_id.
Writes scripts/dev/shots/lane_decide/review_r1/diff_check.json and prints the unified diff. Exit 1 on a frozen change."""
from __future__ import annotations

import ast
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CUR = ROOT / "twin" / "ui" / "decide.py"
OLD = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c" / "twin" / "ui" / "decide.py"
DEMO = ROOT / "docs" / "DEMO.md"
PIPE = ROOT / "twin" / "pipelines" / "decide.py"
OUT = ROOT / "scripts" / "dev" / "shots" / "lane_decide" / "review_r1" / "diff_check.json"

FROZEN_KW = {"label", "placeholder", "value", "choices", "lines", "max_lines", "info", "interactive", "visible",
             "show_label", "type", "container", "show_copy_button", "autoscroll", "open"}
EVENT_KW_FROZEN = {"api_name", "concurrency_id", "concurrency_limit", "queue", "trigger_mode", "js", "cancels",
                   "preprocess", "postprocess", "every", "batch", "show_api", "api_visibility"}
EVENTS = {"click", "change", "submit", "select", "input", "blur", "focus", "upload", "load", "then", "success",
          "release", "tick", "clear", "stream", "key_up"}
LAYOUT = {"Row", "Column", "Group", "Accordion", "Tab", "Tabs", "Blocks"}
MODEL_CALL = re.compile(r"\b(decide\.(decide_b1|decide_b2|say_it)|clients\.|MANAGER\.|gpu\.|warm|session\()")


def seg(text: str, node) -> str:
    return ast.get_source_segment(text, node) or ""


def top(tree):
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assigns = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigns[t.id] = n
    return funcs, assigns


def gr_call(call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "gr":
        return f.attr
    return None


def components(fn, text):
    named, anon = {}, []
    for node in ast.walk(fn):
        call = name = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
        elif isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
            call = node.context_expr
            name = node.optional_vars.id if isinstance(node.optional_vars, ast.Name) else None
        if call is None or gr_call(call) is None:
            continue
        rec = {"ctor": gr_call(call), "args": [seg(text, a) for a in call.args],
               "kw": {k.arg: seg(text, k.value) for k in call.keywords}, "line": call.lineno}
        (named.__setitem__(name, rec) if name else anon.append(rec))
    return named, anon


def events(fn, text):
    out = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in EVENTS
                and isinstance(node.func.value, ast.Name) and node.func.value.id != "gr"):
            out.append({"target": node.func.value.id, "event": node.func.attr,
                        "args": [seg(text, a) for a in node.args],
                        "kw": {k.arg: seg(text, k.value) for k in node.keywords}, "line": node.lineno})
    return out


def returned_dict(fn, text):
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return {seg(text, k).strip("\"'"): seg(text, v) for k, v in zip(node.value.keys, node.value.values)}
    return {}


def demo_labels() -> list[str]:
    text = DEMO.read_text(encoding="utf-8")
    start = text.index("## 3. Never click live")
    end = text.index("\n## 5", start)
    return sorted(set(re.findall(r"\*\*(.+?)\*\*", text[start:end])))


def main() -> int:
    old_t, cur_t = OLD.read_text(encoding="utf-8"), CUR.read_text(encoding="utf-8")
    old, cur = ast.parse(old_t), ast.parse(cur_t)
    fails, notes = [], []
    diff = list(difflib.unified_diff(old_t.splitlines(), cur_t.splitlines(), "backup_pre_c/twin/ui/decide.py",
                                     "twin/ui/decide.py", lineterm="", n=1))
    ofun, oas = top(old)
    cfun, cas = top(cur)
    for name, node in ofun.items():
        if name == "build":
            continue
        if name not in cfun:
            fails.append(f"function removed: {name}")
        elif ast.dump(node) != ast.dump(cfun[name]):
            fails.append(f"function changed: {name}")
        else:
            notes.append(f"function unchanged (AST equal): {name}")
    for name in set(cfun) - set(ofun):
        notes.append(f"function added: {name} (lines {cfun[name].lineno}-{cfun[name].end_lineno})")
    for name, node in oas.items():
        if name not in cas or ast.dump(node) != ast.dump(cas[name]):
            fails.append(f"module assignment changed: {name}")
        else:
            notes.append(f"module assignment unchanged: {name}")
    if [ast.dump(n) for n in old.body if isinstance(n, (ast.Import, ast.ImportFrom))] != \
            [ast.dump(n) for n in cur.body if isinstance(n, (ast.Import, ast.ImportFrom))]:
        notes.append("imports differ")

    oc, oanon = components(ofun["build"], old_t)
    cc, canon = components(cfun["build"], cur_t)
    for name, rec in oc.items():
        if name not in cc:
            fails.append(f"component removed: {name}")
            continue
        new = cc[name]
        if rec["ctor"] != new["ctor"]:
            fails.append(f"component type changed: {name} {rec['ctor']} -> {new['ctor']}")
        if rec["args"] != new["args"]:
            fails.append(f"positional args changed: {name} {rec['args']} -> {new['args']}")
        for k in sorted(set(rec["kw"]) | set(new["kw"])):
            a, b = rec["kw"].get(k), new["kw"].get(k)
            if a == b:
                continue
            try:   # the same literal value re-indented (implicit string concatenation) is not a change
                if a is not None and b is not None and ast.literal_eval(f"({a})") == ast.literal_eval(f"({b})"):
                    notes.append(f"{name} ({rec['ctor']}) kw {k}: source re-indented, literal value EQUAL")
                    continue
            except (ValueError, SyntaxError):
                pass
            msg = f"{name} ({rec['ctor']}) kw {k}: {a} -> {b}"
            (fails if k in FROZEN_KW else notes).append(("FROZEN " if k in FROZEN_KW else "layout/style ") + msg)
    for name in set(cc) - set(oc):
        rec = cc[name]
        kind = "layout wrapper" if rec["ctor"] in LAYOUT else "NEW COMPONENT"
        notes.append(f"added {kind}: {name} = gr.{rec['ctor']}({rec['args']}, {rec['kw']}) line {rec['line']}")
    notes.append(f"anonymous wrappers: backup {[r['ctor'] for r in oanon]} -> current "
                 f"{[(r['ctor'], r['kw']) for r in canon]}")

    oe, ce = events(ofun["build"], old_t), events(cfun["build"], cur_t)
    key = lambda e: (e["target"], e["event"], e["args"][0] if e["args"] else e["kw"].get("fn"))
    ce_by = {key(e): e for e in ce}
    for e in oe:
        k = key(e)
        if k not in ce_by:
            fails.append(f"event removed or retargeted: {k}")
            continue
        n = ce_by[k]
        if e["args"] != n["args"]:
            fails.append(f"event args changed {k}: {e['args']} -> {n['args']}")
        for kw in sorted(set(e["kw"]) | set(n["kw"])):
            if e["kw"].get(kw) != n["kw"].get(kw):
                fails.append(f"event kw changed {k} {kw}: {e['kw'].get(kw)} -> {n['kw'].get(kw)}")
        notes.append(f"event unchanged: {k} inputs={e['kw'].get('inputs')} outputs={e['kw'].get('outputs')} "
                     f"api_name={e['kw'].get('api_name')} concurrency_id={e['kw'].get('concurrency_id')}")
    for k in set(ce_by) - {key(e) for e in oe}:
        n = ce_by[k]
        handler = k[2]
        body = seg(cur_t, cfun[handler]) if handler in cfun else ""
        called = sorted({m.group(0) for m in MODEL_CALL.finditer(body)})
        helpers = re.findall(r"\b([a-z_]+)\(", body)
        for h in helpers:
            if h in cfun and h != handler:
                called += sorted({m.group(0) for m in MODEL_CALL.finditer(seg(cur_t, cfun[h]))})
        private = n["kw"].get("api_name") == "False"
        gpu = n["kw"].get("concurrency_id") == '"gpu"'
        line = f"new event {k}: kw={n['kw']} handler model-ish calls={called or 'none'}"
        if not private or gpu or called:
            fails.append("NOT PRIVATE/MODEL-FREE " + line)
        else:
            notes.append("private model-free " + line)

    od, cd = returned_dict(ofun["build"], old_t), returned_dict(cfun["build"], cur_t)
    for k, v in od.items():
        if cd.get(k) != v:
            fails.append(f"build() return key changed: {k}: {v} -> {cd.get(k)}")
    notes.append(f"build() return keys added: {sorted(set(cd) - set(od))}")

    old_ids = set(re.findall(r'elem_id="([^"]+)"', old_t))
    cur_ids = set(re.findall(r'elem_id="([^"]+)"', cur_t))
    if old_ids - cur_ids:
        fails.append(f"elem_ids removed: {sorted(old_ids - cur_ids)}")
    notes.append(f"elem_ids backup {sorted(old_ids)}; current {sorted(cur_ids)}")

    ui_now = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "twin" / "ui").glob("*.py"))
    ui_now += (ROOT / "app.py").read_text(encoding="utf-8") + PIPE.read_text(encoding="utf-8")
    ui_old = "\n".join(p.read_text(encoding="utf-8") for p in (OLD.parent).glob("*.py"))
    ui_old += (ROOT / "scripts" / "dev" / "finish" / "backup_pre_c" / "app.py").read_text(encoding="utf-8")
    ui_old += PIPE.read_text(encoding="utf-8")
    label_rows = []
    for label in demo_labels():
        core = label.split("…")[0].strip() if "…" in label else label
        in_old_decide, in_cur_decide = core in old_t, core in cur_t
        row = {"label": label, "in_backup_decide_py": in_old_decide, "in_decide_py": in_cur_decide,
               "in_any_ui_or_pipeline_now": core in ui_now, "was_in_any_before": core in ui_old}
        label_rows.append(row)
        if in_old_decide and not in_cur_decide:
            fails.append(f"DEMO bold label lost from decide.py: {label!r}")
        if row["was_in_any_before"] and not row["in_any_ui_or_pipeline_now"]:
            fails.append(f"DEMO bold label lost from the UI: {label!r}")
    report = {"fails": fails, "notes": notes, "labels": label_rows, "diff_lines": len(diff)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(diff))
    print("\n==== notes")
    print("\n".join(notes))
    print("\n==== DEMO.md sections 3-4 bold labels (decide.py before -> now)")
    for r in label_rows:
        if r["in_backup_decide_py"] or r["in_decide_py"]:
            print(f"  {r['label']!r}: backup={r['in_backup_decide_py']} now={r['in_decide_py']}")
    print(f"\n==== FROZEN FAILURES ({len(fails)})")
    print("\n".join(fails) if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

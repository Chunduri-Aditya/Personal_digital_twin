"""Review helper (read-only): unified diff of the evals_status lane modules against backup_pre_c, plus an AST
comparison of every function except build(), and of the Gradio constructor calls' frozen keywords inside build().
Writes nothing but stdout."""
from __future__ import annotations

import ast
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
FILES = ["twin/ui/evals.py", "twin/ui/status.py"]
FROZEN_KW = {"label", "value", "placeholder", "choices", "headers", "interactive", "variant_ignored", "lines",
             "max_height", "wrap", "line_breaks", "api_name", "concurrency_id", "inputs", "outputs", "type"}
LAYOUT_KW = {"elem_id", "elem_classes", "scale", "min_width", "variant"}

failures = 0


def funcs(tree):
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def assigns(tree):
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = ast.dump(n.value)
    return out


def calls_in(fn):
    """Every call node inside build(), keyed by a readable signature, in order."""
    res = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            res.append((name, node))
    # source order, not ast.walk's breadth-first order (a new wrapper would otherwise reorder nested calls)
    res.sort(key=lambda t: (t[1].lineno, t[1].col_offset))
    return res


def strip_doc(fn):
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return "\n".join(ast.dump(b) for b in body)


for rel in FILES:
    new_src = (ROOT / rel).read_text(encoding="utf-8")
    old_src = (BACKUP / rel).read_text(encoding="utf-8")
    print("=" * 100)
    print(f"UNIFIED DIFF {rel}")
    for line in difflib.unified_diff(old_src.splitlines(), new_src.splitlines(), "backup/" + rel, rel, n=1,
                                     lineterm=""):
        print(line)
    new_t, old_t = ast.parse(new_src), ast.parse(old_src)
    nf, of = funcs(new_t), funcs(old_t)
    print("-" * 100)
    print(f"functions only in backup: {sorted(set(of) - set(nf))}; only in new: {sorted(set(nf) - set(of))}")
    for name in sorted(set(nf) & set(of)):
        if name == "build":
            continue
        same = strip_doc(nf[name]) == strip_doc(of[name])
        if not same:
            failures += 1
        print(f"function {name}: {'EQUAL (docstring aside)' if same else 'DIFFERENT'}")
    na, oa = assigns(new_t), assigns(old_t)
    for k in sorted(set(na) | set(oa)):
        if na.get(k) != oa.get(k):
            failures += 1
            print(f"module constant {k}: DIFFERENT")
    print(f"module constants compared: {len(set(na) | set(oa))}")

    # build(): compare Gradio component constructor calls (by label/value text) and event wiring calls
    def components(fn):
        comps = []
        events = []
        for name, node in calls_in(fn):
            kws = {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}
            args = [ast.unparse(a) for a in node.args]
            if name.startswith("gr.") and name not in ("gr.Row", "gr.Column", "gr.Group", "gr.Tab", "gr.Accordion"):
                comps.append((name, args, {k: v for k, v in kws.items() if k not in LAYOUT_KW},
                              {k: v for k, v in kws.items() if k in LAYOUT_KW}))
            elif name.endswith((".click", ".then", ".tick", ".change", ".select", ".submit")):
                events.append((name, args, kws))
        return comps, events

    nc, ne = components(nf["build"])
    oc, oe = components(of["build"])
    print("-" * 100)
    print(f"build(): components new={len(nc)} backup={len(oc)}; events new={len(ne)} backup={len(oe)}")
    ok_frozen = [(c[0], c[1], c[2]) for c in nc] == [(c[0], c[1], c[2]) for c in oc]
    print(f"component constructors (type, positional args, non-layout keywords, in order): "
          f"{'EQUAL' if ok_frozen else 'DIFFERENT'}")
    if not ok_frozen:
        failures += 1
        for a, b in zip(oc, nc):
            if (a[0], a[1], a[2]) != (b[0], b[1], b[2]):
                print("  backup:", a[:3])
                print("  new   :", b[:3])
    for a, b in zip(oc, nc):
        if a[3] != b[3]:
            print(f"  layout kw change on {b[0]} {b[1][:1]}: {a[3]} -> {b[3]}")
    ok_events = ne == oe
    print(f"event wiring calls (method, args, keywords, in order): {'EQUAL' if ok_events else 'DIFFERENT'}")
    if not ok_events:
        failures += 1
        for a, b in zip(oe, ne):
            if a != b:
                print("  backup:", a)
                print("  new   :", b)
        if len(oe) != len(ne):
            print("  lengths differ", len(oe), len(ne))
    # layout wrappers
    def wrappers(fn):
        return [(n, {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}) for n, node in calls_in(fn)
                if n in ("gr.Row", "gr.Column", "gr.Group", "gr.Tab", "gr.Accordion")]
    print(f"layout wrappers backup: {wrappers(of['build'])}")
    print(f"layout wrappers new   : {wrappers(nf['build'])}")
    # elem_ids
    def elem_ids(src):
        import re
        return set(re.findall(r"elem_id\s*=\s*[\"']([^\"']+)[\"']", src))
    old_ids, new_ids = elem_ids(old_src), elem_ids(new_src)
    missing = sorted(old_ids - new_ids)
    print(f"elem_ids backup={sorted(old_ids)}")
    print(f"elem_ids new   ={sorted(new_ids)}")
    print(f"elem_ids missing now: {missing}")
    if missing:
        failures += 1
    # returned dict keys of build
    def ret_keys(fn):
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                return [ast.unparse(k) for k in node.value.keys]
        return []
    rk_equal = ret_keys(nf["build"]) == ret_keys(of["build"])
    print(f"build() return dict keys: {'EQUAL' if rk_equal else 'DIFFERENT'} {ret_keys(nf['build'])}")
    if not rk_equal:
        failures += 1

print("=" * 100)
print(f"FROZEN FAILURES: {failures}")
sys.exit(1 if failures else 0)

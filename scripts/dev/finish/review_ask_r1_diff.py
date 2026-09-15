"""Review of the ask lane, round 1: DEMO CONTRACT in code. Compares twin/ui/ask.py with the pre-restyle backup.

- unified diff (difflib)
- top-level functions and assignments: AST-equal or changed (only the docstring, build and new presentation helpers
  may differ)
- build(): every gr.* component call, keyword by keyword (label, placeholder, value, choices, ...)
- the event wiring statements after the tab block: AST-equal
- string constants of the backup still present; elem_ids of the backup still present
- the bold labels DEMO.md sections 3-4 quote, found in the backup vs now
Read-only."""
from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NEW = ROOT / "twin" / "ui" / "ask.py"
OLD = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c" / "twin" / "ui" / "ask.py"
DEMO = ROOT / "docs" / "DEMO.md"
LAYOUT_KW = {"elem_id", "elem_classes", "scale", "min_width"}


def dump(node) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def top_level(tree: ast.Module) -> dict:
    out = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[n.name] = n
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n
    return out


def gr_calls(fn: ast.FunctionDef) -> list[dict]:
    """gr.X(...) calls inside build, keyed by the bound name (assign target or with ... as name) or type#k."""
    names = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            names[id(n.value)] = n.targets[0].id if isinstance(n.targets[0], ast.Name) else None
        if isinstance(n, ast.With):
            for item in n.items:
                if isinstance(item.context_expr, ast.Call) and isinstance(item.optional_vars, ast.Name):
                    names[id(item.context_expr)] = item.optional_vars.id
    out, counts = [], {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "gr":
            kind = n.func.attr
            counts[kind] = counts.get(kind, 0) + 1
            key = names.get(id(n)) or f"{kind}#{counts[kind]}"
            out.append({"key": key, "kind": kind, "args": [ast.unparse(a) for a in n.args],
                        "kw": {k.arg: ast.unparse(k.value) for k in n.keywords}, "line": n.lineno})
    return out


def wiring(fn: ast.FunctionDef) -> list[str]:
    """Statements of build after its with-block (inputs, outputs, events, return)."""
    idx = max(i for i, s in enumerate(fn.body) if isinstance(s, ast.With))
    return [ast.unparse(s) for s in fn.body[idx + 1:]]


def strings(tree: ast.Module) -> set[str]:
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(n, clean=False)
            if d is not None:
                docs.add(d)
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)} - docs


def main() -> int:
    old_src, new_src = OLD.read_text(encoding="utf-8"), NEW.read_text(encoding="utf-8")
    print("=== unified diff (backup_pre_c -> current) ===")
    for line in difflib.unified_diff(old_src.splitlines(), new_src.splitlines(), "backup_pre_c/twin/ui/ask.py",
                                     "twin/ui/ask.py", lineterm="", n=1):
        print(line)
    old_t, new_t = ast.parse(old_src), ast.parse(new_src)
    old_top, new_top = top_level(old_t), top_level(new_t)
    fails = []
    print("\n=== top-level definitions ===")
    for name, node in old_top.items():
        if name not in new_top:
            print(f"MISSING {name}")
            fails.append(f"missing {name}")
            continue
        same = dump(node) == dump(new_top[name])
        print(f"{'EQUAL  ' if same else 'CHANGED'} {name}")
        if not same and name != "build":
            fails.append(f"changed {name}")
    for name in new_top:
        if name not in old_top:
            print(f"NEW     {name}")
    print("\n=== build(): gr.* components ===")
    old_calls = {c["key"]: c for c in gr_calls(old_top["build"])}
    new_calls = {c["key"]: c for c in gr_calls(new_top["build"])}
    for key, oc in old_calls.items():
        nc = new_calls.get(key)
        if nc is None:
            # layout wrappers without a bound name are matched by kind order; report instead of failing
            print(f"  (unbound) {key}: {oc['kind']} {oc['kw']} -> not matched by key")
            continue
        diffs = []
        if oc["args"] != nc["args"]:
            diffs.append(f"args {oc['args']} -> {nc['args']}")
            fails.append(f"{key}: positional args changed")
        for k in sorted(set(oc["kw"]) | set(nc["kw"])):
            a, b = oc["kw"].get(k), nc["kw"].get(k)
            if a == b:
                continue
            tag = "layout" if k in LAYOUT_KW else "NON-LAYOUT"
            diffs.append(f"{tag} {k}: {a} -> {b}")
            if k not in LAYOUT_KW and a is not None:
                fails.append(f"{key}: {k} changed {a} -> {b}")
        print(f"  {key} ({oc['kind']}): {'unchanged' if not diffs else '; '.join(diffs)}")
    for key, nc in new_calls.items():
        if key not in old_calls:
            print(f"  NEW {key} ({nc['kind']}): {nc['kw']}")
    print("\n=== wiring after the tab block ===")
    ow, nw = wiring(old_top["build"]), wiring(new_top["build"])
    print("EQUAL" if ow == nw else "DIFFERENT")
    if ow != nw:
        fails.append("wiring differs")
        for line in difflib.unified_diff(ow, nw, lineterm=""):
            print(line)
    print("\n=== string constants of the backup still present ===")
    lost = sorted(strings(old_t) - strings(new_t))
    print(f"lost: {lost}")
    if lost:
        fails.append(f"lost strings {lost}")
    print("\n=== elem_ids ===")
    old_ids = set(re.findall(r'elem_id="([^"]+)"', old_src))
    new_ids = set(re.findall(r'elem_id="([^"]+)"', new_src))
    print(f"backup: {sorted(old_ids)}; current: {sorted(new_ids)}; missing: {sorted(old_ids - new_ids)}")
    if old_ids - new_ids:
        fails.append("elem_ids missing")
    print("\n=== DEMO.md sections 3-4 bold labels ===")
    demo = DEMO.read_text(encoding="utf-8")
    sec = demo[demo.index("## 3. Never click live"):demo.index("\n## 5.")]
    bold = sorted(set(re.findall(r"\*\*([^*]+?)\*\*", sec)))
    old_hits = [b for b in bold if b in old_src]
    new_hits = [b for b in bold if b in new_src]
    print(f"bold labels in 3-4: {len(bold)}; in backup ask.py: {old_hits}; in current ask.py: {new_hits}")
    regress = sorted(set(old_hits) - set(new_hits))
    print(f"regression: {regress}")
    if regress:
        fails.append(f"bold labels lost {regress}")
    print(f"\nFROZEN_FAILURES {len(fails)}: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

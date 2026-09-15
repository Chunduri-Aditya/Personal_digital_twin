"""Review of lane act_see, round 1 (read-only): DEMO CONTRACT diff of twin/ui/act.py and twin/ui/see.py against
scripts/dev/finish/backup_pre_c, plus the DEMO.md sections 3-4 bold labels.

Run: python scripts/dev/finish/review_act_see_contract.py   (exit 0 = no frozen change)
"""
from __future__ import annotations

import ast
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
MODULES = ["twin/ui/act.py", "twin/ui/see.py"]
LAYOUT_KW = {"elem_id", "elem_classes", "scale", "min_width"}
LAYOUT_TYPES = {"Row", "Column", "Group", "Accordion"}
EVENTS = {"click", "change", "submit", "select", "load", "then", "success", "input", "upload", "clear", "tick"}


def src(node, text):
    return ast.get_source_segment(text, node)


def components(tree, text):
    """{var_name: (type, frozen kwargs)} for gr.* calls, plus a list of unnamed gr.* calls (layout wrappers)."""
    named, unnamed = {}, []
    for node in ast.walk(tree):
        call, target = None, None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call, target = node.value, node.targets[0]
        elif isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
            call, target = node.context_expr, node.optional_vars
        if call is None:
            continue
        f = call.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "gr"):
            continue
        pos = tuple(src(a, text) for a in call.args)
        kw = {k.arg: src(k.value, text) for k in call.keywords}
        frozen = {k: v for k, v in kw.items() if k not in LAYOUT_KW}
        layout = {k: v for k, v in kw.items() if k in LAYOUT_KW}
        entry = (f.attr, pos, tuple(sorted(frozen.items())), tuple(sorted(layout.items())))
        if isinstance(target, ast.Name):
            named[target.id] = entry
        else:
            unnamed.append(entry)
    return named, unnamed


def events(tree, text):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in EVENTS \
                and not (isinstance(node.func.value, ast.Name) and node.func.value.id == "gr"):
            out.append((src(node.func.value, text), node.func.attr,
                        tuple(src(a, text) for a in node.args),
                        tuple(sorted((k.arg, src(k.value, text)) for k in node.keywords))))
    return sorted(out)


def functions(tree, text):
    return {n.name: src(n, text) for n in tree.body if isinstance(n, ast.FunctionDef)}


def build_return(tree, text):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "build":
            rets = [src(r, text) for r in ast.walk(n) if isinstance(r, ast.Return)]
            return rets
    return []


def strings(tree):
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def elem_ids(tree, text):
    return {k.value.value for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords
            if k.arg == "elem_id" and isinstance(k.value, ast.Constant)}


def demo_bold_labels():
    text = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    start = re.search(r"^## 3\.", text, re.M)
    end = re.search(r"^## 5\.", text, re.M)
    section = text[start.start():end.start()] if start and end else text
    return sorted(set(re.findall(r"\*\*(.+?)\*\*", section)))


def main() -> int:
    frozen_fail = []
    all_new_strings, all_old_strings = set(), set()
    for rel in MODULES:
        new_text = (ROOT / rel).read_text(encoding="utf-8")
        old_text = (BACKUP / rel).read_text(encoding="utf-8")
        new_tree, old_tree = ast.parse(new_text), ast.parse(old_text)
        print(f"===== {rel}")
        diff = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), "backup_pre_c/" + rel, rel,
                                         lineterm="", n=0))
        print("\n".join(diff))
        on, ou = components(old_tree, old_text)
        nn, nu = components(new_tree, new_text)
        for name in sorted(set(on) | set(nn)):
            if name not in nn:
                frozen_fail.append(f"{rel}: component {name} removed")
                continue
            if name not in on:
                t = nn[name][0]
                (print if t in LAYOUT_TYPES else frozen_fail.append)(f"{rel}: new named component {name} = gr.{t}")
                continue
            if on[name][:3] != nn[name][:3]:
                frozen_fail.append(f"{rel}: {name} changed frozen args: {on[name][:3]} -> {nn[name][:3]}")
            else:
                print(f"{rel}: {name} gr.{nn[name][0]} frozen args EQUAL {dict(nn[name][2])}; "
                      f"layout {dict(on[name][3])} -> {dict(nn[name][3])}")
        # unnamed calls: wrappers (Row/Column/Group) and 'with gr.Accordion(...)' without 'as'
        old_un = [(t, p, f) for t, p, f, _ in ou]
        new_un = [(t, p, f) for t, p, f, _ in nu]
        for t, p, f in new_un:
            if t not in LAYOUT_TYPES:
                frozen_fail.append(f"{rel}: new unnamed non-layout gr.{t}{p} {f}")
        for item in old_un:
            if item not in new_un:
                frozen_fail.append(f"{rel}: unnamed wrapper changed or removed: {item}")
        print(f"{rel}: unnamed wrappers backup {len(old_un)} -> now {len(new_un)}: "
              f"{[(t, p, dict(f)) for t, p, f in new_un]}")
        oe, ne = events(old_tree, old_text), events(new_tree, new_text)
        print(f"{rel}: events EQUAL={oe == ne}")
        for e in ne:
            print("   ", e)
        if oe != ne:
            frozen_fail.append(f"{rel}: events differ: {oe} -> {ne}")
        of, nf = functions(old_tree, old_text), functions(new_tree, new_text)
        for fn in sorted(set(of) | set(nf)):
            if fn == "build":
                continue
            same = of.get(fn) == nf.get(fn)
            print(f"{rel}: def {fn} source EQUAL={same}")
            if not same:
                frozen_fail.append(f"{rel}: handler {fn} source changed")
        orr, nr = build_return(old_tree, old_text), build_return(new_tree, new_text)
        print(f"{rel}: build() return EQUAL={orr == nr}")
        if orr != nr:
            frozen_fail.append(f"{rel}: build() return changed")
        oid, nid = elem_ids(old_tree, old_text), elem_ids(new_tree, new_text)
        print(f"{rel}: elem_ids backup {sorted(oid)} -> now {sorted(nid)}; missing {sorted(oid - nid)}")
        if oid - nid:
            frozen_fail.append(f"{rel}: elem_ids removed {sorted(oid - nid)}")
        all_new_strings |= strings(new_tree)
        all_old_strings |= strings(old_tree)
    labels = demo_bold_labels()
    in_old = [l for l in labels if l in all_old_strings]
    missing = [l for l in in_old if l not in all_new_strings]
    print(f"DEMO.md sections 3-4: {len(labels)} bold strings; in backup act/see modules: {in_old}; "
          f"missing now: {missing}")
    if missing:
        frozen_fail.append(f"DEMO bold labels missing: {missing}")
    print("FROZEN_FAILURES:", len(frozen_fail))
    for f in frozen_fail:
        print("  " + f)
    return 1 if frozen_fail else 0


if __name__ == "__main__":
    sys.exit(main())

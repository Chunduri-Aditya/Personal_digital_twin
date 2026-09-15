"""Review r1 of lane onboarding_items (docs/PLAN_FINISH.md P4): DEMO CONTRACT diff of twin/ui/onboarding.py and
twin/ui/items.py against scripts/dev/finish/backup_pre_c/<same path>. Read-only: no app, no model.

Checks: a unified diff; every top-level statement except build() identical (docstrings ignored); build() identical
once the style-only gr.* keywords (elem_classes, variant, scale) are dropped; per gr.* call keyword changes classified;
event wiring identical; every backup elem_id still present; every bold label in docs/DEMO.md sections 3-4 that these
modules rendered before still present; the B1.1 step labels unchanged.

Run (project root): python scripts/dev/finish/review_oi_r1_diff.py    Exit 0 when no contract problem."""
import ast
import copy
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
MODS = ["twin/ui/onboarding.py", "twin/ui/items.py"]
STYLE_KW = {"elem_classes", "variant", "scale"}
EVENT_ATTRS = {"click", "change", "submit", "select", "input", "then", "success", "upload", "expand", "collapse",
               "blur", "focus", "load", "release", "stream"}


def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                node.body = b[1:] or [ast.Pass()]
    return tree


class DropStyle(ast.NodeTransformer):
    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "gr":
            node.keywords = [k for k in node.keywords if k.arg not in STYLE_KW]
        return node


def is_gr(n):
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
        and n.func.value.id == "gr"


def ordered(nodes):
    return sorted(nodes, key=lambda n: (n.lineno, n.col_offset))


def top_level(tree):
    out = {}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[f"def {n.name}"] = n
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            tg = n.targets if isinstance(n, ast.Assign) else [n.target]
            out["assign " + ",".join(ast.unparse(t) for t in tg)] = n
        else:
            out["stmt " + ast.unparse(n)[:80]] = n
    return out


def main() -> int:
    problems, notes = [], []
    src_now, src_old = {}, {}
    for mod in MODS:
        new_p, old_p = ROOT / mod, BACKUP / mod
        new, old = new_p.read_text(encoding="utf-8"), old_p.read_text(encoding="utf-8")
        src_now[mod], src_old[mod] = new, old
        print(f"===== {mod} vs backup_pre_c/{mod}")
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(), f"backup/{mod}", mod, n=0, lineterm=""):
            print("  " + line)
        t_new, t_old = strip_docstrings(ast.parse(new)), strip_docstrings(ast.parse(old))
        top_new, top_old = top_level(t_new), top_level(t_old)
        for k in sorted(set(top_new) | set(top_old)):
            if k not in top_new:
                problems.append(f"{mod}: top-level {k!r} removed")
            elif k not in top_old:
                problems.append(f"{mod}: top-level {k!r} added")
            elif k != "def build" and ast.dump(top_new[k]) != ast.dump(top_old[k]):
                problems.append(f"{mod}: top-level {k!r} changed (handler, constant or label outside build)")
        same_outside = [k for k in top_new if k != "def build" and k in top_old and ast.dump(top_new[k]) == ast.dump(top_old[k])]
        notes.append(f"{mod}: {len(same_outside)} top-level statements outside build() identical to the backup (docstrings ignored)")

        b_new, b_old = top_new.get("def build"), top_old.get("def build")
        if b_new is None or b_old is None:
            problems.append(f"{mod}: build() missing")
            continue
        n_norm = ast.dump(DropStyle().visit(copy.deepcopy(b_new)))
        o_norm = ast.dump(DropStyle().visit(copy.deepcopy(b_old)))
        if n_norm == o_norm:
            notes.append(f"{mod}: build() identical to the backup once elem_classes/variant/scale are dropped")
        else:
            problems.append(f"{mod}: build() differs beyond elem_classes/variant/scale (see gr.* call list below)")

        c_new = ordered([n for n in ast.walk(b_new) if is_gr(n)])
        c_old = ordered([n for n in ast.walk(b_old) if is_gr(n)])
        if [c.func.attr for c in c_new] != [c.func.attr for c in c_old]:
            problems.append(f"{mod}: gr.* call sequence changed: {[c.func.attr for c in c_old]} -> {[c.func.attr for c in c_new]}")
        for cn, co in zip(c_new, c_old):
            kn = {k.arg: ast.unparse(k.value) for k in cn.keywords}
            ko = {k.arg: ast.unparse(k.value) for k in co.keywords}
            if [ast.dump(a) for a in cn.args] != [ast.dump(a) for a in co.args]:
                problems.append(f"{mod}:{cn.lineno} gr.{cn.func.attr} positional args changed: "
                                f"{[ast.unparse(a) for a in co.args]} -> {[ast.unparse(a) for a in cn.args]}")
            for key in sorted(set(kn) | set(ko)):
                if kn.get(key) == ko.get(key):
                    continue
                change = f"{mod}:{cn.lineno} gr.{cn.func.attr} {key}: {ko.get(key)!s} -> {kn.get(key)!s}"
                if key == "elem_classes":
                    notes.append("style keyword (allowed): " + change)
                elif key in ("variant", "scale"):
                    notes.append("style keyword (frame contract: secondary/.twin-caution, scale=0 in .twin-actions): " + change)
                elif key == "elem_id" and ko.get(key) is None:
                    notes.append("elem_id added (allowed): " + change)
                else:
                    problems.append("contract keyword changed: " + change)

        e_new = [ast.unparse(c) for c in ordered([n for n in ast.walk(b_new) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr in EVENT_ATTRS and not is_gr(n)])]
        e_old = [ast.unparse(c) for c in ordered([n for n in ast.walk(b_old) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr in EVENT_ATTRS and not is_gr(n)])]
        if e_new == e_old:
            notes.append(f"{mod}: event wiring identical ({len(e_new)} calls): " + " | ".join(e_new))
        else:
            problems.append(f"{mod}: event wiring changed: {e_old} -> {e_new}")

        ids_new = set(re.findall(r"elem_id=(f?\"[^\"]*\")", new))
        ids_old = set(re.findall(r"elem_id=(f?\"[^\"]*\")", old))
        missing = sorted(ids_old - ids_new)
        if missing:
            problems.append(f"{mod}: elem_ids removed: {missing}")
        notes.append(f"{mod}: elem_ids backup {len(ids_old)}, now {len(ids_new)}, removed {missing}, added {sorted(ids_new - ids_old)}")

    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8").splitlines()
    s = next(i for i, l in enumerate(demo) if l.startswith("## 3."))
    e = next(i for i, l in enumerate(demo) if l.startswith("## 5."))
    labels = sorted({m.group(1) for l in demo[s:e] for m in re.finditer(r"\*\*(.+?)\*\*", l)})
    ours = []
    for lab in labels:
        clean = lab.strip().rstrip(":")
        was = [m for m in MODS if clean and clean in src_old[m]]
        now = [m for m in MODS if clean and clean in src_now[m]]
        if was:
            ours.append(clean)
            if set(was) - set(now):
                problems.append(f"DEMO.md sections 3-4 bold label {clean!r} no longer in {sorted(set(was) - set(now))}")
    notes.append(f"DEMO.md sections 3-4: {len(labels)} bold labels; rendered by these modules and still present: {ours}")

    b11 = next((l for l in demo[s:e] if l.startswith("| B1.1 ")), "")
    quoted = re.findall(r'"(\d\. [^"]+)"', b11)
    for q in quoted:
        if q not in src_now["twin/ui/onboarding.py"]:
            problems.append(f"B1.1 step label {q!r} not in twin/ui/onboarding.py")
    notes.append(f"B1.1 quoted step labels checked against onboarding.py: {quoted}")
    for needle in ("Done.", "Indexes for", "digest {digest}", "Ground truth: ", "ceiling pending", "retest ceiling: "):
        both = [m for m in MODS if needle in src_old[m]]
        if both and not all(needle in src_now[m] for m in both):
            problems.append(f"output string fragment {needle!r} changed")

    for n in notes:
        print("NOTE " + n)
    for p in problems:
        print("PROBLEM " + p)
    print(f"demo-contract diff: {'PASS' if not problems else 'FAIL'} ({len(problems)} problems)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

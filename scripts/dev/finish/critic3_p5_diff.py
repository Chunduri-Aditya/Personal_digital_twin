"""P5 critic 3 (correctness), read-only scratch helper: compare twin/ui/*.py with scripts/dev/finish/backup_pre_c.

Writes scripts/dev/finish/critic3_p5_diff.txt with:
  1. per-file unified diff line counts,
  2. an AST inventory of component constructors (gr.X(...) with label/placeholder/value/choices/info/...),
     event wirings (.click/.submit/.change/.select/.tick/.load/.then/.upload/.input/...), their fn, inputs,
     outputs, api_name, concurrency_id, and the string literals, with the differences between the two trees,
  3. the full unified diffs (for reading).
Nothing in the project is modified.
"""
from __future__ import annotations

import ast
import difflib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CUR = ROOT / "twin" / "ui"
BAK = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c" / "twin" / "ui"
OUT = ROOT / "scripts" / "dev" / "finish" / "critic3_p5_diff.txt"

EVENTS = {"click", "submit", "change", "select", "tick", "load", "then", "success", "upload", "input", "blur",
          "focus", "release", "stream", "clear", "like", "retry", "undo", "edit", "key_up", "stop", "on"}
KW_COMP = ("label", "placeholder", "value", "choices", "info", "elem_id", "interactive", "visible", "lines",
           "max_lines", "minimum", "maximum", "step", "type", "sources", "headers", "open", "selected", "id")
KW_EVT = ("fn", "inputs", "outputs", "api_name", "concurrency_id", "concurrency_limit", "queue", "show_progress",
          "trigger_mode", "js", "preprocess", "postprocess")


def src(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return "<?>"


def inventory(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    comps, events, strings = [], [], Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings[node.value] += 1
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "gr":
            kw = {k.arg: src(k.value) for k in node.keywords if k.arg in KW_COMP}
            pos = [src(a) for a in node.args]
            comps.append(f"gr.{f.attr}(pos={pos}, {sorted(kw.items())})")
        elif isinstance(f, ast.Attribute) and f.attr in EVENTS:
            kw = {k.arg: src(k.value) for k in node.keywords if k.arg in KW_EVT}
            pos = [src(a) for a in node.args]
            events.append(f"{src(f.value)}.{f.attr}(pos={pos}, {sorted(kw.items())})")
    return comps, events, strings


def returns_of(path: Path) -> dict[str, list[str]]:
    """function name -> list of 'return <expr>' source lines (handlers' outputs)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rets = [src(n) for n in ast.walk(node) if isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom))]
            out.setdefault(node.name, []).extend(rets)
    return out


def main() -> int:
    lines: list[str] = []
    full: list[str] = []
    files = sorted({p.name for p in CUR.glob("*.py")} | {p.name for p in BAK.glob("*.py")})
    for name in files:
        c, b = CUR / name, BAK / name
        if not c.exists() or not b.exists():
            lines.append(f"== {name}: present current={c.exists()} backup={b.exists()}")
            continue
        ct = c.read_text(encoding="utf-8").splitlines()
        bt = b.read_text(encoding="utf-8").splitlines()
        diff = list(difflib.unified_diff(bt, ct, f"backup/{name}", f"current/{name}", lineterm="", n=2))
        plus = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        minus = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        lines.append(f"== {name}: +{plus} -{minus}")
        bc, be, bs = inventory(b)
        cc, ce, cs = inventory(c)
        for label, old, new in (("components", bc, cc), ("events", be, ce)):
            oc, nc = Counter(old), Counter(new)
            removed = list((oc - nc).elements())
            added = list((nc - oc).elements())
            lines.append(f"   {label}: backup {len(old)} current {len(new)}; removed {len(removed)} added {len(added)}")
            for r in removed:
                lines.append(f"     - {r}")
            for a in added:
                lines.append(f"     + {a}")
        rs = sorted(set(bs) - set(cs))
        ad = sorted(set(cs) - set(bs))
        lines.append(f"   string literals removed {len(rs)} added {len(ad)}")
        for s in rs:
            lines.append(f"     - {s!r}"[:400])
        for s in ad:
            lines.append(f"     + {s!r}"[:400])
        br, cr = returns_of(b), returns_of(c)
        for fn in sorted(set(br) | set(cr)):
            if Counter(br.get(fn, [])) != Counter(cr.get(fn, [])):
                lines.append(f"   returns differ in {fn}():")
                for r in (Counter(br.get(fn, [])) - Counter(cr.get(fn, []))).elements():
                    lines.append(f"     - {r}"[:400])
                for r in (Counter(cr.get(fn, [])) - Counter(br.get(fn, []))).elements():
                    lines.append(f"     + {r}"[:400])
        full.extend(diff)
        full.append("")
    OUT.write_text("\n".join(lines) + "\n\n==== FULL DIFFS ====\n" + "\n".join(full), encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

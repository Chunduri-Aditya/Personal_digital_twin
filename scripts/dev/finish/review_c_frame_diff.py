"""Review helper (P3 frame, round 1): diff twin/ui/frame.py against the pre-restyle backup and check that the
frozen functions and constants are byte-identical by AST source segment. Reads files only; no app, no model."""
from __future__ import annotations

import ast
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NEW = ROOT / "twin" / "ui" / "frame.py"
OLD = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c" / "twin" / "ui" / "frame.py"

FROZEN = ("_gpu_mib", "_key_loaded", "heartbeat_state", "_loaded_lists", "strip_markdown", "make_tab_select",
          "default_tab", "_on_page_load", "tab_js", "_TAB_JS_TEMPLATE", "TAB_JS", "NEW_API_NAMES",
          "CONDITION_ENDPOINTS", "TAB_IDS", "TAB_LABELS", "TAB_MODULES", "GPU_SELECT_TABS", "GPU_TOTAL_MIB",
          "HEARTBEAT_STATES")


def segments(path: Path) -> dict[str, str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = ast.get_source_segment(src, node) or ""
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = ast.get_source_segment(src, node) or ""
    return out


def calls_in_build_app(path: Path) -> list[str]:
    """Every event-wiring call (.select/.tick/.load/.click/.submit/.change) inside build_app, normalised by ast.dump."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_app")
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                "select", "tick", "load", "click", "submit", "change", "then"):
            out.append(ast.unparse(node))
    return sorted(out)


def elem_ids(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "elem_id" and isinstance(node.value, ast.Constant):
            ids.append(node.value.value)
    return ids


def main() -> int:
    old_lines = OLD.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = NEW.read_text(encoding="utf-8").splitlines(keepends=True)
    print("==== unified diff (backup_pre_c -> current) ====")
    sys.stdout.writelines(difflib.unified_diff(old_lines, new_lines, "backup_pre_c/twin/ui/frame.py",
                                               "twin/ui/frame.py", n=1))
    print("\n==== frozen names (AST source segment equal?) ====")
    so, sn = segments(OLD), segments(NEW)
    bad = 0
    for name in FROZEN:
        eq = so.get(name) == sn.get(name) and name in so
        bad += 0 if eq else 1
        print(f"{name:22s} {'EQUAL' if eq else 'DIFFERENT'}")
    print("\n==== names only in one version ====")
    print("only old:", sorted(set(so) - set(sn)))
    print("only new:", sorted(set(sn) - set(so)))
    print("\n==== event wiring calls in build_app ====")
    co, cn = calls_in_build_app(OLD), calls_in_build_app(NEW)
    print("EQUAL" if co == cn else "DIFFERENT")
    for c in cn:
        print("  ", c)
    if co != cn:
        bad += 1
        print("old:", co)
    print("\n==== elem_ids ====")
    print("old:", elem_ids(OLD))
    print("new:", elem_ids(NEW))
    need = {"twin-header", "gpu-note", "status-strip", "twin-tabs"}
    missing = need - set(elem_ids(NEW))
    print("missing required:", sorted(missing))
    bad += len(missing)
    # tab-<id> elem_ids come from the tab modules
    tab_ids = []
    for f in sorted((ROOT / "twin" / "ui").glob("*.py")):
        tab_ids += [i for i in elem_ids(f) if i.startswith("tab-")]
    print("tab-<id> elem_ids in twin/ui/*.py:", sorted(set(tab_ids)))
    print("\nFROZEN_FAILURES", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

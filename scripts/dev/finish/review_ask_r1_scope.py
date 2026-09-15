"""Review of the ask lane, round 1: scoping, internal selectors and tokens in static/tabs/ask.css. Read-only.

Prints every selector with its line, fails any that does not start with #tab-ask (or body.dark #tab-ask), greps
for Gradio internal selectors, and flags colour, font, radius, shadow and motion literals outside --twin-* tokens.
Writes scripts/dev/shots/lane_ask/review_r1/scope_tokens.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = ROOT / "static" / "tabs" / "ask.css"
TWIN_CSS = ROOT / "static" / "twin.css"
THEME_PY = ROOT / "twin" / "ui" / "theme.py"
OUT = ROOT / "scripts" / "dev" / "shots" / "lane_ask" / "review_r1" / "scope_tokens.json"

INTERNAL = ("svelte-", ".block", ".gradio-container", ".prose", ".wrap", ".gr-")
OUR_CLASSES = {"trace", "twin-panel", "twin-actions", "twin-quiet", "twin-hint", "ask-empty", "ask-empty-mark",
               "ask-empty-text", "ask-empty-title"}
NAMED = ("white", "black", "red", "green", "blue", "gray", "grey", "silver", "orange", "yellow", "purple", "pink",
         "brown", "navy", "teal", "maroon", "olive", "lime", "aqua", "fuchsia", "beige", "ivory", "gold", "tan",
         "coral", "crimson", "cyan", "magenta", "violet", "indigo", "khaki", "salmon", "plum", "orchid", "lavender",
         "linen", "snow", "wheat", "whitesmoke", "gainsboro")
COLOUR_PROPS = ("color", "background", "background-color", "border", "border-color", "border-top", "border-left",
                "border-right", "border-bottom", "outline", "outline-color", "fill", "stroke", "box-shadow", "filter",
                "text-decoration", "caret-color", "accent-color")


def strip_comments_keep_lines(s: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), s, flags=re.S)


def split_top(s: str, sep: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def rules(text: str) -> list[dict]:
    s = strip_comments_keep_lines(text)
    out, stack, buf, start, i = [], [], [], None, 0
    while i < len(s):
        c = s[i]
        if c == "{":
            prelude = " ".join("".join(buf).split())
            line = s.count("\n", 0, start if start is not None else i) + 1
            buf, start = [], None
            if prelude.startswith("@"):
                stack.append(prelude)
                i += 1
                continue
            j = s.index("}", i)
            out.append({"media": list(stack), "prelude": prelude, "body": s[i + 1:j], "line": line})
            i = j + 1
            continue
        if c == "}":
            if stack:
                stack.pop()
            buf, start = [], None
            i += 1
            continue
        if start is None and not c.isspace():
            start = i
        buf.append(c)
        i += 1
    return out


def declared_twin_tokens() -> set[str]:
    names = set(re.findall(r"(--twin-[\w-]+)\s*:", TWIN_CSS.read_text(encoding="utf-8")))
    names |= set(re.findall(r"(--twin-[\w-]+)", THEME_PY.read_text(encoding="utf-8")))
    return names


def main() -> int:
    raw = CSS.read_text(encoding="utf-8")
    declared = declared_twin_tokens()
    report = {"file": str(CSS), "selectors": [], "scope_fail": [], "internal_in_selectors": [],
              "internal_raw_text": [], "foreign_classes": [], "hard": [], "info": [], "vars_used": [],
              "undeclared_twin_vars": [], "custom_props_set": []}
    for r in rules(raw):
        for sel in split_top(r["prelude"], ","):
            report["selectors"].append({"line": r["line"], "media": r["media"], "selector": sel})
            if not re.match(r"^(body\.dark\s+)?#tab-ask(?![\w-])", sel):
                report["scope_fail"].append({"line": r["line"], "selector": sel})
            for bad in INTERNAL:
                if bad in sel:
                    report["internal_in_selectors"].append({"line": r["line"], "selector": sel, "hit": bad})
            for cls in re.findall(r"\.([A-Za-z_][\w-]*)", re.sub(r"\"[^\"]*\"|'[^']*'", "", sel)):
                if cls not in OUR_CLASSES:
                    report["foreign_classes"].append({"line": r["line"], "selector": sel, "class": cls})
        for decl in split_top(r["body"], ";"):
            if ":" not in decl:
                continue
            prop, val = (x.strip() for x in decl.split(":", 1))
            where = {"line": r["line"], "selector": r["prelude"][:90], "decl": f"{prop}: {val}"}
            if prop.startswith("--"):
                report["custom_props_set"].append(where)
                if prop.startswith("--twin-"):
                    report["hard"].append({**where, "why": "redefines a --twin-* token"})
            for v in re.findall(r"var\((--[\w-]+)", val):
                report["vars_used"].append(v)
                if v.startswith("--twin-") and v not in declared:
                    report["undeclared_twin_vars"].append({**where, "var": v})
                if not v.startswith("--twin-"):
                    report["hard"].append({**where, "why": f"reads a non-token variable {v}"})
            if re.search(r"#[0-9a-fA-F]{3,8}\b", val):
                report["hard"].append({**where, "why": "hex colour literal"})
            if re.search(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\(", val):
                report["hard"].append({**where, "why": "functional colour literal"})
            if prop in COLOUR_PROPS or prop.startswith("--"):
                for name in NAMED:
                    if re.search(rf"(?<![\w-]){name}(?![\w-])", val):
                        report["hard"].append({**where, "why": f"named colour {name}"})
            if prop in ("font-family", "font") and not re.fullmatch(r"(var\(--twin-font-[\w-]+\)|inherit)", val):
                report["hard"].append({**where, "why": "font family not from --twin-font-*"})
            if prop == "box-shadow" and not re.fullmatch(r"(none|var\(--twin-shadow-[\w-]+\))", val):
                report["hard"].append({**where, "why": "box-shadow literal"})
            if prop.startswith("border") and "radius" in prop and not re.fullmatch(r"(0|var\(--twin-radius-[\w-]+\))", val):
                report["hard"].append({**where, "why": "radius literal"})
            if prop.startswith(("transition", "animation")):
                report["info"].append({**where, "why": "motion declaration"})
            if "!important" in val:
                report["hard"].append({**where, "why": "!important"})
            if re.search(r"(?<![\w.-])\d*\.?\d+(px|rem|em|ch|%)?(?![\w-])", val) and "var(" not in val \
                    and prop not in ("content",):
                report["info"].append({**where, "why": "literal length or number"})
            elif re.search(r"\d+(px|ch)", val):
                report["info"].append({**where, "why": "literal length inside a token expression"})
    for bad in INTERNAL:
        for n, line in enumerate(raw.splitlines(), 1):
            if bad in line:
                report["internal_raw_text"].append({"line": n, "hit": bad, "text": line.strip()})
    report["vars_used"] = sorted(set(report["vars_used"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"selectors: {len(report['selectors'])}")
    for s in report["selectors"]:
        print(f"  {s['line']:>4} {'@' + s['media'][0] + ' ' if s['media'] else ''}{s['selector']}")
    print(f"scope_fail: {report['scope_fail']}")
    print(f"internal_in_selectors: {report['internal_in_selectors']}")
    print(f"internal_raw_text (Select-String equivalent): {report['internal_raw_text']}")
    print(f"foreign_classes: {report['foreign_classes']}")
    print(f"custom_props_set: {[c['decl'] for c in report['custom_props_set']]}")
    print(f"undeclared_twin_vars: {report['undeclared_twin_vars']}")
    print(f"HARD ({len(report['hard'])}):")
    for h in report["hard"]:
        print(f"  {h['line']:>4} {h['why']}: {h['decl']}")
    print(f"INFO ({len(report['info'])}):")
    for h in report["info"]:
        print(f"  {h['line']:>4} {h['why']}: {h['decl']}")
    print(f"SCOPING_OK={not report['scope_fail']}")
    return 0 if not report["scope_fail"] and not report["internal_in_selectors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

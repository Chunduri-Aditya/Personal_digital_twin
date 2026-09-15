"""Review helper (read-only): independent selector scope, internal-selector and tokens-only check over
static/tabs/eval.css and static/tabs/status.css. Uses its own brace parser (not the lane's helper and not the
tests/test_theme.py parser) so a shared parser bug cannot hide a finding. Writes nothing but stdout."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PARTIALS = {"eval": ROOT / "static" / "tabs" / "eval.css", "status": ROOT / "static" / "tabs" / "status.css"}
FORBIDDEN = ["svelte-", ".block", ".gradio-container", ".prose", ".wrap", ".gr-"]
COLOUR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\blab\(")
NAMED = {"white", "black", "red", "blue", "green", "gray", "grey", "orange", "yellow", "purple", "brown", "pink",
         "silver", "navy", "teal", "maroon", "olive", "lime", "aqua", "fuchsia"}


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), css, flags=re.S)


def rules(css: str):
    """Yield (selector_text, declarations, line) for style rules, descending into @media blocks."""
    i, n, line = 0, len(css), 1
    stack = []
    buf_start = 0
    while i < n:
        ch = css[i]
        if ch == "{":
            head = css[buf_start:i].strip()
            head_line = line - css[buf_start:i].rstrip().count("\n") + css[buf_start:i].lstrip("\n").count("\n") * 0
            if head.startswith("@"):
                stack.append(("at", head))
                buf_start = i + 1
            else:
                j = css.index("}", i)
                decls = css[i + 1:j]
                yield head, decls, line - 0, [s for s in stack]
                line += css[i:j + 1].count("\n")
                i = j + 1
                buf_start = i
                continue
        elif ch == "}":
            if stack:
                stack.pop()
            buf_start = i + 1
        if ch == "\n":
            line += 1
        i += 1


def split_selectors(sel: str):
    out, depth, cur = [], 0, ""
    for ch in sel:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        if ch == "\n":
            pass
    if cur.strip():
        out.append(cur.strip())
    return out


total_fail = 0
for tab, path in PARTIALS.items():
    raw = path.read_text(encoding="utf-8")
    css = strip_comments(raw)
    n_rules = n_sel = 0
    unscoped, forb, literals, fonts, radii, shadows, raw_hits = [], [], [], [], [], [], []
    prefix = f"#tab-{tab}"
    for sel, decls, line, stack in rules(css):
        n_rules += 1
        for s in split_selectors(sel):
            n_sel += 1
            s1 = " ".join(s.split())
            ok = s1 == prefix or s1.startswith(prefix + " ") or s1.startswith(prefix + ">") \
                 or s1.startswith(prefix + ".") or s1.startswith(prefix + ":") or s1.startswith(prefix + "[") \
                 or s1.startswith("body.dark " + prefix)
            # prefix must be the full id token (not #tab-evalx)
            if ok and re.match(re.escape(prefix) + r"[\w-]", s1.replace("body.dark ", "", 1)):
                ok = False
            if not ok:
                unscoped.append(s1)
            for f in FORBIDDEN:
                if f in s1:
                    forb.append((f, s1))
        for d in decls.split(";"):
            if ":" not in d:
                continue
            prop, val = d.split(":", 1)
            prop, val = prop.strip().lower(), val.strip()
            if COLOUR_RE.search(val):
                literals.append(f"{prop}: {val}")
            words = set(re.findall(r"[a-zA-Z]+", re.sub(r"var\([^)]*\)", "", val)))
            if prop in ("color", "background", "background-color", "border", "border-color", "border-bottom",
                        "border-top", "outline", "fill", "stroke", "box-shadow") and words & NAMED:
                literals.append(f"{prop}: {val}")
            if prop in ("font-family", "font") and "var(--twin-font" not in val and val not in ("inherit",):
                fonts.append(f"{prop}: {val}")
            if prop.startswith("border") and "radius" in prop and "var(--twin-radius" not in val and val not in ("0", "inherit"):
                radii.append(f"{prop}: {val}")
            if prop == "box-shadow" and "var(--twin-shadow" not in val and val not in ("none", "0"):
                shadows.append(f"{prop}: {val}")
            if prop.startswith("--twin-"):
                literals.append(f"REDEFINES {prop}")
            if "!important" in val:
                literals.append(f"!important in {prop}: {val}")
            px = re.findall(r"(?<![\w-])(\d+(?:\.\d+)?)px", val)
            if px and not prop.startswith("--block") and any(p not in ("0", "1") for p in px):
                raw_hits.append(f"{prop}: {val}")
    # literal grep over the raw file including comments (the test's regex scans comments too)
    raw_forbidden = [f for f in FORBIDDEN if f in raw]
    print(f"{path.relative_to(ROOT)}: {n_rules} rules, {n_sel} selectors")
    print(f"  unscoped: {unscoped}")
    print(f"  forbidden in selectors: {forb}; forbidden literal anywhere in file (incl. comments): {raw_forbidden}")
    print(f"  colour literals / redefinitions / !important: {literals}")
    print(f"  non-token font: {fonts}; non-token radius: {radii}; non-token shadow: {shadows}")
    print(f"  raw px values (informational, not colours): {raw_hits}")
    fail = bool(unscoped or forb or raw_forbidden or literals or fonts or radii or shadows)
    total_fail += int(fail)
    print(f"  => {'FAIL' if fail else 'PASS'}")

print(f"scope/tokens: {'FAIL' if total_fail else 'PASS'}")
sys.exit(1 if total_fail else 0)

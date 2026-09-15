"""Review of lane act_see, round 1 (read-only): scoping, tokens-only and internal-selector check for
static/tabs/act.css and static/tabs/see.css.

Run: python scripts/dev/finish/review_act_see_scope.py   (exit 0 = no hard finding)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = {"act": ROOT / "static" / "tabs" / "act.css", "see": ROOT / "static" / "tabs" / "see.css"}
INTERNAL = ["svelte-", ".block", ".gradio-container", ".prose", ".wrap", ".gr-"]
COLOUR_PROPS = ("color", "background", "background-color", "border", "border-color", "border-top", "border-bottom",
                "border-left", "border-right", "border-inline", "border-block", "outline", "outline-color",
                "box-shadow", "fill", "stroke", "caret-color", "accent-color", "text-decoration-color")
NAMED = re.compile(r"\b(white|black|red|green|blue|gray|grey|silver|orange|yellow|purple|pink|brown|navy|teal|"
                   r"maroon|olive|lime|aqua|fuchsia|beige|ivory|tan|gold|cyan|magenta)\b", re.I)


def blank_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), css, flags=re.S)


def parse(css: str):
    """(prelude, body, line) for every style rule, descending into @media blocks."""
    out, stack, last = [], [], 0
    for m in re.finditer(r"[{}]", css):
        if m.group() == "{":
            stack.append((css[last:m.start()].strip(), m.end()))
        else:
            prelude, start = stack.pop()
            if not prelude.startswith("@"):
                out.append((prelude, css[start:m.start()], css.count("\n", 0, start) + 1))
        last = m.end()
    return out


def split_top(prelude: str):
    parts, depth, cur, nested_commas = [], 0, "", 0
    for ch in prelude:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        if ch == "," and depth > 0:
            nested_commas += 1
        cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p], nested_commas


def declared_tokens() -> set[str]:
    names: set[str] = set()
    for p in (ROOT / "static" / "twin.css", ROOT / "twin" / "ui" / "theme.py"):
        names |= set(re.findall(r"(--twin-[a-z0-9-]+)\s*:", p.read_text(encoding="utf-8")))
    theme = (ROOT / "twin" / "ui" / "theme.py").read_text(encoding="utf-8")
    names |= set(re.findall(r"[\"'](--twin-[a-z0-9-]+)[\"']", theme))
    # theme.py may build names from a prefix: record any "twin-<x>" key it writes as a hint
    names |= {"--" + n for n in re.findall(r"[\"'](twin-[a-z0-9-]+)[\"']", theme)}
    return names


def main() -> int:
    hard, info = [], []
    tokens = declared_tokens()
    for tab, path in FILES.items():
        raw = path.read_text(encoding="utf-8")
        css = blank_comments(raw)
        rules = parse(css)
        n_sel = 0
        for prelude, body, line in rules:
            sels, nested = split_top(prelude)
            if nested:
                hard.append(f"{path.name}:{line} comma inside a pseudo-class list: {prelude!r}")
            for sel in sels:
                n_sel += 1
                if not re.match(rf"^(body\.dark\s+)?#tab-{tab}(?![\w-])", sel):
                    hard.append(f"{path.name}:{line} selector not scoped to #tab-{tab}: {sel!r}")
                if re.search(rf"#tab-{tab}-button", sel):
                    hard.append(f"{path.name}:{line} frame strip button styled: {sel!r}")
                for bad in INTERNAL:
                    if bad in sel:
                        hard.append(f"{path.name}:{line} internal selector {bad!r} in {sel!r}")
                for frame_id in ("#twin-masthead", "#twin-avatar", "#twin-header", "#gpu-note", "#status-strip",
                                 "#twin-tabs"):
                    if frame_id in sel:
                        hard.append(f"{path.name}:{line} frame element styled: {sel!r}")
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                prop, value = (s.strip() for s in decl.split(":", 1))
                prop_l = prop.lower()
                where = f"{path.name}:{line} {prop}: {value}"
                if "!important" in value:
                    hard.append(f"{where} uses !important")
                if prop_l.startswith("--twin-"):
                    hard.append(f"{where} redefines a --twin-* token")
                elif prop_l.startswith("--"):
                    if not (re.fullmatch(r"var\(--twin-[a-z0-9-]+\)", value) or value in ("0", "0px")):
                        hard.append(f"{where} sets a Gradio variable to a non-token value")
                    else:
                        info.append(f"{where} (Gradio variable)")
                if re.search(r"#[0-9a-fA-F]{3,8}\b", value):
                    hard.append(f"{where} hex colour literal")
                if re.search(r"\b(rgba?|hsla?|oklch|lab|lch|color-mix)\(", value):
                    hard.append(f"{where} colour function literal")
                if prop_l in COLOUR_PROPS and NAMED.search(value):
                    hard.append(f"{where} named colour")
                if prop_l in ("font-family", "font"):
                    if not (re.fullmatch(r"var\(--twin-font-[a-z]+\)", value) or value == "inherit"):
                        hard.append(f"{where} font not from a --twin-font-* token")
                if prop_l.endswith("radius"):
                    if not (re.fullmatch(r"var\(--twin-radius-[a-z]+\)", value) or value in ("0", "0px", "inherit")):
                        hard.append(f"{where} radius literal")
                if prop_l == "box-shadow":
                    if not (re.fullmatch(r"var\(--twin-[a-z0-9-]+\)", value) or value == "none"):
                        hard.append(f"{where} shadow literal")
                if prop_l.startswith("transition"):
                    if "all" in value.split() or not re.search(r"var\(--twin-duration\)", value):
                        hard.append(f"{where} transition not on listed properties with var(--twin-duration)")
                for tok in re.findall(r"var\((--twin-[a-z0-9-]+)\)", value):
                    if tok not in tokens:
                        hard.append(f"{where} references undeclared token {tok}")
                if re.search(r"(?<![\w-])\d+(\.\d+)?px", value) and not prop_l.startswith("--") \
                        and value not in ("0px",):
                    info.append(f"{where} (px literal, spacing/size: informational)")
        raw_hits = [b for b in INTERNAL if b in raw]
        print(f"{path.relative_to(ROOT)}: {len(rules)} rules, {n_sel} selectors; internal strings anywhere in file "
              f"(comments included): {raw_hits or 'none'}")
    print(f"declared --twin-* names found: {len(tokens)}")
    print("INFO:")
    for i in info:
        print("  " + i)
    print("HARD:" if hard else "HARD: none")
    for h in hard:
        print("  " + h)
    print("scoping/tokens: " + ("FAIL" if hard else "PASS"))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())

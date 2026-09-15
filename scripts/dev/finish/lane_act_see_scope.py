"""Scratch scoping check for the P4 act_see lane (read-only).

For static/tabs/act.css and static/tabs/see.css it checks three things:
- every selector starts with #tab-<id>, optionally after body.dark;
- no declaration redefines a --twin-* token or uses a colour literal;
- no Gradio-internal selector appears (svelte-, .block, .gradio-container, .prose, .wrap, .gr-).
It prints one line per file and exits 1 on any finding. The rule parser matches tests/test_theme.py.

Usage (project root): python scripts/dev/finish/lane_act_see_scope.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN = re.compile(r"svelte-|\.block\b|\.gradio-container|\.prose\b|\.wrap\b|\.gr-")
COLOUR = re.compile(
    r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(|"
    r"\b(?:white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy)\b", re.IGNORECASE)


def selectors(prelude: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur.strip()] if p]


def rules(css: str) -> list[tuple[list[str], str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    while (j := css.find("{", i)) >= 0:
        depth, k = 1, j + 1
        while k < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        prelude, body = css[i:j].strip(), css[j + 1:k - 1]
        if prelude.startswith(("@media", "@supports")):
            out.extend(rules(body))
        elif not prelude.startswith("@"):
            out.append((selectors(prelude), body))
        i = k
    return out


def main() -> int:
    bad = 0
    for tab in ("act", "see"):
        path = ROOT / "static" / "tabs" / f"{tab}.css"
        text = path.read_text(encoding="utf-8")
        root = f"#tab-{tab}"
        count, findings = 0, []
        for sels, body in rules(text):
            for s in sels:
                count += 1
                t = s[len("body.dark "):].lstrip() if s.startswith("body.dark ") else s
                if not re.match(re.escape(root) + r"(?![\w-])", t):
                    findings.append(f"unscoped selector: {s}")
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, value = (x.strip() for x in decl.split(":", 1))
                if name.startswith("--twin-"):
                    findings.append(f"redefines a token: {name}")
                if COLOUR.search(value):
                    findings.append(f"colour literal: {name}: {value}")
        for m in FORBIDDEN.finditer(text):
            findings.append(f"internal selector text: {m.group(0)!r}")
        if findings:
            bad += len(findings)
            print(f"FAIL static/tabs/{path.name}: {count} selectors")
            for f in findings:
                print("  " + f)
        else:
            print(f"PASS static/tabs/{path.name}: {count} selectors, every one starts with {root}; "
                  f"no token redefinition, colour literal or internal selector")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

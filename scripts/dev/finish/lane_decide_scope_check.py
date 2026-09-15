"""P4 decide lane check (read-only, no app, no model; run as a file from the project root).

Parses static/tabs/decide.css the way tests/test_theme.py does and prints, for every style rule (including those
inside @media): selectors that do not start with #tab-decide (optionally after "body.dark "); Gradio-internal names
(svelte-, .block, .gradio-container, .prose, .wrap, .gr-) anywhere in the file; colour literals or --twin-*
redefinitions in declarations; and commas inside :is(), :where() or :not(), which Gradio 6.27's CSS prefixer splits
(inflating specificity). Exit 0 when all four lists are empty.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = ROOT / "static" / "tabs" / "decide.css"
FORBIDDEN = re.compile(r"svelte-|\.block\b|\.gradio-container|\.prose\b|\.wrap\b|\.gr-")
COLOUR_LITERAL = re.compile(
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


def rules(css: str) -> list[tuple[list[str], str, str]]:
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
            out.append((selectors(prelude), body, prelude))
        i = k
    return out


def main() -> int:
    text = CSS.read_text(encoding="utf-8")
    parsed = rules(text)
    unscoped, literals, commas = [], [], []
    for sels, body, prelude in parsed:
        for s in sels:
            bare = s[len("body.dark "):].lstrip() if s.startswith("body.dark ") else s
            if not re.match(r"#tab-decide(?![\w-])", bare):
                unscoped.append(s)
            if re.search(r":(?:is|where|not)\([^()]*,", s):
                commas.append(s)
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            name, value = (part.strip() for part in decl.split(":", 1))
            if name.startswith("--twin-") or COLOUR_LITERAL.search(value):
                literals.append(f"{prelude} {{ {name}: {value} }}")
    forbidden = [m.group(0) for m in FORBIDDEN.finditer(text)]
    print(f"{CSS.relative_to(ROOT)}: {len(parsed)} rules, {sum(len(s) for s, _, _ in parsed)} selectors")
    print("unscoped selectors:", unscoped or "none")
    print("forbidden Gradio-internal names:", forbidden or "none")
    print("colour literals or --twin-* redefinitions:", literals or "none")
    print("commas inside :is()/:where()/:not():", commas or "none")
    return 0 if not (unscoped or forbidden or literals or commas) else 1


if __name__ == "__main__":
    sys.exit(main())

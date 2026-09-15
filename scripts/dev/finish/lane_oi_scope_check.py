"""P4 lane onboarding_items: scoping and tokens check for static/tabs/onboarding.css and static/tabs/items.css
(read-only, no app, no model). Parses the partials with the same rule splitter as tests/test_theme.py and prints
every selector with OK or FAIL (must start with #tab-<id>, optionally after 'body.dark '), then any colour literal,
--twin-* redefinition, !important or Gradio accent variable in a declaration. Exit 1 on any failure.

Usage (project root):  python scripts/dev/finish/lane_oi_scope_check.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PARTIALS = {"onboarding": ROOT / "static" / "tabs" / "onboarding.css", "items": ROOT / "static" / "tabs" / "items.css"}
COLOUR_LITERAL = re.compile(
    r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(|"
    r"\b(?:white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy)\b", re.IGNORECASE)


def selectors(prelude):
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur.strip()] if p]


def rules(css):
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


def scoped(sel, root):
    s = sel[len("body.dark "):].lstrip() if sel.startswith("body.dark ") else sel
    return re.match(re.escape(root) + r"(?![\w-])", s) is not None


def main():
    fails = 0
    for tab, path in PARTIALS.items():
        rs = rules(path.read_text(encoding="utf-8"))
        n_sel = sum(len(s) for s, _ in rs)
        print(f"== {path.relative_to(ROOT)}: {len(rs)} rules, {n_sel} selectors, root #tab-{tab}")
        for sels, body in rs:
            for s in sels:
                ok = scoped(s, f"#tab-{tab}")
                fails += 0 if ok else 1
                print(f"  {'OK  ' if ok else 'FAIL'} {s}")
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, value = (x.strip() for x in decl.split(":", 1))
                bad = []
                if name.startswith("--twin-"):
                    bad.append("redefines a token")
                if name.startswith("--color-accent") or "--color-accent" in value:
                    bad.append("Gradio accent variable")
                if COLOUR_LITERAL.search(value):
                    bad.append("colour literal")
                if "!important" in value:
                    bad.append("!important")
                for b in bad:
                    fails += 1
                    print(f"  FAIL {b}: {', '.join(sels)} {{ {name}: {value} }}")
    print(f"scope/tokens check: {'PASS' if fails == 0 else 'FAIL'} ({fails} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

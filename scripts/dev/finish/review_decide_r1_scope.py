"""P4 decide lane, visual review r1 (read-only): list every selector in static/tabs/decide.css, fail any that does not
start with #tab-decide (or body.dark #tab-decide), and flag Gradio-internal names, colour/font/shadow/radius literals,
commas inside :is()/:where()/:not(), !important, --twin-* redefinitions and undeclared --twin-* tokens.
Writes scripts/dev/shots/lane_decide/review_r1/scope_check.json. Exit 1 on any hard failure."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = ROOT / "static" / "tabs" / "decide.css"
TWIN_CSS = ROOT / "static" / "twin.css"
THEME = ROOT / "twin" / "ui" / "theme.py"
OUT = ROOT / "scripts" / "dev" / "shots" / "lane_decide" / "review_r1" / "scope_check.json"

INTERNAL = ["svelte-", ".block", ".gradio-container", ".prose", ".wrap", ".gr-"]
NAMED = {"white", "black", "red", "green", "blue", "gray", "grey", "silver", "orange", "yellow", "purple", "brown",
         "pink", "navy", "teal", "maroon", "olive", "lime", "aqua", "fuchsia", "beige", "ivory", "tan", "gold"}
SCOPE = re.compile(r"^(body\.dark\s+)?#tab-decide(?=$|[\s.:\[>+~#])")


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def parse(text: str) -> list[tuple[list[str], str, str]]:
    """(at-rule context, selector prelude, declarations) for every style rule, recursing into @media."""
    items: list[tuple[list[str], str, str]] = []
    n = len(text)

    def block(i: int, ctx: list[str]) -> int:
        start = i
        while i < n:
            c = text[i]
            if c == "{":
                prelude = text[start:i].strip()
                if prelude.startswith("@"):
                    i = block(i + 1, ctx + [prelude])
                else:
                    j = text.index("}", i)
                    items.append((ctx, prelude, text[i + 1:j]))
                    i = j + 1
                start = i
            elif c == "}":
                return i + 1
            else:
                i += 1
        return i

    block(0, [])
    return items


def split_top(prelude: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def commas_in_functional_pseudo(selector: str) -> bool:
    for m in re.finditer(r":(is|where|not|has)\(", selector):
        depth, k = 1, m.end()
        while k < len(selector) and depth:
            if selector[k] == "(":
                depth += 1
            elif selector[k] == ")":
                depth -= 1
            elif selector[k] == "," and depth == 1:
                return True
            k += 1
    return False


def main() -> int:
    raw = CSS.read_text(encoding="utf-8")
    body = strip_comments(raw)
    declared = set(re.findall(r"(--twin-[a-z0-9-]+)\s*:", TWIN_CSS.read_text(encoding="utf-8")))
    declared |= set(re.findall(r"--twin-[a-z0-9-]+", THEME.read_text(encoding="utf-8")))
    fails: list[str] = []
    info: list[str] = []
    selectors: list[dict] = []
    rules = parse(body)
    for ctx, prelude, decls in rules:
        for sel in split_top(prelude):
            ok = bool(SCOPE.match(sel))
            selectors.append({"media": " ".join(ctx), "selector": sel, "scoped": ok})
            if not ok:
                fails.append(f"unscoped selector: {sel!r}")
            if sel.startswith("#tab-decide-"):
                fails.append(f"frame strip button id: {sel!r}")
            if commas_in_functional_pseudo(sel):
                info.append(f"comma inside a functional pseudo-class (Gradio's prefixer splits it): {sel!r}")
            for bad in INTERNAL:
                if bad in sel:
                    fails.append(f"internal name {bad!r} in selector {sel!r}")
        for decl in [d.strip() for d in decls.split(";") if d.strip()]:
            if ":" not in decl:
                continue
            prop, val = [p.strip() for p in decl.split(":", 1)]
            low = val.lower()
            where = f"{prelude.splitlines()[0]} {{ {prop}: {val} }}"
            if prop.startswith("--twin-"):
                fails.append(f"--twin-* redefinition: {where}")
            if re.search(r"#[0-9a-f]{3,8}\b", low) or re.search(r"\b(rgba?|hsla?|hwb|lab|lch|oklch|color)\(", low):
                fails.append(f"colour literal: {where}")
            for word in re.findall(r"\b[a-z]+\b", low):
                if word in NAMED:
                    fails.append(f"named colour {word!r}: {where}")
            if prop in ("font-family", "font") and "var(--twin-font" not in low and low not in ("inherit",):
                fails.append(f"font not from a token: {where}")
            if prop == "box-shadow" and low not in ("none",) and "var(--twin-shadow" not in low:
                fails.append(f"shadow not from a token: {where}")
            if "radius" in prop and not (low in ("0", "0px") or "var(--twin-radius" in low):
                fails.append(f"radius not from a token: {where}")
            if "!important" in low:
                fails.append(f"!important: {where}")
            for tok in re.findall(r"var\((--twin-[a-z0-9-]+)", val):
                if tok not in declared:
                    fails.append(f"undeclared token {tok}: {where}")
            if prop.startswith("--") and not prop.startswith("--twin-"):
                info.append(f"Gradio variable set: {where}")
            for px in re.findall(r"\b\d+(?:\.\d+)?px\b", val):
                if px not in ("0px",):
                    info.append(f"px literal {px}: {where}")
            if prop.startswith("transition") or prop.startswith("animation"):
                info.append(f"motion: {where}")
    for bad in INTERNAL:
        if bad in raw:
            hits = [i + 1 for i, line in enumerate(raw.splitlines()) if bad in line]
            (fails if bad in body else info).append(f"literal {bad!r} in file lines {hits} (comments included)")
    report = {"file": str(CSS.relative_to(ROOT)), "rules": len(rules), "selectors": len(selectors),
              "unscoped": [s["selector"] for s in selectors if not s["scoped"]], "fails": fails, "info": info,
              "all_selectors": selectors}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{report['file']}: {report['rules']} rules, {report['selectors']} selectors")
    for s in selectors:
        print(("  OK   " if s["scoped"] else "  FAIL ") + (f"[{s['media']}] " if s["media"] else "") + s["selector"])
    print(f"fails ({len(fails)}):")
    for f in fails:
        print("  " + f)
    print(f"info ({len(info)}):")
    for f in info:
        print("  " + f)
    print("scoping_ok=" + str(not report["unscoped"]).lower())
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

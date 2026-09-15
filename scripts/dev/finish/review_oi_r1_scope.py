"""Review r1 of lane onboarding_items (docs/PLAN_FINISH.md P4): scope, internal-selector and tokens check of
static/tabs/onboarding.css and static/tabs/items.css, plus WCAG contrast for the token pairs those partials put text
on. Read-only: no app, no model. Written independently of the lane's own lane_oi_scope_check.py.

Run (project root): python scripts/dev/finish/review_oi_r1_scope.py
Exit 0 when no hard failure (scope, forbidden selector, colour literal, token redefinition, !important,
--color-accent, non-token font/radius/shadow)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = {"onboarding": ROOT / "static" / "tabs" / "onboarding.css", "items": ROOT / "static" / "tabs" / "items.css"}
FORBIDDEN = re.compile(r"svelte-|\.block\b|\.gradio-container|\.prose\b|\.wrap\b|\.gr-")
COLOUR = re.compile(r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(|"
                    r"\b(?:white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy)\b", re.I)


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


def rules(css: str, media: str = "") -> list[tuple[list[str], str, str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    while (j := css.find("{", i)) >= 0:
        depth, k = 1, j + 1
        while k < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        prelude, body = css[i:j].strip(), css[j + 1:k - 1]
        if prelude.startswith(("@media", "@supports")):
            out.extend(rules(body, prelude))
        elif not prelude.startswith("@"):
            out.append((selectors(prelude), body, media))
        i = k
    return out


def token_block(css: str, selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, flags=re.S)
    return dict(re.findall(r"--twin-([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", m.group(1))) if m else {}


def lum(hexv: str) -> float:
    rgb = [int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main() -> int:
    hard, soft, info = [], [], []
    for tab, path in FILES.items():
        text = path.read_text(encoding="utf-8")
        scope = re.compile(r"^(?:body\.dark\s+)?#tab-" + re.escape(tab) + r"(?![\w-])")
        for m in FORBIDDEN.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hard.append(f"{path.name}:{line} forbidden internal selector text {m.group(0)!r}")
        rs = rules(text)
        n_sel = 0
        for sels, body, media in rs:
            for s in sels:
                n_sel += 1
                print(f"  {path.name}{' [' + media + ']' if media else ''}: {s}")
                if not scope.match(s):
                    hard.append(f"{path.name}: selector not scoped to #tab-{tab}: {s!r}")
                if re.search(r"#tab-" + re.escape(tab) + r"-button", s):
                    hard.append(f"{path.name}: styles the frame's strip button: {s!r}")
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, value = (p.strip() for p in decl.split(":", 1))
                where = f"{path.name} {', '.join(sels)} {{ {name}: {value} }}"
                if name.startswith("--twin-"):
                    hard.append(f"redefines a token: {where}")
                elif name.startswith("--"):
                    ok = value.startswith("var(--twin-") or value == "0"
                    (info if ok else hard).append(f"sets Gradio variable {name} to {value!r}: {where}")
                if name == "--color-accent":
                    hard.append(f"overrides --color-accent: {where}")
                if COLOUR.search(value):
                    hard.append(f"colour literal: {where}")
                if "!important" in value:
                    hard.append(f"!important: {where}")
                if name in ("font-family", "font") and "var(--twin-font" not in value:
                    hard.append(f"font not from a token: {where}")
                if name == "border-radius" and not (value in ("0", "none") or value.startswith("var(--twin-radius")):
                    hard.append(f"radius not from a token: {where}")
                if name == "box-shadow" and not (value in ("none", "0") or "var(--twin-shadow" in value or "var(--twin-focus" in value):
                    hard.append(f"shadow not from a token: {where}")
                if name == "font-size" and not value.startswith("var(--twin-text"):
                    soft.append(f"font-size not from the type scale: {where}")
                if name.startswith("transition") and re.search(r"\ball\b", value):
                    soft.append(f"transition: all: {where}")
                if name.startswith("outline") and value in ("none", "0"):
                    soft.append(f"outline removed: {where}")
                if re.search(r"(?<![\w-])\d+(?:\.\d+)?px", value) and not value.startswith("var("):
                    info.append(f"px literal (spacing/size, not colour/radius/shadow/font): {where}")
        print(f"{path.name}: {len(rs)} rules, {n_sel} selectors")

    css = (ROOT / "static" / "twin.css").read_text(encoding="utf-8")
    modes = {"light": token_block(css, ":root"), "dark": token_block(css, "body.dark")}
    pairs = [
        ("text", "surface", "walkthrough status, statements, decision verdict (light surface-raised = surface)"),
        ("text-muted", "surface", "step labels to do, help text, number to do"),
        ("text-muted", "bg", "intro, files list"),
        ("text-muted", "surface-raised", "decision footer"),
        ("text", "surface-raised", "decision verdict"),
        ("warn", "surface", "caution buttons (Save answers, Run twin, Score)"),
        ("warn", "bg", "*ceiling pending* in the files list"),
        ("warn", "warn-soft", "caution button hover"),
        ("err", "bg", "**Error:** label in save/run notes"),
        ("accent-ink", "accent", "current step number"),
        ("accent", "accent-soft", "done step number"),
        ("text", "accent-soft", "checked answer option"),
        ("accent", "surface", "accordion heading hover"),
        ("border-strong", "surface", "to-do step circle edge (non-text, 3:1)"),
    ]
    for mode, toks in modes.items():
        for fg, bg, use in pairs:
            if fg in toks and bg in toks:
                r = ratio(toks[fg], toks[bg])
                need = 3.0 if "non-text" in use else 4.5
                line = f"contrast {mode}: --twin-{fg} {toks[fg]} on --twin-{bg} {toks[bg]} = {r:.2f}:1 ({use})"
                print("  " + line)
                if r < need:
                    soft.append("below " + str(need) + ": " + line)
            else:
                info.append(f"contrast {mode}: token missing for {fg} or {bg}")

    for label, rows in (("HARD", hard), ("SOFT", soft), ("INFO", info)):
        for row in rows:
            print(f"{label} {row}")
    print(f"scope/tokens review: {'PASS' if not hard else 'FAIL'} ({len(hard)} hard, {len(soft)} soft, {len(info)} info)")
    return 0 if not hard else 1


if __name__ == "__main__":
    sys.exit(main())

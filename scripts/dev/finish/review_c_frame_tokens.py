"""Review helper (P3 frame, round 1): tokens-only scan of static/twin.css and static/tabs/frame.css outside the two
token blocks, plus the frame contract cross-check (every var(--twin-*) used is declared; every contract class has a
rule). Reads files only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "static"

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
NAMED = re.compile(r"\b(?:white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy)\b", re.I)
PX = re.compile(r"(?<![\w-])\d+(?:\.\d+)?px\b")
FONT_LITERAL = re.compile(r"'[^']+'|\"[^\"]+\"|\b(?:serif|sans-serif|monospace|Georgia|Consolas|Arial)\b")
COLOUR_PROPS = ("color", "background", "background-color", "border", "border-color", "border-left", "border-right",
                "border-top", "border-bottom", "outline", "box-shadow", "fill", "stroke", "text-decoration-color")


def rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    i = 0
    while (j := css.find("{", i)) >= 0:
        depth, k = 1, j + 1
        while k < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        prelude, body = css[i:j].strip(), css[j + 1:k - 1]
        if prelude.startswith(("@media", "@supports")):
            out.extend((f"{prelude} >> {p}", b) for p, b in rules(body))
        elif not prelude.startswith("@"):
            out.append((prelude, body))
        i = k
    return out


def main() -> int:
    twin = (STATIC / "twin.css").read_text(encoding="utf-8")
    frame = (STATIC / "tabs" / "frame.css").read_text(encoding="utf-8")
    declared = set(re.findall(r"(--twin-[a-z0-9-]+)\s*:", twin))
    findings = 0
    for name, css in (("static/twin.css", twin), ("static/tabs/frame.css", frame)):
        print(f"==== {name} ====")
        for prelude, body in rules(css):
            if name.endswith("twin.css") and prelude in (":root", "body.dark"):
                continue
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                prop, value = (p.strip() for p in decl.split(":", 1))
                notes = []
                if HEX.search(value) or FUNC.search(value) or NAMED.search(value):
                    notes.append("COLOUR LITERAL")
                if prop in ("font-family", "font") and "var(--twin-font" not in value and value not in ("inherit",):
                    notes.append("FONT not from token")
                if prop == "border-radius" and PX.search(value) and "var(--twin-radius" not in value:
                    notes.append("RADIUS literal")
                if prop == "box-shadow" and value not in ("none",) and "var(--twin-shadow" not in value:
                    notes.append("SHADOW literal")
                if PX.search(value) and prop not in ("border-radius",):
                    notes.append("px literal (spacing/size; informational)")
                if prop.startswith("--twin-"):
                    notes.append("TOKEN REDEFINED")
                for v in re.findall(r"var\((--twin-[a-z0-9-]+)", value):
                    if v not in declared:
                        notes.append(f"UNDECLARED {v}")
                if notes:
                    hard = [n for n in notes if "informational" not in n]
                    findings += len(hard)
                    print(f"  {prelude} {{ {prop}: {value} }}  -> {', '.join(notes)}")
    print("\n==== contract variables named in the restyle result, declared in twin.css? ====")
    named = ["--twin-bg", "--twin-surface", "--twin-surface-raised", "--twin-text", "--twin-text-muted",
             "--twin-accent", "--twin-accent-ink", "--twin-accent-soft", "--twin-border", "--twin-border-strong",
             "--twin-ok", "--twin-ok-soft", "--twin-warn", "--twin-warn-soft", "--twin-err", "--twin-err-soft",
             "--twin-focus", "--twin-focus-ring", "--twin-shadow-1", "--twin-shadow-2", "--twin-font-body",
             "--twin-font-serif", "--twin-font-mono", "--twin-radius-control", "--twin-radius-card",
             "--twin-text-xs", "--twin-text-sm", "--twin-text-md", "--twin-text-lg", "--twin-text-xl",
             "--twin-text-2xl", "--twin-text-3xl", "--twin-leading", "--twin-leading-serif", "--twin-measure",
             "--twin-measure-wide", "--twin-space-1", "--twin-space-2", "--twin-space-3", "--twin-space-4",
             "--twin-space-5", "--twin-space-6", "--twin-space-8", "--twin-max-width", "--twin-target",
             "--twin-avatar", "--twin-rule", "--twin-card-min", "--twin-duration", "--twin-ease"]
    miss = [v for v in named if v not in declared]
    print("missing:", miss)
    findings += len(miss)
    print("declared but not in contract:", sorted(declared - set(named)))
    print("\n==== contract classes, rule present in twin.css? ====")
    classes = ["twin-intro", "twin-section", "twin-panel", "twin-card", "twin-result", "twin-actions", "twin-quiet",
               "twin-caution", "twin-hint", "twin-empty", "twin-split", "twin-table", "trace", "quote-card",
               "verdict-card", "verdict", "reasons", "verdict-footer", "confidence-meter", "track", "fill", "value",
               "chip", "chip-id", "badge-ok", "badge-warn", "badge-err", "model-table", "placeholder-card", "num",
               "quote-by"]
    sels = " ".join(p for p, _ in rules(twin))
    for c in classes:
        ok = re.search(r"\." + re.escape(c) + r"(?![\w-])", sels) is not None
        findings += 0 if ok else 1
        print(f"  .{c:18s} {'ok' if ok else 'MISSING'}")
    # var() used in any tab partial or frame.css must be declared
    print("\n==== var(--twin-*) used anywhere in static/, declared? ====")
    for f in sorted(STATIC.rglob("*.css")):
        used = set(re.findall(r"var\((--twin-[a-z0-9-]+)", f.read_text(encoding="utf-8")))
        und = sorted(used - declared)
        print(f"  {f.relative_to(ROOT)}: {len(used)} used, undeclared {und}")
        findings += len(und)
    print("\nHARD_FINDINGS", findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

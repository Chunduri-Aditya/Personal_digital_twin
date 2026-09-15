"""P5 assemble scratch check (read-only): every selector in static/tabs/<tab>.css starts with #tab-<id> or
body.dark #tab-<id>. frame.css is the frame's own partial and is listed separately. Handles comments, @media
blocks and top-level comma lists (commas inside parentheses are not split)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TAB_OF = {"eval": "eval", "evals": "eval"}


def selectors(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, buf, depth = [], "", 0
    i = 0
    while i < len(css):
        ch = css[i]
        if ch == "{":
            head = buf.strip()
            buf = ""
            if head.startswith("@"):
                depth += 0  # at-rule block: selectors inside are read as normal rules
                i += 1
                continue
            # skip the declaration block
            j, d = i + 1, 1
            while j < len(css) and d:
                if css[j] == "{":
                    d += 1
                elif css[j] == "}":
                    d -= 1
                j += 1
            parts, cur, par = [], "", 0
            for c2 in head:
                if c2 in "([":
                    par += 1
                elif c2 in ")]":
                    par -= 1
                if c2 == "," and par == 0:
                    parts.append(cur.strip())
                    cur = ""
                else:
                    cur += c2
            parts.append(cur.strip())
            out.extend(p for p in parts if p)
            i = j
            continue
        if ch == "}":
            buf = ""
        else:
            buf += ch
        i += 1
    return out


total_fail = 0
for f in sorted((ROOT / "static/tabs").glob("*.css")):
    sels = selectors(f.read_text(encoding="utf-8"))
    if f.stem == "frame":
        print(f"{f.name}: {len(sels)} selectors (frame partial, not a tab partial; skipped)")
        continue
    tid = TAB_OF.get(f.stem, f.stem)
    pat = re.compile(rf"^(body\.dark\s+)?#tab-{re.escape(tid)}(?![\w-])")
    bad = [s for s in sels if not pat.match(s) or s.startswith(f"#tab-{tid}-button")]
    total_fail += len(bad)
    print(f"{f.name}: {len(sels)} selectors, unscoped {len(bad)}" + (f" -> {bad}" if bad else ""))
print("SCOPING_OK" if total_fail == 0 else f"SCOPING_FAIL {total_fail}")
sys.exit(1 if total_fail else 0)

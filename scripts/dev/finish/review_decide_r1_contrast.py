"""P4 decide lane, visual review r1 (read-only, no app boot): WCAG contrast of the text/background pairs that
static/tabs/decide.css introduces, resolved from the token sheet through twin.ui.theme (css_variables per mode), with
twin.css's default token blocks as a fallback. Writes scripts/dev/shots/lane_decide/review_r1/contrast_check.json."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from twin.ui import theme  # noqa: E402

OUT = ROOT / "scripts" / "dev" / "shots" / "lane_decide" / "review_r1" / "contrast_check.json"
TWIN_CSS = ROOT / "static" / "twin.css"

# (foreground, background, minimum, where decide.css uses it)
PAIRS = [
    ("text", "surface-raised", 4.5, "verdict card body text, reasons, In my voice serif text"),
    ("text-muted", "surface-raised", 4.5, "Reasons / Cited decisions labels, footer, em (13 px)"),
    ("accent", "surface-raised", 3.0, "Verdict / Choice figure (32 px bold, large text)"),
    ("accent", "surface-raised", 4.5, "Verdict figure at body-text threshold (informational)"),
    ("warn", "surface-raised", 4.5, "uncited references line (13 px)"),
    ("err", "err-soft", 4.5, "Error: label on the madder band (15 px 600)"),
    ("text", "err-soft", 4.5, "error message text on the madder band"),
    ("text", "bg", 4.5, "cited-decision chips (13 px on page ground)"),
    ("text-muted", "bg", 4.5, "(no decision yet) in the dashed empty card"),
    ("accent-ink", "accent", 4.5, "B1 primary label"),
    ("text", "surface", 4.5, "B2 / Say it outlined labels, question sheets"),
    ("border-strong", "bg", 3.0, "dashed empty-card edge (non-text, informational)"),
    ("border-strong", "surface-raised", 3.0, "annotation left rule (non-text, informational)"),
    ("accent", "accent-soft", 3.0, "meter fill against its track (non-text)"),
    ("accent", "bg", 3.0, "quote-card left rule against the page ground (non-text)"),
]


def css_defaults() -> dict[str, dict[str, str]]:
    text = re.sub(r"/\*.*?\*/", "", TWIN_CSS.read_text(encoding="utf-8"), flags=re.S)
    out: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        sel = sel.strip()
        mode = "light" if sel == ":root" else "dark" if sel == "body.dark" else None
        if not mode:
            continue
        for name, val in re.findall(r"--twin-([a-z0-9-]+)\s*:\s*([^;]+);", body):
            out[mode][name] = val.strip()
    return out


def to_hex(value: str, under: str | None) -> tuple[str | None, str]:
    v = value.strip()
    if re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", v):
        return theme._norm_hex(v), ""
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = float(m.group(4)) if m.group(4) else 1.0
        if a < 1.0:
            if under is None:
                return None, "alpha without a base"
            ur, ug, ub = theme._rgb(under)
            r, g, b = r * a + ur * (1 - a), g * a + ug * (1 - a), b * a + ub * (1 - a)
            return theme._hex(r, g, b), f"composited alpha {a} over {under}"
        return theme._hex(r, g, b), ""
    return None, f"unparsed {v!r}"


def main() -> int:
    tokens = theme.load_tokens()
    defaults = css_defaults()
    report, fails = {}, []
    for mode in ("light", "dark"):
        raw = {}
        try:
            for k, v in theme.css_variables(tokens, mode).items():
                raw[re.sub(r"^-*(twin-)?", "", k)] = str(v)
        except Exception as e:  # noqa: BLE001
            print(f"css_variables({mode}) failed: {type(e).__name__}: {e}")
        for k, v in defaults[mode].items():
            raw.setdefault(k, v)
        rows = []
        for fg, bg, minimum, where in PAIRS:
            bg_hex, bg_note = to_hex(raw.get(bg, ""), to_hex(raw.get("surface-raised", ""), None)[0])
            fg_hex, fg_note = to_hex(raw.get(fg, ""), bg_hex)
            if not (fg_hex and bg_hex):
                rows.append({"fg": fg, "bg": bg, "error": f"fg {raw.get(fg)!r} {fg_note}; bg {raw.get(bg)!r} {bg_note}"})
                fails.append(f"{mode} {fg} on {bg}: unresolved")
                continue
            ratio = round(theme.contrast_ratio(fg_hex, bg_hex), 2)
            ok = ratio >= minimum
            rows.append({"fg": fg, "fg_hex": fg_hex, "bg": bg, "bg_hex": bg_hex, "ratio": ratio, "min": minimum,
                         "ok": ok, "where": where, "notes": " ".join(n for n in (fg_note, bg_note) if n)})
            print(f"{mode:5} {fg:14} {fg_hex} on {bg:14} {bg_hex}: {ratio:5.2f} (min {minimum}) "
                  f"{'ok' if ok else 'LOW'}  - {where}")
            if not ok and "informational" not in where:
                fails.append(f"{mode} {fg} on {bg} = {ratio} < {minimum} ({where})")
        report[mode] = rows
    report["fails"] = fails
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"fails ({len(fails)}): {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

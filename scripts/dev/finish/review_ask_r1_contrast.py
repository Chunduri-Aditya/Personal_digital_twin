"""Review of the ask lane, round 1: WCAG contrast of the text and edge pairs the Ask restyle introduces. Read-only.

Run from the project root with PYTHONPATH set to it. Pairs (fg on bg):
- the twin's reply: text on surface; the inline error line: err on surface
- the placeholder's second line, the waiting ellipsis and the quiet Clear: text-muted on surface
- the hint line and Trace's '(no trace yet)': text-muted on bg; trace text: text on bg
- your message: text on accent-soft; the monogram glyph: accent on accent-soft
- Send: accent-ink on accent
- non-text (3:1): the streaming ring (accent on surface), the settings hairline and log rule (border on surface)"""
from __future__ import annotations

from twin.ui import theme

PAIRS = [
    ("text", "surface", 4.5, "reply text on the sheet"),
    ("err", "surface", 4.5, "inline error line on the sheet"),
    ("text-muted", "surface", 4.5, "placeholder line 2, waiting ellipsis, quiet Clear"),
    ("text-muted", "bg", 4.5, "hint line, '(no trace yet)'"),
    ("text", "bg", 4.5, "trace and checker text"),
    ("text", "accent-soft", 4.5, "your message on the tint"),
    ("accent", "accent-soft", 3.0, "monogram glyph on its tile (large glyph)"),
    ("accent-ink", "accent", 4.5, "Send label"),
    ("accent", "surface", 3.0, "streaming ring (non-text)"),
    ("border", "surface", 1.0, "hairlines (decorative, informational)"),
]


def main() -> int:
    tokens = theme.load_tokens()
    print(f"sheet: {tokens.get('path')}")
    print(f"keys light: {sorted(tokens['light'])}")
    fails = []
    for mode in ("light", "dark"):
        col = tokens[mode]
        for fg, bg, need, what in PAIRS:
            if fg not in col or bg not in col:
                print(f"{mode:5} {fg} on {bg}: MISSING TOKEN")
                continue
            r = theme.contrast_ratio(col[fg], col[bg])
            ok = r >= need
            print(f"{mode:5} {fg:11} {col[fg]} on {bg:11} {col[bg]}: {r:5.2f} need {need} {'ok' if ok else 'FAIL'}  ({what})")
            if not ok:
                fails.append((mode, fg, bg, round(r, 2)))
    white = "#FFFFFF"
    for mode in ("light", "dark"):
        col = tokens[mode]
        print(f"{mode:5} #FFFFFF on accent {col['accent']}: {theme.contrast_ratio(white, col['accent']):.2f}; "
              f"text {col['text']} on accent: {theme.contrast_ratio(col['text'], col['accent']):.2f}")
    print(f"check_contrast() = {theme.check_contrast()}")
    print(f"FAILS {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

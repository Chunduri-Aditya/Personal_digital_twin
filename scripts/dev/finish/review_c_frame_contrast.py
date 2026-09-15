"""Review helper (P3 frame, round 1): print twin.ui.theme.check_contrast() and a few frame-specific pairs the
restyle relies on (warning label on bg, muted label on surface, accent rule, border-strong rule). Reads files only."""
from __future__ import annotations

from twin.ui import theme


def main() -> int:
    failures = theme.check_contrast()
    print("check_contrast() =", failures)
    tokens = theme.load_tokens()
    print("tokens:", tokens["path"])
    extra = [
        ("warn", "bg", 4.5, "header Warning label (on page ground)"),
        ("warn", "surface", 4.5, "Warning label if on a surface"),
        ("text-muted", "surface", 4.5, "status strip labels, tab labels on surface"),
        ("text-muted", "bg", 4.5, "tab labels on page ground"),
        ("text", "accent-soft", 4.5, "tab hover text on accent-soft"),
        ("text-muted", "accent-soft", 4.5, "quiet button text on hover"),
        ("accent", "accent-soft", 4.5, "monogram initial"),
        ("accent", "bg", 3.0, "open-tab 3px rule (non-text 3:1)"),
        ("border-strong", "bg", 3.0, "gpu note left rule vs page"),
        ("focus", "bg", 3.0, "focus outline on page ground"),
        ("warn", "warn-soft", 4.5, "caution hover"),
        ("text", "surface-raised", 4.5, "raised result text"),
    ]
    for mode in ("light", "dark"):
        t = tokens[mode]
        for fg, bg, need, why in extra:
            r = theme.contrast_ratio(t[fg], t[bg])
            print(f"{mode:>5} {fg:>13} on {bg:<14} {r:5.2f} need {need} {'ok' if r >= need else 'LOW'}  {why}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

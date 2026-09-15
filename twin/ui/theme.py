"""Design tokens -> Gradio theme + custom CSS for the twin console (docs/PLAN_UNIFIED.md section 3.8).

Token sheet: docs/design/tokens.md when the user has exported one from Claude Design, else
docs/design/tokens.default.md (the frontend-design two-pass plan written 2026-09-14). The sheet
is a markdown table ``| token | light | dark | note |`` followed by ``font-body:``, ``font-serif:``,
``font-mono:``, ``radius:`` and ``default_theme:`` lines. Everything Gradio owns is set through
``TwinTheme.set()``; everything on our own elem_ids/classes lives in static/twin.css (+
static/tabs/*.css) and reaches the page through ``css_text()``. Both read the same tokens: the
theme re-declares every ``--twin-*`` custom property from the parsed sheet (``custom_css``), so a
re-exported tokens.md updates the app without code changes, and static/twin.css keeps the default
values as the readable fallback.

No model is touched here; this module only reads files.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import gradio as gr
from gradio.themes.utils import colors, fonts, sizes

from twin import config

# Tokens every sheet must define in both columns (docs/PLAN_UNIFIED.md 3.8 + the A3 contract).
REQUIRED_TOKENS: tuple[str, ...] = (
    "bg", "surface", "surface-raised", "text", "text-muted", "accent", "accent-ink",
    "accent-soft", "border", "ok", "warn", "err", "focus",
)
# Optional tokens the theme derives when the sheet omits them (fg/bg mix, see _derived).
OPTIONAL_TOKENS: tuple[str, ...] = ("border-strong", "ok-soft", "warn-soft", "err-soft")
# Every text/background pair that carries body text; each must reach 4.5:1 in both modes.
BODY_TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("text", "bg"), ("text", "surface"), ("text-muted", "bg"), ("accent-ink", "accent"),
)
MIN_BODY_CONTRAST = 4.5
KEY_LINES = ("font-body", "font-serif", "font-mono", "radius", "default_theme")
# Fonts that ship with Windows/macOS; anything else named in the sheet is fetched as a Google Font.
_LOCAL_FONTS = {
    "consolas", "cascadia mono", "cascadia code", "menlo", "sf mono", "courier new", "segoe ui",
    "arial", "helvetica", "georgia", "times new roman", "monospace", "sans-serif", "serif",
}

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_KEY_LINE = re.compile(r"^\s*(font-body|font-serif|font-mono|radius|default_theme)\s*:\s*(.+?)\s*$")
_RADIUS = re.compile(r"(\d+)\s*px\s*(controls?|cards?)", re.IGNORECASE)


# ----------------------------------------------------------------------------- colour helpers

def _norm_hex(value: str) -> str:
    """'#abc' / '#AABBCC' -> '#AABBCC'; anything else is returned untouched."""
    v = value.strip()
    if not _HEX.match(v):
        return v
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v.upper()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = _norm_hex(hex_color).lstrip("#")
    if len(h) != 6:
        raise ValueError(f"not a hex colour: {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(c))) for c in (r, g, b)))


def _mix(a: str, b: str, t: float) -> str:
    """sRGB mix: t=0 -> a, t=1 -> b."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def _luminance(hex_color: str) -> float:
    def lin(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hex_color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colours (order does not matter)."""
    la, lb = _luminance(hex_a), _luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ----------------------------------------------------------------------------- token sheet

def parse_tokens(text: str) -> dict:
    """Parse a token sheet. Returns
    {"light": {name: value}, "dark": {name: value}, "notes": {name: note},
     "font_body", "font_serif", "font_mono", "radius", "radius_control", "radius_card",
     "default_theme"}. Missing keys come back as "" (fonts) or defaults (radius 6px/10px, theme light).
    """
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    notes: dict[str, str] = {}
    keys: dict[str, str] = {}
    in_table = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            heads = [c.lower() for c in cells]
            if heads[:3] == ["token", "light", "dark"]:
                in_table = True
                continue
            if in_table and cells and set(cells[0]) <= set("-: "):
                continue  # the |---|---| separator
            if in_table and len(cells) >= 3 and cells[0]:
                name = cells[0].strip("`").lower()
                light[name] = _norm_hex(cells[1].strip("`"))
                dark[name] = _norm_hex(cells[2].strip("`"))
                notes[name] = cells[3] if len(cells) > 3 else ""
            continue
        if in_table and line == "":
            in_table = False
        m = _KEY_LINE.match(line)
        if m and m.group(1) not in keys:
            keys[m.group(1)] = m.group(2).strip().strip("`'\"")
    radius = keys.get("radius", "6px controls, 10px cards")
    control, card = "6px", "10px"
    for px, what in _RADIUS.findall(radius):
        if what.lower().startswith("control"):
            control = f"{px}px"
        else:
            card = f"{px}px"
    theme = keys.get("default_theme", "light").lower()
    return {
        "light": light,
        "dark": dark,
        "notes": notes,
        "font_body": keys.get("font-body", ""),
        "font_serif": keys.get("font-serif", ""),
        "font_mono": keys.get("font-mono", ""),
        "radius": radius,
        "radius_control": control,
        "radius_card": card,
        "default_theme": theme if theme in ("light", "dark") else "light",
    }


def missing_tokens(tokens: dict) -> list[str]:
    """Required tokens absent (or not a hex colour) in either column, as 'light:name' / 'dark:name'."""
    out: list[str] = []
    for mode in ("light", "dark"):
        col = tokens.get(mode, {})
        for name in REQUIRED_TOKENS:
            if not _HEX.match(col.get(name, "")):
                out.append(f"{mode}:{name}")
    return out


def _derived(mode_tokens: dict[str, str]) -> dict[str, str]:
    """Fill the optional tokens from the required ones so CSS and theme never see a gap."""
    t = dict(mode_tokens)
    t.setdefault("border-strong", _mix(t["border"], t["text-muted"], 0.5))
    for sem in ("ok", "warn", "err"):
        t.setdefault(f"{sem}-soft", _mix(t["surface"], t[sem], 0.14))
    return t


def resolve_tokens_path() -> Path:
    """docs/design/tokens.md when the user exported one, else the default sheet."""
    if config.DESIGN_TOKENS_PATH.exists():
        return config.DESIGN_TOKENS_PATH
    return config.DEFAULT_DESIGN_TOKENS_PATH


def load_tokens(path: str | Path | None = None) -> dict:
    """Read and validate a token sheet (default: resolve_tokens_path()). A user-supplied tokens.md
    that lacks required tokens falls back to the default sheet with a warning on stderr; a broken
    default sheet raises ValueError naming the gaps."""
    p = Path(path) if path else resolve_tokens_path()
    tokens = parse_tokens(p.read_text(encoding="utf-8"))
    missing = missing_tokens(tokens)
    if missing and path is None and p != config.DEFAULT_DESIGN_TOKENS_PATH \
            and config.DEFAULT_DESIGN_TOKENS_PATH.exists():
        print(f"theme: {p.name} lacks {', '.join(missing)}; using {config.DEFAULT_DESIGN_TOKENS_PATH.name}",
              file=sys.stderr)
        p = config.DEFAULT_DESIGN_TOKENS_PATH
        tokens = parse_tokens(p.read_text(encoding="utf-8"))
        missing = missing_tokens(tokens)
    if missing:
        raise ValueError(f"token sheet {p} lacks required tokens: {', '.join(missing)}")
    tokens["light"] = _derived(tokens["light"])
    tokens["dark"] = _derived(tokens["dark"])
    tokens["path"] = str(p)
    return tokens


def contrast_report(tokens: dict | None = None) -> list[tuple[str, str, str, float]]:
    """(mode, fg, bg, ratio) for every BODY_TEXT_PAIRS entry in both modes."""
    tokens = tokens or load_tokens()
    rows = []
    for mode in ("light", "dark"):
        col = tokens[mode]
        for fg, bg in BODY_TEXT_PAIRS:
            rows.append((mode, fg, bg, contrast_ratio(col[fg], col[bg])))
    return rows


def check_contrast(tokens: dict | None = None, minimum: float = MIN_BODY_CONTRAST) -> list[tuple[str, str, str, float]]:
    """The body-text pairs below `minimum` (empty list = the sheet passes)."""
    return [row for row in contrast_report(tokens) if row[3] < minimum]


# ----------------------------------------------------------------------------- CSS variables

def _shadows(mode: str, t: dict[str, str]) -> tuple[str, str]:
    """Two elevation levels. Light: tinted with the ink (text token) so the shadow belongs to the
    paper. Dark: plain black at higher alpha; the raised surface, not the shadow, carries elevation."""
    if mode == "light":
        ink = t["text"]
        return (f"0 1px 2px {_rgba(ink, 0.06)}, 0 2px 6px {_rgba(ink, 0.06)}",
                f"0 2px 4px {_rgba(ink, 0.08)}, 0 12px 28px {_rgba(ink, 0.12)}")
    return ("0 1px 2px rgba(0, 0, 0, 0.5), 0 2px 6px rgba(0, 0, 0, 0.4)",
            "0 2px 4px rgba(0, 0, 0, 0.5), 0 12px 28px rgba(0, 0, 0, 0.45)")


def _font_stack(name: str, generic: str) -> str:
    fallback = {
        "sans": "ui-sans-serif, system-ui, 'Segoe UI', sans-serif",
        "serif": "Georgia, 'Times New Roman', serif",
        "mono": "'Cascadia Mono', ui-monospace, Menlo, monospace",
    }[generic]
    if name:
        return f"'{name}', {fallback}"
    return ("Consolas, " if generic == "mono" else "") + fallback


def css_variables(tokens: dict, mode: str) -> dict[str, str]:
    """The --twin-* custom properties for one mode (name without the prefix -> value)."""
    t = tokens[mode]
    s1, s2 = _shadows(mode, t)
    out = {name: t[name] for name in REQUIRED_TOKENS + OPTIONAL_TOKENS}
    out.update({
        "focus-ring": f"0 0 0 3px {_rgba(t['focus'], 0.3)}",
        "shadow-1": s1,
        "shadow-2": s2,
        "font-body": _font_stack(tokens.get("font_body", ""), "sans"),
        "font-serif": _font_stack(tokens.get("font_serif", ""), "serif"),
        "font-mono": _font_stack(tokens.get("font_mono", ""), "mono"),
        "radius-control": tokens.get("radius_control", "6px"),
        "radius-card": tokens.get("radius_card", "10px"),
    })
    return out


def tokens_css(tokens: dict) -> str:
    """The custom-property block the theme carries. `body` beats static/twin.css's `:root` by
    inheritance proximity and `body.dark.dark` beats its `body.dark` by specificity, so the parsed
    sheet always wins over the file's built-in defaults."""
    def block(selector: str, mode: str) -> str:
        lines = "\n".join(f"  --twin-{k}: {v};" for k, v in css_variables(tokens, mode).items())
        scheme = "  color-scheme: dark;" if mode == "dark" else "  color-scheme: light;"
        return f"{selector} {{\n{lines}\n{scheme}\n}}"
    return "/* twin tokens from " + Path(tokens.get("path", "tokens")).name + " */\n" \
        + block("body", "light") + "\n" + block("body.dark.dark", "dark") + "\n"


# ----------------------------------------------------------------------------- Gradio theme

_TEXT_SIZE = sizes.Size(xxs="10px", xs="11px", sm="13px", md="15px", lg="17px", xl="20px", xxl="24px",
                        name="text_twin")
_SPACING = sizes.spacing_md
_RADIUS_CACHE: dict[tuple[str, str], sizes.Size] = {}


def _radius_size(control: str, card: str) -> sizes.Size:
    key = (control, card)
    if key not in _RADIUS_CACHE:
        _RADIUS_CACHE[key] = sizes.Size(xxs="2px", xs="4px", sm=control, md=control, lg=card, xl=card,
                                        xxl=card, name=f"radius_twin_{control}_{card}")
    return _RADIUS_CACHE[key]


def _primary_scale(light: dict[str, str], dark: dict[str, str]) -> colors.Color:
    """One accent, eleven stops: the dark-mode accent sits at 400, the light-mode accent at 600."""
    acc_l, acc_d = light["accent"], dark["accent"]
    return colors.Color(
        c50=_mix("#FFFFFF", acc_d, 0.10), c100=light["accent-soft"], c200=_mix("#FFFFFF", acc_d, 0.45),
        c300=_mix("#FFFFFF", acc_d, 0.72), c400=acc_d, c500=_mix(acc_d, acc_l, 0.5), c600=acc_l,
        c700=_mix(acc_l, "#000000", 0.18), c800=_mix(acc_l, "#000000", 0.36),
        c900=_mix(acc_l, "#000000", 0.54), c950=_mix(acc_l, "#000000", 0.70), name="twin_ink",
    )


def _neutral_scale(light: dict[str, str], dark: dict[str, str]) -> colors.Color:
    """One grey family anchored on the sheet: paper (50), borders (200/400), muted ink (600), the
    dark surfaces (800-950)."""
    strong = light["border-strong"]
    return colors.Color(
        c50=light["bg"], c100=_mix(light["bg"], light["border"], 0.5), c200=light["border"],
        c300=_mix(light["border"], strong, 0.5), c400=strong, c500=_mix(strong, light["text-muted"], 0.5),
        c600=light["text-muted"], c700=_mix(light["text-muted"], light["text"], 0.5),
        c800=dark["surface-raised"], c900=dark["surface"], c950=dark["bg"], name="twin_paper",
    )


def _font(name: str, weights: tuple[int, ...]) -> fonts.Font:
    if name.lower() in _LOCAL_FONTS:
        return fonts.Font(name)
    return fonts.GoogleFont(name, weights=weights)


class TwinTheme(gr.themes.Base):
    """Gradio theme built from a token sheet (see module docstring)."""

    def __init__(self, tokens: dict | None = None):
        tokens = tokens or load_tokens()
        if missing_tokens(tokens):
            raise ValueError("TwinTheme needs a validated token dict (use load_tokens())")
        tokens = dict(tokens, light=_derived(tokens["light"]), dark=_derived(tokens["dark"]))
        L, D = tokens["light"], tokens["dark"]
        body_font = _font(tokens.get("font_body") or "Source Sans 3", (400, 600, 700))
        font: list = [body_font, "ui-sans-serif", "system-ui", fonts.Font("Segoe UI"), "sans-serif"]
        if tokens.get("font_serif"):
            # After the generic keyword it never wins the body stack; it is here so Gradio emits the
            # Google Fonts link. static/twin.css uses it through --twin-font-serif (quote cards, name).
            font.append(_font(tokens["font_serif"], (400, 600)))
        mono_name = tokens.get("font_mono") or "Consolas"
        font_mono: list = [_font(mono_name, (400, 600)), fonts.Font("Cascadia Mono"), "ui-monospace",
                           fonts.Font("Menlo"), "monospace"]
        primary = _primary_scale(L, D)
        super().__init__(
            primary_hue=primary, secondary_hue=primary, neutral_hue=_neutral_scale(L, D),
            text_size=_TEXT_SIZE, spacing_size=_SPACING,
            radius_size=_radius_size(tokens["radius_control"], tokens["radius_card"]),
            font=font, font_mono=font_mono,
        )
        self.name = "twin"
        self._tokens = tokens  # underscore: _get_theme_css() would otherwise emit it as a CSS var
        s1, s2 = _shadows("light", L)
        placeholder_l = _mix(L["text-muted"], L["border-strong"], 0.5)
        placeholder_d = _mix(D["text-muted"], D["border-strong"], 0.5)
        self.set(
            # page and blocks
            body_background_fill=L["bg"], body_background_fill_dark=D["bg"],
            body_text_color=L["text"], body_text_color_dark=D["text"],
            body_text_color_subdued=L["text-muted"], body_text_color_subdued_dark=D["text-muted"],
            body_text_size="*text_md", body_text_weight="400",
            background_fill_primary=L["surface"], background_fill_primary_dark=D["surface"],
            background_fill_secondary=L["bg"], background_fill_secondary_dark=D["bg"],
            block_background_fill=L["surface"], block_background_fill_dark=D["surface"],
            block_border_color=L["border"], block_border_color_dark=D["border"],
            block_border_width="1px",
            border_color_primary=L["border"], border_color_primary_dark=D["border"],
            border_color_accent=L["accent"], border_color_accent_dark=D["accent"],
            border_color_accent_subdued=L["accent-soft"], border_color_accent_subdued_dark=D["accent-soft"],
            panel_background_fill=L["bg"], panel_background_fill_dark=D["bg"],
            panel_border_color=L["border"], panel_border_color_dark=D["border"],
            color_accent=L["accent"], color_accent_soft=L["accent-soft"], color_accent_soft_dark=D["accent-soft"],
            # elevation: blocks are flat; two levels exist for the result cards and popovers
            block_shadow="none", shadow_drop=s1, shadow_drop_lg=s2,
            shadow_spread="3px", shadow_spread_dark="3px",
            # radius rule: controls sm (6px), containers lg (10px)
            block_radius="*radius_lg", container_radius="*radius_lg", table_radius="*radius_lg",
            input_radius="*radius_sm", checkbox_border_radius="*radius_xs",
            button_large_radius="*radius_sm", button_medium_radius="*radius_sm", button_small_radius="*radius_sm",
            # labels: sentence case, semibold, no tracking (never uppercase eyebrows)
            block_label_background_fill=L["surface"], block_label_background_fill_dark=D["surface"],
            block_label_border_color=L["border"], block_label_border_color_dark=D["border"],
            block_label_text_color=L["text-muted"], block_label_text_color_dark=D["text-muted"],
            block_label_text_size="*text_sm", block_label_text_weight="600",
            block_title_text_color=L["text"], block_title_text_color_dark=D["text"],
            block_title_text_size="*text_sm", block_title_text_weight="600",
            block_info_text_color=L["text-muted"], block_info_text_color_dark=D["text-muted"],
            block_info_text_size="*text_sm",
            section_header_text_weight="600", prose_header_text_weight="600",
            accordion_text_color=L["text"], accordion_text_color_dark=D["text"],
            # primary button: an accent outline on transparent (Nocturne: "Outline primary actions"); hover fills the
            # accent tint and lights a glow, so the one action per area still reads as the one to press
            button_border_width="1px",
            button_primary_background_fill="transparent", button_primary_background_fill_dark="transparent",
            button_primary_background_fill_hover=L["accent-soft"], button_primary_background_fill_hover_dark=D["accent-soft"],
            button_primary_border_color=L["accent"], button_primary_border_color_dark=D["accent"],
            button_primary_border_color_hover=L["accent"], button_primary_border_color_hover_dark=D["accent"],
            button_primary_text_color=L["accent"], button_primary_text_color_dark=D["accent"],
            button_primary_text_color_hover=L["accent"], button_primary_text_color_hover_dark=D["accent"],
            button_primary_shadow="none",
            button_primary_shadow_hover=f"0 0 14px {_rgba(L['accent'], 0.25)}",
            button_primary_shadow_hover_dark=f"0 0 16px {_rgba(D['accent'], 0.4)}",
            button_primary_shadow_active="none",
            # secondary button: outlined
            button_secondary_background_fill=L["surface"], button_secondary_background_fill_dark=D["surface"],
            button_secondary_background_fill_hover=L["accent-soft"], button_secondary_background_fill_hover_dark=D["accent-soft"],
            button_secondary_border_color=L["border-strong"], button_secondary_border_color_dark=D["border-strong"],
            button_secondary_border_color_hover=L["accent"], button_secondary_border_color_hover_dark=D["accent"],
            button_secondary_text_color=L["text"], button_secondary_text_color_dark=D["text"],
            button_secondary_text_color_hover=L["text"], button_secondary_text_color_hover_dark=D["text"],
            button_secondary_shadow="none", button_secondary_shadow_hover="none", button_secondary_shadow_active="none",
            # stop/cancel button: outlined in the error colour, fills on hover
            button_cancel_background_fill=L["err-soft"], button_cancel_background_fill_dark=D["err-soft"],
            button_cancel_background_fill_hover=L["err"], button_cancel_background_fill_hover_dark=D["err"],
            button_cancel_border_color=L["err"], button_cancel_border_color_dark=D["err"],
            button_cancel_border_color_hover=L["err"], button_cancel_border_color_hover_dark=D["err"],
            button_cancel_text_color=L["err"], button_cancel_text_color_dark=D["err"],
            button_cancel_text_color_hover=L["accent-ink"], button_cancel_text_color_hover_dark=D["accent-ink"],
            button_cancel_shadow="none", button_cancel_shadow_hover="none", button_cancel_shadow_active="none",
            button_transform_hover="none", button_transform_active="none",
            button_transition="background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease",
            # inputs
            input_background_fill=L["surface"], input_background_fill_dark=D["surface"],
            input_background_fill_hover=L["surface"], input_background_fill_hover_dark=D["surface"],
            input_background_fill_focus=L["surface"], input_background_fill_focus_dark=D["surface"],
            input_border_color=L["border-strong"], input_border_color_dark=D["border-strong"],
            input_border_color_hover=_mix(L["border-strong"], L["text-muted"], 0.5),
            input_border_color_hover_dark=_mix(D["border-strong"], D["text-muted"], 0.5),
            input_border_color_focus=L["focus"], input_border_color_focus_dark=D["focus"],
            input_border_width="1px",
            input_shadow="none", input_shadow_dark="none",
            input_shadow_focus=f"0 0 0 3px {_rgba(L['focus'], 0.3)}",
            input_shadow_focus_dark=f"0 0 0 3px {_rgba(D['focus'], 0.3)}",
            input_placeholder_color=placeholder_l, input_placeholder_color_dark=placeholder_d,
            input_text_size="*text_md",
            # checkboxes and radios
            checkbox_background_color=L["surface"], checkbox_background_color_dark=D["surface"],
            checkbox_background_color_hover=L["surface"], checkbox_background_color_hover_dark=D["surface"],
            checkbox_background_color_focus=L["surface"], checkbox_background_color_focus_dark=D["surface"],
            checkbox_background_color_selected=L["accent"], checkbox_background_color_selected_dark=D["accent"],
            checkbox_border_color=L["border-strong"], checkbox_border_color_dark=D["border-strong"],
            checkbox_border_color_hover=L["accent"], checkbox_border_color_hover_dark=D["accent"],
            checkbox_border_color_focus=L["focus"], checkbox_border_color_focus_dark=D["focus"],
            checkbox_border_color_selected=L["accent"], checkbox_border_color_selected_dark=D["accent"],
            checkbox_border_width="1px",
            checkbox_label_background_fill=L["surface"], checkbox_label_background_fill_dark=D["surface"],
            checkbox_label_background_fill_hover=L["accent-soft"], checkbox_label_background_fill_hover_dark=D["accent-soft"],
            checkbox_label_background_fill_selected=L["surface"], checkbox_label_background_fill_selected_dark=D["surface"],
            checkbox_label_border_color=L["border"], checkbox_label_border_color_dark=D["border"],
            checkbox_label_border_color_hover=L["accent"], checkbox_label_border_color_hover_dark=D["accent"],
            checkbox_label_border_color_selected=L["accent"], checkbox_label_border_color_selected_dark=D["accent"],
            checkbox_label_text_color=L["text"], checkbox_label_text_color_dark=D["text"],
            checkbox_label_text_color_selected=L["text"], checkbox_label_text_color_selected_dark=D["text"],
            checkbox_label_shadow="none", checkbox_label_shadow_hover="none", checkbox_label_shadow_active="none",
            checkbox_label_text_weight="400",
            # sliders, loaders, progress, links
            slider_color=L["accent"], slider_color_dark=D["accent"],
            loader_color=L["accent"], loader_color_dark=D["accent"],
            stat_background_fill=L["accent"], stat_background_fill_dark=D["accent"],
            link_text_color=L["accent"], link_text_color_dark=D["accent"],
            link_text_color_hover=_mix(L["accent"], "#000000", 0.2), link_text_color_hover_dark=_mix(D["accent"], "#FFFFFF", 0.2),
            link_text_color_active=L["accent"], link_text_color_active_dark=D["accent"],
            link_text_color_visited=L["accent"], link_text_color_visited_dark=D["accent"],
            # inline errors: tinted field, coloured border and text
            error_background_fill=L["err-soft"], error_background_fill_dark=D["err-soft"],
            error_border_color=L["err"], error_border_color_dark=D["err"],
            error_border_width="1px",
            error_text_color=L["err"], error_text_color_dark=D["err"],
            error_icon_color=L["err"], error_icon_color_dark=D["err"],
            # tables (no header variable exists: static/twin.css paints headers on our ids)
            table_border_color=L["border"], table_border_color_dark=D["border"],
            table_odd_background_fill=L["surface"], table_odd_background_fill_dark=D["surface"],
            table_even_background_fill=L["bg"], table_even_background_fill_dark=_mix(D["surface"], D["surface-raised"], 0.5),
            table_text_color=L["text"], table_text_color_dark=D["text"],
            table_row_focus=L["accent-soft"], table_row_focus_dark=D["accent-soft"],
            # code blocks (trace panels) sit on the page ground
            code_background_fill=L["bg"], code_background_fill_dark=D["bg"],
            chatbot_text_size="*text_md",
        )
        self.custom_css = tokens_css(tokens)

    @property
    def tokens(self) -> dict:
        return self._tokens


def build_theme(tokens: dict | None = None) -> TwinTheme:
    """The app's theme from a validated token dict (default: load_tokens())."""
    return TwinTheme(tokens=tokens)


tokens_to_theme = build_theme


def css_text() -> str:
    """static/twin.css followed by sorted(static/tabs/*.css); '' when neither exists. Read at call
    time from config.STATIC_DIR so tests can point it elsewhere."""
    static = Path(config.STATIC_DIR)
    parts: list[str] = []
    main = static / "twin.css"
    if main.exists():
        parts.append(main.read_text(encoding="utf-8"))
    for extra in sorted((static / "tabs").glob("*.css")):
        parts.append(f"/* {extra.name} */\n" + extra.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """python -m twin.ui.theme: print the token sheet in use and the body-text contrast table; exit 1
    when any pair is under 4.5:1."""
    tokens = load_tokens()
    print(f"tokens: {tokens['path']}")
    print(f"fonts: body {tokens['font_body'] or '-'}, serif {tokens['font_serif'] or '-'}, mono {tokens['font_mono'] or '-'}")
    print(f"radius: {tokens['radius_control']} controls, {tokens['radius_card']} cards; default theme {tokens['default_theme']}")
    bad = 0
    for mode, fg, bg, ratio in contrast_report(tokens):
        ok = ratio >= MIN_BODY_CONTRAST
        bad += 0 if ok else 1
        print(f"{mode:>5}  {fg:>10} on {bg:<8} {ratio:5.2f}  {'ok' if ok else 'LOW'}")
    theme = build_theme(tokens)
    print(f"theme: {type(theme).__name__}, {len(theme._stylesheets)} font stylesheet(s), css {len(css_text())} chars")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

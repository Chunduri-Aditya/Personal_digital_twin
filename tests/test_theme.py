"""Tests for twin/ui/theme.py: token sheet parsing, WCAG contrast, theme construction and CSS
hygiene. Reads files only: no model, no network, no app boot."""
from __future__ import annotations

import re
from pathlib import Path

import gradio as gr
import pytest

from twin import config
from twin.ui import theme

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
# Gradio-internal selectors that static/**/*.css must never target (docs/PLAN_UNIFIED.md 3.8).
FORBIDDEN = re.compile(r"svelte-|\.block\b|\.gradio-container|\.prose\b|\.wrap\b|\.gr-")
OUR_SELECTORS = (
    "#twin-header", "#gpu-note", "#status-strip", "#twin-tabs", '[id^="tab-"]', ".placeholder-card",
    ".verdict-card", ".confidence-meter", ".chip", ".trace", ".badge-ok", ".badge-warn", ".badge-err",
    ".quote-card", ".model-table",
)

SMALL_SHEET = """# tiny sheet

Some prose before the table.

| token | light | dark | note |
|---|---|---|---|
| bg | #ffffff | #000000 | page |
| surface | #FAFAFA | #111111 | blocks |
| surface-raised | #ffffff | #1a1a1a | cards |
| text | #111111 | #eeeeee | ink |
| text-muted | #555555 | #aaaaaa | secondary |
| accent | #123456 | #abcdef | one accent |
| accent-ink | #ffffff | #000000 | on accent |
| accent-soft | #e0e8f0 | #223344 | tint |
| border | #dddddd | #333333 | 1px |
| ok | #006600 | #66cc66 | |
| warn | #884400 | #ddaa44 | |
| err | #aa0000 | #ff8888 | |
| focus | #123456 | #abcdef | ring |

font-body: Test Sans
font-serif: Test Serif
font-mono: Consolas
radius: 4px controls, 12px cards
default_theme: dark
"""


def _css_vars(block: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"--twin-([a-z0-9-]+)\s*:\s*([^;]+);", block)}


def _block(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start:css.index("}", start)]


# ----------------------------------------------------------------------------- theme object

def test_build_theme_returns_twin_theme():
    t = theme.build_theme()
    assert type(t).__name__ == "TwinTheme"
    assert isinstance(t, gr.themes.Base)
    assert t.name == "twin"
    assert theme.tokens_to_theme is theme.build_theme


def test_default_theme_fonts_shadows_and_radius():
    t = theme.build_theme(theme.load_tokens(config.DEFAULT_DESIGN_TOKENS_PATH))
    assert any("Source+Sans+3" in s for s in t._stylesheets)      # body font from Google Fonts
    assert any("Source+Serif+4" in s for s in t._stylesheets)     # the twin's voice face
    assert not any("Consolas" in s for s in t._stylesheets)       # mono is local
    assert t.font.startswith("'Source Sans 3'") and "sans-serif" in t.font
    assert t.font_mono.startswith("'Consolas'")
    assert t.block_shadow == "none"                                # flat blocks
    assert "rgba(" in t.shadow_drop and "rgba(" in t.shadow_drop_lg and t.shadow_drop != t.shadow_drop_lg
    assert t.radius_sm == "6px" and t.radius_lg == "10px"
    assert t.input_radius == "*radius_sm" and t.block_radius == "*radius_lg"
    assert t.text_md == "15px"


def test_theme_css_renders_tokens():
    tokens = theme.load_tokens()
    t = theme.build_theme(tokens)
    css = t._get_theme_css()
    # primary actions are accent outlines on transparent (docs/design/tokens.md section 1)
    assert "--button-primary-background-fill: transparent;" in css
    assert f"--button-primary-border-color: {tokens['light']['accent']};" in css
    assert f"--button-primary-text-color: {tokens['light']['accent']};" in css
    assert f"--body-background-fill: {tokens['dark']['bg']};" in css
    assert ":root.dark" in css
    # the theme carries the --twin-* variables so a re-exported tokens.md wins over twin.css defaults
    assert f"--twin-accent: {tokens['light']['accent']};" in css
    assert "body.dark.dark {" in css and "color-scheme: dark;" in css


def test_theme_uses_values_from_a_custom_sheet(tmp_path):
    sheet = tmp_path / "tokens.md"
    sheet.write_text(SMALL_SHEET, encoding="utf-8")
    tokens = theme.load_tokens(sheet)
    t = theme.build_theme(tokens)
    d = t.to_dict()["theme"]
    assert d["button_primary_border_color"] == "#123456" and d["button_primary_text_color"] == "#123456"
    assert d["button_primary_border_color_dark"] == "#ABCDEF" and d["button_primary_background_fill"] == "transparent"
    assert d["button_primary_background_fill_hover_dark"] == "#223344"             # the accent tint on hover
    assert d["body_background_fill"] == "#FFFFFF" and d["body_background_fill_dark"] == "#000000"
    assert d["button_secondary_background_fill"] == "#FAFAFA"       # outlined: surface fill
    assert d["input_background_fill_dark"] == "#111111"
    assert t.radius_sm == "4px" and t.radius_lg == "12px"
    assert any("Test+Sans" in s for s in t._stylesheets) and any("Test+Serif" in s for s in t._stylesheets)
    assert "--twin-accent: #123456;" in t.custom_css and "--twin-accent: #ABCDEF;" in t.custom_css
    assert "--twin-border-strong:" in t.custom_css                  # derived when the sheet omits it


# ----------------------------------------------------------------------------- token sheet

def test_sheet_in_use_has_every_required_token():
    """Whichever sheet the app resolves (docs/design/tokens.md when present) parses completely."""
    tokens = theme.load_tokens()
    assert tokens["path"].endswith(("tokens.default.md", "tokens.md"))
    assert theme.missing_tokens(tokens) == [] and tokens["default_theme"] in ("light", "dark")
    assert tokens["font_body"] and tokens["radius_control"].endswith("px") and tokens["radius_card"].endswith("px")


def test_default_sheet_has_every_required_token():
    tokens = theme.load_tokens(config.DEFAULT_DESIGN_TOKENS_PATH)
    assert tokens["path"].endswith("tokens.default.md")
    for mode in ("light", "dark"):
        for name in theme.REQUIRED_TOKENS:
            assert re.fullmatch(r"#[0-9A-F]{6}", tokens[mode][name]), (mode, name, tokens[mode].get(name))
        for name in theme.OPTIONAL_TOKENS:
            assert re.fullmatch(r"#[0-9A-F]{6}", tokens[mode][name]), (mode, name)
    assert tokens["font_body"] == "Source Sans 3"
    assert tokens["font_serif"] == "Source Serif 4"
    assert tokens["font_mono"] == "Consolas"
    assert tokens["radius_control"] == "6px" and tokens["radius_card"] == "10px"
    assert tokens["default_theme"] == "light"


def test_parse_tokens_round_trips_a_small_table():
    tokens = theme.parse_tokens(SMALL_SHEET)
    assert theme.missing_tokens(tokens) == []
    assert tokens["light"]["bg"] == "#FFFFFF" and tokens["dark"]["bg"] == "#000000"
    assert tokens["light"]["accent"] == "#123456" and tokens["dark"]["accent"] == "#ABCDEF"
    assert tokens["notes"]["bg"] == "page" and tokens["notes"]["ok"] == ""
    assert tokens["font_body"] == "Test Sans"
    assert tokens["font_serif"] == "Test Serif"
    assert tokens["font_mono"] == "Consolas"
    assert tokens["radius"] == "4px controls, 12px cards"
    assert tokens["radius_control"] == "4px" and tokens["radius_card"] == "12px"
    assert tokens["default_theme"] == "dark"
    assert set(tokens["light"]) == set(theme.REQUIRED_TOKENS)


def test_parse_tokens_reports_missing_and_defaults():
    broken = SMALL_SHEET.replace("| focus |", "| ring |").replace("radius: 4px controls, 12px cards\n", "")
    tokens = theme.parse_tokens(broken)
    assert theme.missing_tokens(tokens) == ["light:focus", "dark:focus"]
    assert tokens["radius_control"] == "6px" and tokens["radius_card"] == "10px"
    assert theme.parse_tokens("no table here")["light"] == {}
    with pytest.raises(ValueError):
        theme.TwinTheme(tokens)


def test_load_tokens_prefers_user_sheet_and_falls_back_when_broken(tmp_path, monkeypatch, capsys):
    user_sheet = tmp_path / "tokens.md"
    monkeypatch.setattr(config, "DESIGN_TOKENS_PATH", user_sheet)
    assert theme.resolve_tokens_path() == config.DEFAULT_DESIGN_TOKENS_PATH
    user_sheet.write_text(SMALL_SHEET, encoding="utf-8")
    tokens = theme.load_tokens()
    assert tokens["path"] == str(user_sheet) and tokens["light"]["accent"] == "#123456"
    user_sheet.write_text("# exported but empty\n", encoding="utf-8")
    tokens = theme.load_tokens()
    assert tokens["path"] == str(config.DEFAULT_DESIGN_TOKENS_PATH)
    assert "lacks" in capsys.readouterr().err


# ----------------------------------------------------------------------------- contrast

def test_contrast_ratio_black_white():
    assert theme.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio("#fff", "#FFFFFF") == pytest.approx(1.0, abs=1e-9)
    assert theme.contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the classic AA grey


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("fg,bg", theme.BODY_TEXT_PAIRS)
def test_body_text_pairs_reach_aa(mode, fg, bg):
    tokens = theme.load_tokens()
    ratio = theme.contrast_ratio(tokens[mode][fg], tokens[mode][bg])
    assert ratio >= theme.MIN_BODY_CONTRAST, f"{mode}: {fg} on {bg} = {ratio:.2f}"


def test_check_contrast_passes_and_catches_a_bad_pair():
    assert theme.check_contrast() == []
    bad = theme.parse_tokens(SMALL_SHEET.replace("| text | #111111 | #eeeeee |", "| text | #cccccc | #333333 |"))
    failures = theme.check_contrast(bad)
    assert {(m, fg, bg) for m, fg, bg, _ in failures} >= {("light", "text", "bg"), ("dark", "text", "bg")}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_semantic_and_muted_text_readable_on_surfaces(mode):
    """Design target beyond the contract: badges, muted labels and links stay AA on every surface."""
    t = theme.load_tokens()[mode]
    for fg in ("ok", "warn", "err", "accent", "text-muted"):
        for bg in ("bg", "surface", "surface-raised"):
            assert theme.contrast_ratio(t[fg], t[bg]) >= 4.5, (mode, fg, bg)
    for sem in ("ok", "warn", "err"):
        assert theme.contrast_ratio(t[sem], t[f"{sem}-soft"]) >= 4.5, (mode, sem)
    assert theme.contrast_ratio(t["border-strong"], t["surface"]) >= 3.0, mode  # WCAG 1.4.11 for input edges


# ----------------------------------------------------------------------------- CSS

def test_css_text_contains_our_selectors_and_tokens():
    css = theme.css_text()
    for sel in OUR_SELECTORS:
        assert sel in css, sel
    assert "@media (max-width: 400px)" in css
    assert "#twin-tabs" in css[css.index("@media (max-width: 400px)"):]
    assert "#twin-masthead" in css and "#twin-avatar" in css and "@media (max-width: 600px)" in css   # frame.css
    assert "font-variant-numeric: tabular-nums" in css
    assert "--twin-bg:" in css and "body.dark {" in css and "color-scheme: dark" in css


def test_no_internal_gradio_selectors_in_static_css():
    files = sorted(STATIC.rglob("*.css"))
    assert files, "static/twin.css missing"
    for f in files:
        text = f.read_text(encoding="utf-8")
        hit = FORBIDDEN.search(text)
        assert hit is None, f"{f.relative_to(ROOT)}: forbidden selector {hit.group(0)!r}"


def test_twin_css_defaults_match_the_default_sheet():
    """static/twin.css keeps readable defaults; they must equal the sheet theme.py parses."""
    css = (STATIC / "twin.css").read_text(encoding="utf-8")
    tokens = theme.load_tokens(config.DEFAULT_DESIGN_TOKENS_PATH)
    for selector, mode in ((":root", "light"), ("body.dark", "dark")):
        found = _css_vars(_block(css, selector))
        expected = theme.css_variables(tokens, mode)
        for name in theme.REQUIRED_TOKENS + theme.OPTIONAL_TOKENS + ("radius-control", "radius-card"):
            assert found.get(name, "").upper() == expected[name].upper(), (selector, name, found.get(name))


def test_css_text_concatenates_tab_partials_sorted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATIC_DIR", tmp_path)
    assert theme.css_text() == ""
    (tmp_path / "twin.css").write_text("#twin-header { color: red; }", encoding="utf-8")
    (tmp_path / "tabs").mkdir()
    (tmp_path / "tabs" / "b.css").write_text("#tab-b {}", encoding="utf-8")
    (tmp_path / "tabs" / "a.css").write_text("#tab-a {}", encoding="utf-8")
    out = theme.css_text()
    assert out.startswith("#twin-header")
    assert out.index("#tab-a") < out.index("#tab-b")


# ----------------------------------------------------------------------------- frame contract (P3)

FRAME_ROOTS = ("#twin-masthead", "#twin-avatar", "#twin-header", "#gpu-note", "#status-strip", "#twin-tabs")
# Shared component classes the tab lanes build on (static/twin.css, docs/design/tokens.default.md section 7).
CONTRACT_CLASSES = (
    "twin-intro", "twin-section", "twin-panel", "twin-card", "twin-result", "twin-actions", "twin-quiet",
    "twin-caution", "twin-hint", "twin-empty", "twin-split", "twin-table", "placeholder-card", "verdict-card",
    "confidence-meter", "quote-card", "chip", "badge-ok", "badge-warn", "badge-err", "trace", "model-table",
)
TOKEN_BLOCKS = ([":root"], ["body.dark"])
# Colour literals a stylesheet must take from --twin-* instead (transparent, currentColor and inherit are fine).
COLOUR_LITERAL = re.compile(
    r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(|"
    r"\b(?:white|black|red|green|blue|gr[ae]y|orange|yellow|purple|pink|brown|silver|navy)\b", re.IGNORECASE)
# static/tabs/<stem>.css files whose stem differs from the tab id they style.
PARTIAL_TAB = {"evals": "eval"}


def _selectors(prelude: str) -> list[str]:
    """Split a selector list on top-level commas (commas inside :is() or :not() stay put)."""
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [p for p in parts + [cur.strip()] if p]


def _rules(css: str) -> list[tuple[list[str], str]]:
    """(selectors, declarations) for every style rule, descending into @media/@supports; @keyframes are skipped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[list[str], str]] = []
    i = 0
    while (j := css.find("{", i)) >= 0:
        depth, k = 1, j + 1
        while k < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        prelude, body = css[i:j].strip(), css[j + 1:k - 1]
        if prelude.startswith(("@media", "@supports")):
            out.extend(_rules(body))
        elif not prelude.startswith("@"):
            out.append((_selectors(prelude), body))
        i = k
    return out


def _scoped(selector: str, roots: tuple[str, ...]) -> bool:
    """The selector starts with one of `roots` (optionally after `body.dark `), not a longer id like #tab-ask-button."""
    s = selector[len("body.dark "):].lstrip() if selector.startswith("body.dark ") else selector
    return any(re.match(re.escape(root) + r"(?![\w-])", s) for root in roots)


def test_css_rule_parser_handles_media_and_selector_lists():
    rules = _rules("/* a { } */ #x, #y :is(.a, .b) { color: red; } @media (max-width: 1px) { #z > p { margin: 0; } }"
                   " @keyframes k { 0% { opacity: 0; } }")
    assert [sels for sels, _ in rules] == [["#x", "#y :is(.a, .b)"], ["#z > p"]]
    assert _scoped("#tab-ask .x", ("#tab-ask",)) and _scoped("body.dark #tab-ask", ("#tab-ask",))
    assert not _scoped("#tab-ask-button", ("#tab-ask",)) and not _scoped(".x #tab-ask", ("#tab-ask",))


def test_twin_css_rules_live_under_twin_tabs():
    """twin.css holds the two token blocks, then base and shared-component rules that all start with #twin-tabs."""
    rules = _rules((STATIC / "twin.css").read_text(encoding="utf-8"))
    assert [sels for sels, _ in rules if sels in TOKEN_BLOCKS] == [[":root"], ["body.dark"]]
    for sels, _ in rules:
        if sels in TOKEN_BLOCKS:
            continue
        for s in sels:
            assert _scoped(s, ("#twin-tabs",)), f"twin.css: {s!r} is not scoped under #twin-tabs"


def test_contract_classes_defined_in_twin_css():
    selectors = [s for sels, _ in _rules((STATIC / "twin.css").read_text(encoding="utf-8")) for s in sels]
    for cls in CONTRACT_CLASSES:
        pat = re.compile(r"\." + re.escape(cls) + r"(?![\w-])")
        assert any(pat.search(s) for s in selectors), f"twin.css has no rule for .{cls}"


def test_frame_css_is_scoped_to_the_frame_ids():
    path = STATIC / "tabs" / "frame.css"
    rules = _rules(path.read_text(encoding="utf-8"))
    assert rules, "static/tabs/frame.css is empty"
    for sels, _ in rules:
        for s in sels:
            assert _scoped(s, FRAME_ROOTS), f"frame.css: {s!r} does not start with a frame id"
    found = {root for sels, _ in rules for s in sels for root in FRAME_ROOTS if _scoped(s, (root,))}
    assert found == set(FRAME_ROOTS), sorted(set(FRAME_ROOTS) - found)


def test_tab_partials_scope_every_selector_to_their_tab():
    """P4 contract: every static/tabs/<tab>.css except frame.css starts each selector with #tab-<id>."""
    from twin.ui import frame
    for path in sorted((STATIC / "tabs").glob("*.css")):
        if path.stem == "frame":
            continue
        tab = PARTIAL_TAB.get(path.stem, path.stem)
        assert tab in frame.TAB_IDS, f"static/tabs/{path.name}: {tab!r} is not one of {frame.TAB_IDS}"
        for sels, _ in _rules(path.read_text(encoding="utf-8")):
            for s in sels:
                assert _scoped(s, (f"#tab-{tab}",)), f"static/tabs/{path.name}: {s!r} does not start with #tab-{tab}"


def test_static_css_takes_colours_from_tokens_only():
    """No colour literal and no --twin-* redefinition outside twin.css's two token blocks."""
    for path in sorted(STATIC.rglob("*.css")):
        for sels, body in _rules(path.read_text(encoding="utf-8")):
            if path == STATIC / "twin.css" and sels in TOKEN_BLOCKS:
                continue
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, value = (part.strip() for part in decl.split(":", 1))
                where = f"{path.relative_to(ROOT)} {', '.join(sels)} {{ {name}: {value} }}"
                assert not name.startswith("--twin-"), f"redefines a token: {where}"
                assert COLOUR_LITERAL.search(value) is None, f"colour literal: {where}"


def test_masthead_monogram_helpers():
    from twin.ui import frame
    assert frame.avatar_initial("Mara Ellison") == "M"
    assert frame.avatar_initial("  (x) élodie") == "X"
    assert frame.avatar_initial("") == "" and frame.avatar_initial(None) == ""
    assert frame.avatar_html("mara") == '<span class="twin-avatar" aria-hidden="true">M</span>'
    assert frame.avatar_html("--") == "" and frame.avatar_html(None) == ""

# Design tokens (default sheet): the twin console

Written 2026-09-14 by the tokens agent (Workflow A, A3 in `docs/PLAN_UNIFIED.md`). `docs/design/tokens.md`, the Claude Design export, was absent, so this file holds the `frontend-design` two-pass plan the plan's section 2 table names as the fallback. `twin/ui/theme.py` reads `tokens.md` first whenever it appears and this file otherwise; section 6 is the block it parses. Everything else in this file is the reasoning, kept so the per-tab restyle agents (Workflow C) inherit the same decisions.

## 1. Subject

A private console for one person's digital twin. The owner opens it on their own laptop to talk to a small local model that answers in their texting voice, predicts their decisions, runs tools, reacts to images and grades itself against their real answers; sometimes a friend or a reviewer is looking over their shoulder. It is not a product and not a chatbot: it is an instrument that belongs to one person, and it reports measurements (verdicts with confidence, bake-off tables, item scores, the model on the GPU right now).

Two things are always on screen at once: something the twin said or decided, and the reading that qualifies it (which model, how long, which chunks, how confident). The design's job is to keep those two legible from each other.

## 2. Pass one: the plan

### 2.1 Palette: paper and ink

The metaphor is a kept notebook: paper for the surfaces, one ink for everything the person touches. The accent is an iron-gall ink brown; the text is the same ink at full depth. That gives the "a little warm because it is about a person" of the brief without reaching for the warm clay/terracotta that every generated console uses, and it leaves red, amber and green free for the three states the instrument reports.

| name | light | dark | why |
|---|---|---|---|
| paper | `#F7F6F3` | `#1C1A17` | page ground. Barely warm (chroma about a third of a cream): paper, not parchment. Dark is a lifted warm charcoal, not a near-black. |
| sheet | `#FFFFFF` | `#252220` | blocks, inputs, chat bubbles. A raised sheet exists only in dark (`#2C2926`), where elevation is a lighter surface; in light it is the same white plus a shadow. |
| ink | `#1F1B17` | `#ECE7E0` | body text. The accent's own ink at full depth (hue 27), so text and accent are one material. |
| faded ink | `#5F574F` | `#A69E94` | secondary text, labels, footers. Same hue, less depth. |
| iron-gall | `#784B26` | `#C99666` | the one accent: primary buttons, active tab, links, the owner's monogram, meters, focus. HSL 27/52%/31% in light, 32/48%/59% in dark; saturation well under 80 percent. Far from red, amber and green, so a primary button never reads as a warning. |
| moss, ochre, madder | `#23744A` `#9A5B00` `#B3261E` | `#7BC88F` `#E4B15C` `#F08A80` | ok, warn, err. One hue each, plus a soft tint each for badges (`ok-soft`, `warn-soft`, `err-soft`). |

One grey family, warm, derived from paper and ink: `border` `#E3DFD8` / `#3A3632` for decorative separation and `border-strong` `#958D84` / `#7A736B` for edges that identify a control (inputs, outlined buttons), the latter computed to reach 3:1 against the surface (WCAG 1.4.11).

### 2.2 Type: the instrument speaks in a sans, the person speaks in a serif

- Body face: **Source Sans 3** (Google Fonts, 400/600/700). A humanist sans with true italics, a tall x-height that survives 13 px table cells, and tabular figures through `font-variant-numeric`. It is neither Gradio's own IBM Plex Sans nor the Inter/Roboto reflex, and it has a matched serif from the same family.
- Voice face: **Source Serif 4** (Google Fonts, 400/600). Used only where the twin speaks as the person: the quote card ("Say it in my voice"), later the reply bubbles if the Ask restyle wants it, and the owner's name and monogram in the header. Typography encodes who is talking: a reading is sans, a voice is serif. Headings stay sans, so the serif never becomes the "editorial display" cliché.
- Trace face: **Consolas** (local on Windows; Cascadia Mono, ui-monospace, Menlo fallbacks). Only inside `.trace` panels, where the content is chunk ids, tool arguments, JSON and timings. Never for data labels, model names or numbers in tables.

Type scale (px): 11, 13, 15, 17, 20, 24, 32. Steps of about 1.15 to 1.2 for text, then 1.33 for the verdict figure, which is the only display size. Body 15/1.5; serif 17/1.6 (a serif gets a little more leading and may run slightly longer); labels 13/600; measure 68ch for any prose (header lines, quote card, placeholder cards). Weights 400, 600, 700 only. Sentence case everywhere, no letter-spacing on labels, no uppercase.

### 2.3 Layout

The global frame, every screen. Everything left-aligned; numbers right-aligned in tables; nothing centered.

```
+----------------------------------------------------------------------------------+
| [M] Mara Ellison                                                                  |
|     Profile data/twin_profile.md, index fresh, consent given 2026-09-01.          |
|     Warning: twin_profile.md is missing; using the example profile.               |
+------------------+---------------------------------------------------------------+
| GPU 3.1 of 8 GB  |  Ask   Decide   Act   See   Items   Eval   Status              |
| LM Studio        |  -------                                                      |
|   stheno (loaded)|                                                               |
| Ollama           |  [ tab content, left-aligned, max width 1440 ]                |
|   qwen3 100% 8k  |                                                               |
| Tab: Ask         |                                                               |
| * ready          |                                                               |
+------------------+---------------------------------------------------------------+
```

Ask at 1440. One primary action (Send). The trace is the only monospace surface and is collapsed by default.

```
| Chat with the twin                                                              |
|  [M] hey, what do you do on a slow sunday?                                      |
|                                   sleep in, then the market if it's not raining |
|                                                                                 |
| Message ....................................................  [ Send ] [Clear]  |
| Temperature ----o------ 1.0   [ ] Q8 voice (slow)   [ ] Consistency check       |
| Condition [ interview v ]                                                       |
| consistent (0 unsupported, 0 contradictions)   Looks like a tool request? Try Act|
| > Trace                                                                         |
```

Ask at 400: the sidebar collapses, the control row stacks to one column, buttons go full width at 44 px, the trace wraps.

```
| Chat with the twin        |
|  bubbles                  |
| Message                   |
| [        Send          ]  |
| [        Clear         ]  |
| Temperature ---o---  1.0  |
| [ ] Q8 voice (slow)       |
| [ ] Consistency check     |
| Condition [interview v]   |
| consistent (0, 0)         |
| > Trace                   |
```

Density is medium: 15 px body, 6 to 10 px cell padding in tables and the strip, 20 to 24 px inside cards.

### 2.4 Rules

- Corner radius: **6 px on anything you press or type into** (buttons, inputs, chips, badges, checkbox labels) and **10 px on anything that contains them** (blocks, cards, the trace, tables). Two values, one rule. Two hairline elements sit at 4 px because 6 px on a 16 px checkbox or an 8 px meter track reads as a circle.
- Shadows: two levels, and blocks have none. Level 1 (popovers, the quote card) and level 2 (the verdict card) are tinted with the ink (`rgba(31, 27, 23, …)`) so they belong to the paper. In dark mode the raised sheet is lighter and the shadow is plain black at a higher alpha; a tinted shadow on charcoal only muddies it. If something floats, it is a result.
- Numerals: `font-variant-numeric: tabular-nums` on every table, the status strip, meters and the verdict footer; numeric columns right-aligned; the strip never reflows as values tick.
- Focus: buttons and links get a 2 px outline in the accent with a 2 px offset; inputs get the accent border plus a 3 px ring at 30 percent. Both visible in both modes.
- Motion: only 150 to 250 ms colour and width transitions that answer an action (hover, focus, the meter filling). `prefers-reduced-motion` removes them. No entrance animations.
- Copy in states: loading text ends with an ellipsis character; inline errors say what happened and what to do next, never apologise; empty panels name the next action.

### 2.5 Three principles

1. **Paper and ink.** One warm neutral family and one ink. The accent at full depth is the text; the accent at button depth is the ink used for actions. Nothing else gets colour except the three states.
2. **Elevation is evidence.** Blocks are flat with a border. The only things that rise are results the person came for: the verdict card and the quote card. One raised element per screen.
3. **Numbers line up and voices are typeset.** Tabular figures everywhere a reading appears; the serif appears only where the twin speaks as the person, so a glance tells a measurement from a voice.

## 3. Pass two: the review against the anti-default clusters

Checked against the `frontend-design` skill's five clusters and the brief's own list. What changed during this pass is stated per item.

1. **Cream background + serif display + terracotta/clay accent.** The first draft had a warmer paper near the cream that every generated page uses, and a serif for headings. Changed: paper chroma cut to `#F7F6F3` (about a third of `#F4F1EA`'s), the serif confined to the twin's voice and the monogram, and the accent chosen far from clay: `#784B26` is a dark ink at 31 percent lightness, not a 59 percent clay. A red-family candidate (madder/oxblood) was dropped because a red primary button next to red error badges is a usability bug, and a brass/amber candidate (PLAN3's "primary solid amber") was dropped because it collides with the warning colour.
2. **Near-black + acid accent.** Dark ground is `#1C1A17`, a lifted warm charcoal; the dark accent is a desaturated caramel. Not applicable, and stated so the "tinted near-black standing in for black" check is answered: the light text `#1F1B17` is the accent's own ink at full depth, chosen for the metaphor, not a #111 posing as black.
3. **Broadsheet hairlines, zero radius, dense columns.** Radii are 6/10; borders are 1 px in a visible warm grey; tables separate rows by an even-row tint instead of rules; only table headers carry a rule.
4. **The SaaS card kit.** The first draft set `block_shadow` to a soft shadow on every block. Changed: blocks are flat (`block_shadow: none`), one border, and only the verdict and quote cards are raised, at two different levels. Cards are not identical: the verdict card is the only element with a display-size figure; the quote card is the only serif surface.
5. **Template chrome.** No ALL-CAPS eyebrows (labels are 13/600 sentence case with zero tracking); header meta is a sentence with commas, not middle dots; no "WORD — fragment" labels; monospace only in `.trace`; no arrows appended to button text; the monogram is a rounded square, not a circle, so the radius rule holds even there.
6. **The brief's extras.** No gradients (the progress fill is solid accent, where Gradio's default is a gradient), no glass, no noise, no illustrations or decorative icons, no scroll-triggered motion, one accent under 80 percent saturation, one grey family, one radius rule stated.

Where the brief pins a direction it is followed exactly: light-first with a complete dark variant, 1440 max width, Ask at 400, tabular numerals, monospace only in trace panels, Gradio-buildable blocks only.

## 4. Contrast, computed

WCAG 2.1 ratios from `twin.ui.theme.contrast_ratio` (the same function `tests/test_theme.py` runs). Body-text pairs must reach 4.5:1 in both modes; they do, with margin.

| pair | light | dark | rule |
|---|---|---|---|
| text on bg | 15.83 | 14.12 | body text, 4.5 |
| text on surface | 17.11 | 12.85 | body text, 4.5 |
| text on surface-raised | 17.11 | 11.76 | body text, 4.5 |
| text-muted on bg | 6.56 | 6.56 | body text, 4.5 |
| text-muted on surface | 7.09 | 5.98 | body text, 4.5 |
| accent-ink on accent | 7.41 | 6.65 | button text, 4.5 |
| accent on bg | 6.86 | 6.65 | links, 4.5 |
| accent on surface | 7.41 | 6.05 | links, chip ids, 4.5 |
| ok on bg | 5.30 | 8.68 | status text, 4.5 |
| warn on bg | 5.02 | 8.88 | status text, 4.5 |
| err on bg | 6.05 | 7.15 | status and error text, 4.5 |
| ok on ok-soft | 4.85 | 6.52 | badge text, 4.5 |
| warn on warn-soft | 4.64 | 6.40 | badge text, 4.5 |
| err on err-soft | 5.36 | 5.81 | badge text, 4.5 |
| accent on accent-soft | 6.08 | 5.04 | active tab, chips, 4.5 |
| placeholder on surface | 4.73 | 4.53 | derived: mix(text-muted, border-strong), 4.5 |
| border-strong on surface | 3.27 | 3.38 | control edges, 3.0 (WCAG 1.4.11) |
| border-strong on bg | 3.03 | 3.71 | control edges, 3.0 |
| focus on surface | 7.41 | 6.05 | focus outline, 3.0 |
| border on bg | 1.23 | 1.45 | decorative separation only, no rule |

## 5. How `twin/ui/theme.py` uses this sheet

- `parse_tokens()` reads the table and the key lines in section 6; `load_tokens()` validates the required tokens and derives `border-strong` and the three soft tints when a sheet omits them.
- `TwinTheme` builds the Gradio primary and neutral scales from the accent and the paper/ink anchors (dark accent at 400, light accent at 600; paper at 50, borders at 200/400, faded ink at 600, dark surfaces at 800 to 950), passes the body font as a `GoogleFont` (the serif rides on the same tuple so Gradio emits its stylesheet link; it sits after the generic keyword and never wins the body stack), and sets every colour, radius, shadow, button, input, checkbox, slider, link, error and table variable with its `_dark` counterpart from the dark column. Primary buttons are solid accent; secondary buttons are outlined with `border-strong`; the stop button is outlined in `err` and fills on hover. `block_shadow` is `none`; `shadow_drop` and `shadow_drop_lg` carry the two levels.
- The theme also carries the `--twin-*` custom properties (on `body` and `body.dark.dark`), which beat the defaults declared in `static/twin.css` (`:root` and `body.dark`), so a re-exported `tokens.md` restyles both Gradio and our own elements without code changes.
- `css_text()` returns `static/twin.css` followed by `static/tabs/*.css` in name order.
- `python -m twin.ui.theme` prints the sheet in use and the body-text contrast table and exits 1 when any pair is under 4.5.

## 6. Token sheet (parsed by theme.py)

| token | light | dark | note |
|---|---|---|---|
| bg | #F7F6F3 | #1C1A17 | page ground (paper / warm charcoal) |
| surface | #FFFFFF | #252220 | blocks, inputs, chat bubbles |
| surface-raised | #FFFFFF | #2C2926 | verdict and quote cards; light raises by shadow, dark by a lighter sheet |
| text | #1F1B17 | #ECE7E0 | body text: the ink at full depth |
| text-muted | #5F574F | #A69E94 | secondary text, labels, footers |
| accent | #784B26 | #C99666 | the one accent (iron-gall / caramel): primary buttons, active tab, links, monogram, meters |
| accent-ink | #FFFFFF | #1C1A17 | text on the accent |
| accent-soft | #F1E7DD | #3A2E24 | tint for chips, the active tab, hover fills |
| border | #E3DFD8 | #3A3632 | 1px decorative separation (blocks, cards, table headers) |
| border-strong | #958D84 | #7A736B | edges that identify a control: inputs, outlined buttons (3:1 on surface) |
| ok | #23744A | #7BC88F | moss: consistent, loaded, ready |
| warn | #9A5B00 | #E4B15C | ochre: stale, loading, ceiling pending |
| err | #B3261E | #F08A80 | madder: errors, inconsistent, stop button |
| ok-soft | #E1F0E6 | #22352A | badge tint for ok |
| warn-soft | #F8ECD6 | #3D3222 | badge tint for warn |
| err-soft | #F9E4E1 | #40241F | badge tint for err and inline error fields |
| focus | #784B26 | #C99666 | 2px outline with 2px offset; inputs add a 3px ring at 30 percent |

font-body: Source Sans 3
font-serif: Source Serif 4
font-mono: Consolas
radius: 6px controls, 10px cards
default_theme: light

## 7. Frame and shared classes (P3, 2026-09-14)

Written by the frame restyle agent (`docs/PLAN_FINISH.md` P3). The colours, fonts and radii above did not change. The frame adds static scales and a class contract, both in `static/twin.css`, and the frame layout in `static/tabs/frame.css`.

- **Static tokens** (not parsed; declared only in the `static/twin.css` token block):
  - spacing `--twin-space-1` to `--twin-space-8` on a 4 px grid (4, 8, 12, 16, 20, 24, 32)
  - `--twin-measure-wide` 80ch for tab intros and the header meta
  - `--twin-target` 44 px, `--twin-avatar` 48 px, `--twin-rule` 3 px (the gpu note rule and the open-tab underline) and `--twin-card-min` 64 px
  - `--twin-duration` 150 ms with `--twin-ease`
- **Masthead:** the monogram sits beside the persona header: the serif initial in `accent` on `accent-soft`, 48 px, card radius.
  - It is a tint, not a solid fill, because a solid accent fill is kept for the primary button.
  - The name is the serif at 24 px, the profile line 13 px faded ink, and the `**Warning:**` labels ochre.
  - The monogram hides at 600 px and below.
- **Gpu note:** an annotation line under the masthead: a left rule in `border-strong` on the sheet colour, with 15 px ink. It is 44 px tall so the tab-select loading overlay shows its timer.
- **Status strip:** the sheet colour with a `border` edge. Each reading puts its label (13/600, faded ink) on a line above its value (15 px ink, tabular figures), and the time sits under a rule.
- **Tab strip:**
  - Labels are 15/600 in faded ink; the open tab is ink over a 3 px `accent` rule, and hover fills `accent-soft`.
  - The strip reads `--twin-accent` directly. Gradio 6.27 has no dark value for `--color-accent`, so the open tab measured 2.3:1 on charcoal.
- **Page column:** the masthead, gpu note and tabs share one column, capped at 1440 px inside Gradio's own container, which stays at 1280 px on a 1440 px screen.
  - `gr.Blocks(fill_width=True)` was tried and reverted: it gave tables 80 px more, but it pushed the Onboarding Walkthrough's last step label past the right edge.
- **Shared classes for the tab lanes** (all scoped under `#twin-tabs`):
  - new: `.twin-intro`, `.twin-section`, `.twin-panel`, `.twin-card`, `.twin-result`, `.twin-actions`, `.twin-quiet`, `.twin-caution`, `.twin-hint`, `.twin-empty`, `.twin-split` and `.twin-table`
  - earlier: `.chip`, `.badge-ok`, `.badge-warn`, `.badge-err`, `.trace`, `.quote-card`, `.verdict-card`, `.confidence-meter`, `.model-table` and `.placeholder-card`
  - Identifiers in prose (`code` outside `pre`) use the body face in a quiet chip; monospace stays in `.trace`.
- **Partials:** `tests/test_theme.py` enforces three rules:
  - every selector in `static/tabs/<tab>.css` starts with `#tab-<id>`
  - no colour literals appear outside the two token blocks
  - no `--twin-*` property is redefined outside them

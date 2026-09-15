# Design tokens: the twin console on Nocturne

Drop this file at `docs/design/tokens.md` in `Personal_digital_twin`. `twin/ui/theme.py` reads `tokens.md` first and
`tokens.default.md` only when it is absent, so copying this file in restyles both the Gradio theme and every
`--twin-*` element with no CSS or Python change. Section 4 is the block `parse_tokens()` reads; everything else is
the reasoning, kept for the per-tab partials.

Source of the palette: the Nocturne design system (`_ds/nocturne-.../styles.css`, `readme.md`). Values below are
Nocturne ramp steps, named per step where they are taken verbatim.

## 1. What changed from the paper-and-ink sheet

- The ground is dark by default: `--color-bg` #161826 with `--color-surface` #232532. `default_theme` is `dark`.
- One accent, Nocturne's blurple #9184d9, used as a line, a rule and a glow. It replaces iron-gall brown in the
  same roles: primary buttons, active tab, links, monogram, meters, focus.
- Type is Inter for both faces. The "a reading is sans, a voice is typeset" rule survives, but the voice is now
  marked by the accent left rule and `accent-300` text on the quote card rather than by a serif, because Nocturne
  carries no serif. `font-serif` therefore resolves to Inter and the quote card's distinction is structural.
- Radii step down from 6/10 to Nocturne's 4/8: `radius: 4px controls, 8px cards`.
- Primary buttons become accent outlines on transparent, not solid fills (Nocturne: "Outline primary actions").
  That is a `theme.py` change, not a token change — see section 7.

## 2. Roles Nocturne does not define

Nocturne is a mono palette with no state colours, and the console reports three states (ok, warn, err) in badges,
the audit and the checker. They are added here at Nocturne's own chroma discipline: one hue each, low saturation,
far from the blurple accent, on the shared lightness scale so a badge carries the same visual weight as a ramp
step. They are the only values in the sheet that are not Nocturne ramp steps.

## 3. Contrast

Body-text pairs clear 4.5:1 in both columns, control edges clear 3:1. `python -m twin.ui.theme` prints the table
and exits 1 on a failure; run it after copying this file in. The tight pair is accent on accent-soft, which is why
`accent-soft` in the dark column is Nocturne's `accent-900` taken one step further toward the ground (#241F33,
4.99:1) rather than #2B2741 (4.45:1, a fail). The same check moved dark `surface-raised` off neutral-900 #292B31:
the verdict figure and the quote card put accent text on it, which measured 4.38:1 there and 4.53:1 on #262834.

## 4. Token sheet (parsed by theme.py)

| token | light | dark | note |
|---|---|---|---|
| bg | #E4E7F5 | #161826 | page ground: neutral-200 / Nocturne `--color-bg` |
| surface | #F3F5FE | #232532 | blocks, inputs, chat bubbles: neutral-100 / `--color-surface` |
| surface-raised | #FFFFFF | #262834 | verdict and quote cards; dark raises one step above the surface (neutral-900 #292B31 held accent at 4.38:1) |
| text | #292B31 | #E9E9ED | body text: neutral-900 / Nocturne `--color-text` |
| text-muted | #595D6C | #B2B6CA | secondary text, labels, footers: neutral-700 / neutral-400 |
| accent | #5D5294 | #9184D9 | the one accent: accent-700 on light, Nocturne blurple on dark |
| accent-ink | #F3F5FE | #161826 | text on the accent |
| accent-soft | #E7E5FE | #241F33 | tint for chips, the active tab, hover fills: accent-200 / accent-900 toward the ground |
| border | #CFD3E5 | #3F424D | 1px decorative separation: neutral-300 / neutral-800 |
| border-strong | #75798C | #75798C | edges that identify a control: neutral-600 both columns (3:1 on surface) |
| ok | #1F6D47 | #79C39A | consistent, loaded, ready (added: Nocturne defines no state colours) |
| warn | #8A5A12 | #DFB26A | stale, loading, ceiling pending (added) |
| err | #A32E2A | #E8908D | errors, inconsistent, stop button (added) |
| ok-soft | #DDEDE4 | #1B2C24 | badge tint for ok |
| warn-soft | #F4EAD8 | #2E2619 | badge tint for warn |
| err-soft | #F6E2E1 | #32201F | badge tint for err and inline error fields |
| focus | #5D5294 | #9184D9 | 2px outline with 2px offset; inputs add a 3px ring at 30 percent |

font-body: Inter
font-serif: Inter
font-mono: Consolas
radius: 4px controls, 8px cards
default_theme: dark

## 5. What this file does not do

Status, 2026-09-15: all four items below and the outlined primary buttons are built. The warnings disclosure starts
open, so the demo's header warning stays visible. The Status tiles are GPU memory, heartbeat, LM Studio and Ollama.
The Decide meter now redraws when the result markdown changes. The console opens in `default_theme` unless
`TWIN_THEME` or `?__theme=` says otherwise. Contract details are in `docs/CONTRACTS.md` "UI styling".

The token sheet carries colour, type, radius and shadow. The four wireframes also move things, and each one needs
code:

1. **Masthead readings** (`twin/ui/state.py: header_markdown`, `static/tabs/frame.css`) — the three tiles are new
   markup; the profile line and warnings become disclosures. Header text is assembled in `header_markdown()`, so
   this is a Python change plus frame CSS, and `tests/test_theme.py`'s selector rule still applies.
2. **Ask evidence rail** (`twin/ui/ask.py`, `static/tabs/ask.css`) — the rail is a `gr.Column` beside the chat fed
   by the trace, checker and hint outputs `/ask` already returns. No endpoint change: same five outputs, laid out
   as a rail instead of stacked panels. The Trace accordion stays for the full step list.
3. **Decide verdict row** (`twin/ui/decide.py`, `static/tabs/decide.css`) — the verdict card takes the full row and
   `Raw result` moves behind a disclosure. `/decide_b1` and `/decide_b2` keep both outputs, so the DEMO CONTRACT
   holds; only the container changes.
4. **Status tiles** (`twin/ui/status.py`, `static/tabs/status.css`) — `status_markdown()` currently returns one
   markdown block. The tiles need it split into named values, which is the only change here that touches an
   endpoint's return shape. Safest route: keep `/status` returning the same markdown and add the tiles as a second,
   private GET-only component fed by `MANAGER.status()`.

Outlined primary buttons (Nocturne's rule) are a `TwinTheme` change in `twin/ui/theme.py`: `button_primary_background_fill`
becomes transparent with `button_primary_border_color` on the accent. That inverts the console's current rule that a
solid accent fill means "press me", which is what keeps `.twin-caution` and the monogram distinct — decide that one
before the restyle, because every tab partial leans on it.

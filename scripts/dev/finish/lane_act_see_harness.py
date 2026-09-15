"""Static harness for the P4 act_see lane (read-only; no app, no port, no model).

ui_check.ps1 can only show the empty states: filling Act or See needs a model, and Act's Trace starts closed. This
renders the filled states from recorded demo output instead:
- the run 8 B5.2 Act trace as step cards, with its Answer and a Polished quote card;
- an inline error line and the empty trace;
- the run 3 BX.1 See description, reaction and trace, plus both See empty states.
It uses static/twin.css plus static/tabs/act.css and see.css, and screenshots light and dark with headless Chrome
from a local HTML file.

Two Gradio 6.27 behaviours are reproduced so the harness sees the real specificity:
- Markup, taken from real DOM dumps of other lanes (scripts/dev/shots/lane_ask/states_r1,
  lane_decide/states_r1):
  - a Markdown block: the block div with elem_id and elem_classes > markdown-wrapper div > prose div, which carries
    the same elem_classes again > span holding the rendered siblings;
  - fenced code: div > button[title=copy] + pre > code;
  - the Accordion: a block with a label button (span label, span chevron);
  - a Textbox: a form container div > block div > label > span + div > textarea. The form container's real rules,
    including its !important border, radius and shadow reset on the block, are copied into the reset below.
- The custom-CSS prefixer in Gradio's core JS. It re-emits every rule with
  ".gradio-container.gradio-container-6-27-0 .contain" before each comma-separated piece of the selector, splitting
  on every comma including those inside :is(). The page sits inside matching wrapper divs.
The rest of Gradio's CSS is not loaded. The real-app shots from ui_check.ps1 cover the empty states against it.

Usage (project root): python scripts/dev/finish/lane_act_see_harness.py [out_dir]
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scripts" / "dev" / "shots" / "lane_act_see" / "harness"
DEMO = ROOT / "scripts" / "dev" / "demo"
PREFIX = ".gradio-container.gradio-container-6-27-0 .contain"

RESET = """
body { margin: 0; padding: 24px; background: var(--twin-bg); color: var(--twin-text);
       font-family: var(--twin-font-body); font-size: 15px; line-height: 1.5; }
.page { max-width: 978px; }
h1 { font-size: 13px; font-weight: 600; color: var(--twin-text-muted); margin: 28px 0 8px; }
.column { display: flex; flex-direction: column; gap: 16px; min-width: 0; flex: 1 1 0; }
.column > .column { flex: 0 0 auto; }
.row { display: flex; gap: 16px; align-items: flex-start; }
.block { position: relative; box-sizing: border-box; flex: 1 1 100%; padding: var(--block-padding, 12px);
         border: var(--block-border-width, 1px) solid var(--twin-border); border-radius: var(--block-radius, 10px);
         background: var(--block-background-fill, var(--twin-surface)); }
.form { display: flex; flex-wrap: wrap; gap: 1px; overflow-y: hidden;
        border: var(--block-border-width, 1px) solid var(--twin-border); border-radius: var(--block-radius, 10px);
        background: var(--twin-border); }
.form .block { box-shadow: none !important; border-width: 0 !important; border-radius: 0 !important; }
label.container { display: block; }
label.container > span { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 600; }
textarea { display: block; box-sizing: border-box; width: 100%; padding: 8px 12px; resize: none; font: inherit;
           border: 1px solid var(--twin-border-strong); border-radius: 6px; background: var(--twin-surface);
           color: var(--twin-text); }
.label-wrap { display: flex; justify-content: space-between; width: 100%; padding: 0; border: 0;
              background: none; font: inherit; color: inherit; cursor: pointer; }
.accordion-content { margin-top: 12px; }
.code_wrap { position: relative; }
.copy_code_button { position: absolute; top: 12px; right: 20px; padding: 2px 6px; border: 1px solid; font-size: 11px; }
.drop { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px;
        color: var(--twin-text-muted); }
.floatlabel { position: absolute; top: 0; left: 0; padding: 2px 8px; border: 1px solid; border-radius: 0 0 6px 0; font-size: 13px; }
.see-image { border-style: dashed; }
button.primary { padding: 10px 24px; border: 0; border-radius: 6px; background: var(--twin-accent);
                 color: var(--twin-accent-ink); font: inherit; font-weight: 600; }
"""


def gradio_prefix(css: str) -> str:
    """Emulate Gradio 6.27's custom-CSS prefixer (core JS): for every style rule, drop the first ".dark", split the
    selector on every comma, and prefix each piece (with ".dark" in front when the rule text contains ".dark ")."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    while (j := css.find("{", i)) >= 0:
        depth, k = 1, j + 1
        while k < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        prelude, body = css[i:j].strip(), css[j + 1:k - 1]
        if prelude.startswith(("@media", "@supports")):
            out.append(f"{prelude} {{\n{gradio_prefix(body)}\n}}")
        elif prelude and not prelude.startswith("@"):
            dark = ".dark " in f"{prelude} {{{body}}}"
            selector = " ".join(prelude.split())
            pieces = selector.replace(".dark", "", 1).split(",")
            prefixed = ",".join(f"{'.dark' if dark else ''} {PREFIX} {p.strip()} " for p in pieces)
            out.append(f"{prefixed} {{{body}}}")
        i = k
    return "\n".join(out)


def section(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"=== " + re.escape(name) + r" ===\n(.*?)(?=\n\[\+[\d.]+ s\] ===|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def render(md_text: str) -> str:
    out = MarkdownIt("commonmark").render(md_text)
    out = re.sub(r"<pre><code([^>]*)>",
                 r'<div class="code_wrap"><button title="copy" class="copy_code_button">copy</button><pre><code\1>', out)
    return out.replace("</code></pre>", "</code></pre></div>")


def md_block(elem_id: str, classes: str, md_text: str) -> str:
    return (f'<div id="{elem_id}" class="block {classes}"><div data-testid="markdown-wrapper">'
            f'<div data-testid="markdown" class="prose {classes}"><span class="md prose">{render(md_text)}</span>'
            f'</div></div></div>')


def textbox(card_id: str, card_classes: str, elem_id: str, label: str, value: str, rows: int,
            disabled: bool = True) -> str:
    dis = " disabled" if disabled else ""
    return (f'<div id="{card_id}" class="column {card_classes}"><div class="form"><div id="{elem_id}" class="block">'
            f'<label class="container show_textbox_border"><span data-testid="block-info">{html.escape(label)}</span>'
            f'<div class="input-container"><textarea rows="{rows}"{dis}>{html.escape(value)}</textarea></div></label>'
            f'</div></div></div>')


def accordion(classes: str, inner: str) -> str:
    return (f'<div id="act-trace-accordion" class="block {classes}"><button class="label-wrap"><span>Trace</span>'
            f'<span class="icon">&#9660;</span></button><div class="accordion-content"><div class="column">{inner}'
            f'</div></div></div>')


def page(theme: str) -> str:
    act_trace = section(DEMO / "run8_B5.2.txt", "trace_md")
    act_answer = section(DEMO / "run8_B5.2.txt", "answer")
    polished = section(DEMO / "run9_B5.2.txt", "answer") or act_answer
    see_desc = section(DEMO / "run3_BX.1.txt", "description")
    see_reaction = section(DEMO / "run3_BX.1.txt", "reaction")
    see_trace = section(DEMO / "run3_BX.1.txt", "trace_md")
    err = "**Error:** `ConnectionError: [WinError 10061] No connection could be made because the target machine actively refused it`"
    css = "\n".join((ROOT / p).read_text(encoding="utf-8") for p in ("static/twin.css", "static/tabs/act.css",
                                                                        "static/tabs/see.css"))
    # The same elem_id repeats for each state below; CSS id selectors match every element that carries it.
    act_panel = f"""
<h1>Act: answer, polish, polished (run 8 answer; run 9 answer as the Polished sample)</h1>
<div class="row twin-split" id="act-results">
  <div class="column">{textbox("act-answer-card", "twin-card twin-result act-answer", "act-answer", "Answer", act_answer, 7, disabled=False)}
    <div class="row twin-actions"><button class="secondary">Polish with Stheno</button></div></div>
  <div class="column">{textbox("act-polished-card", "quote-card act-polished", "act-polished", "Polished", polished, 7)}</div>
</div>
<h1>Act: Trace open, run 8 B5.2</h1>
{accordion("act-trace-accordion", md_block("act-trace", "trace act-trace", act_trace))}
<h1>Act: Trace, empty and error states</h1>
{accordion("act-trace-accordion", md_block("act-trace", "trace act-trace", "_(no trace)_"))}
{accordion("act-trace-accordion", md_block("act-trace", "trace act-trace", err))}
"""
    see_panel = f"""
<h1>See: run 3 BX.1</h1>
<div class="row twin-split" id="see-row">
  <div class="column"><div id="see-image" class="block see-image"><label class="floatlabel">Image</label>
      <div class="drop">Drop Image Here<br>- or -<br>Click to Upload</div></div>
    <div class="row twin-actions"><button class="primary">Look</button></div></div>
  <div class="column">{textbox("see-description-card", "twin-card see-description", "see-description", "Description (qwen3.5)", see_desc, 9)}
    {textbox("see-reaction-card", "quote-card see-reaction", "see-reaction", "Reaction (in my voice)", see_reaction, 5)}</div>
</div>
{md_block("see-trace", "trace see-trace", see_trace)}
<h1>See: trace empty, no image, error</h1>
{md_block("see-trace", "trace see-trace", "_(no trace)_")}
{md_block("see-trace", "trace see-trace", "_(upload an image first)_")}
{md_block("see-trace", "trace see-trace", err)}
"""
    body_class = ' class="dark"' if theme == "dark" else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:wght@400;600&display=swap">
<style>{RESET}</style><style>{css}</style><style>{gradio_prefix(css)}</style></head>
<body{body_class}><div class="gradio-container gradio-container-6-27-0"><div class="contain"><div class="page">
<div id="twin-tabs">
<div id="tab-act" role="tabpanel"><div class="column">{act_panel}</div></div>
<div id="tab-see" role="tabpanel"><div class="column">{see_panel}</div></div>
</div></div></div></div></body></html>"""


def find_chrome() -> str:
    for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"):
        if p.exists():
            return str(p)
    raise FileNotFoundError("no chrome.exe or msedge.exe found")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    ok = True
    for theme in ("light", "dark"):
        doc = OUT / f"harness_{theme}.html"
        doc.write_text(page(theme), encoding="utf-8")
        png = OUT / f"harness_{theme}.png"
        if png.exists():
            png.unlink()
        profile = tempfile.mkdtemp(prefix="twin_harness_")
        try:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--no-default-browser-check", f"--user-data-dir={profile}", "--window-size=1026,3400",
                            "--virtual-time-budget=6000", f"--screenshot={png}", doc.as_uri()],
                           timeout=120, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        size = png.stat().st_size if png.exists() else 0
        print(f"{theme}: {png} ({size} bytes)")
        ok = ok and size > 5000
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

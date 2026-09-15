"""Review helper (read-only): condensed print of review_capture.json written by review_evals_status_capture.py."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
for r in data["results"]:
    print("=" * 110)
    print(f"{r['width']} {r['theme']} {r['tab']}: selected={r.get('selectedTab')!r} dark={r.get('dark')} height={r.get('height')} "
          f"scrollWidth={r.get('scrollWidth')}/{r.get('innerWidth')} panelFound={r.get('panelFound')}")
    if not r.get("panelFound"):
        continue
    c = r.get("contrast") or {}
    print(f"  contrast: textElements={c.get('textElements')} unknown={c.get('unknownColour')} min={c.get('minRatio')} "
          f"below={c.get('belowCount')} {c.get('below')}")
    print(f"  islands ({r.get('islandCount')}): {r.get('islands')}")
    print(f"  clipped ({r.get('clippedCount')}): {r.get('clipped')[:8]}")
    past = r.get("pastPanel") or []
    print(f"  pastPanel ({r.get('pastPanelCount')}, panelRight={r.get('panelRight')}): tags={Counter(p['tag'] for p in past)} "
          f"sample={past[:6]}")
    print(f"  inputs: {r.get('inputs')}")
    print("  buttons:")
    for b in r.get("buttons") or []:
        print(f"    {b['text'][:44]!r:48} id={b['id']:<26} rect={b['rect']} bg={b['bg']} color={b['color']} "
              f"border={b['border']} ws={b['whiteSpace']} contrast={b['contrast']} cls={b['cls'][:60]!r}")
    print(f"  rects: {json.dumps(r.get('rects'))}")
    for t in r.get("tables") or []:
        print(f"  table owner={t['owner']} headers={t['headers']} rows={t['rows']} misaligned={t['misalignedCount']} "
              f"{t['misaligned'][:4]} rect={t['rect']} cellMaxLines={t['cellMaxLines']}")
    css = r.get("css") or {}
    print(f"  css: rulesMentioningTab={css.get('rulesMentioningTab')}")
    for s in css.get("sample") or []:
        print(f"     sample: {s[:160]}")
    for s in css.get("prefixedSample") or []:
        print(f"     prefixed: {s[:200]}")
    for s in css.get("twinTableIsRules") or []:
        print(f"     twin-table :is(): {s[:220]}")
    print(f"  markdownDoubleClass={r.get('markdownDoubleClass')} gridCellFont={r.get('gridCellFont')}")

"""P4 evals_status lane scratch check (read-only): every selector in static/tabs/eval.css and static/tabs/status.css
starts with #tab-<id> (optionally after "body.dark "), no Gradio-internal selector appears, and no colour literal or
--twin-* redefinition sits in a declaration. Uses the rule parser of tests/test_theme.py. Run from the project root:
  python scripts/dev/finish/lane_evals_status_scope.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests.test_theme import COLOUR_LITERAL, FORBIDDEN, _rules, _scoped  # noqa: E402

PARTIALS = {"eval": ROOT / "static" / "tabs" / "eval.css", "status": ROOT / "static" / "tabs" / "status.css"}


def main() -> int:
    bad = 0
    for tab, path in PARTIALS.items():
        text = path.read_text(encoding="utf-8")
        rules = _rules(text)
        selectors = [s for sels, _ in rules for s in sels]
        unscoped = [s for s in selectors if not _scoped(s, (f"#tab-{tab}",))]
        forbidden = FORBIDDEN.search(text)
        literals = []
        for sels, body in rules:
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                name, value = (p.strip() for p in decl.split(":", 1))
                if name.startswith("--twin-") or COLOUR_LITERAL.search(value):
                    literals.append(f"{', '.join(sels)} {{ {name}: {value} }}")
        dark = sum(1 for s in selectors if s.startswith("body.dark "))
        print(f"{path.relative_to(ROOT)}: {len(rules)} rules, {len(selectors)} selectors, "
              f"{len(selectors) - len(unscoped)} start with #tab-{tab} ({dark} after body.dark); "
              f"unscoped={unscoped}; forbidden={forbidden.group(0) if forbidden else None}; literals={literals}")
        bad += len(unscoped) + (1 if forbidden else 0) + len(literals)
    print("scope check:", "PASS" if bad == 0 else f"FAIL ({bad})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

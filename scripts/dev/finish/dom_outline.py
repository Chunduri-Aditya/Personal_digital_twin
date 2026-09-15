"""Print a compact outline of chosen subtrees of a saved DOM dump (read-only helper for the P3 frame restyle).

Usage (project root):
  python scripts/dev/finish/dom_outline.py <dump.html> <id> [<id> ...] [--depth N] [--fixed]
Shows tag, id, role, aria-*, data-testid and the non-svelte classes of each element, plus a short text sample.
--fixed also lists elements whose inline style contains position: fixed.
"""
import re
import sys
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr", "path",
        "circle", "rect", "line", "polyline", "polygon"}


class Outline(HTMLParser):
    def __init__(self, ids, depth, fixed):
        super().__init__(convert_charrefs=True)
        self.ids, self.max_depth, self.fixed = set(ids), depth, fixed
        self.stack = []          # [(tag, capture_depth or None)]
        self.capture = None      # depth at which capture started
        self.lines = []
        self.fixed_hits = []

    def _desc(self, tag, attrs):
        a = dict(attrs)
        parts = [tag]
        if a.get("id"):
            parts.append("#" + a["id"])
        cls = [c for c in (a.get("class") or "").split() if not c.startswith("svelte-")]
        if cls:
            parts.append("." + ".".join(cls[:6]))
        for k in ("role", "aria-selected", "aria-label", "aria-expanded", "data-testid", "type"):
            if a.get(k):
                parts.append(f"[{k}={a[k][:40]}]")
        style = a.get("style") or ""
        if style:
            parts.append("{" + style[:90] + "}")
        return " ".join(parts)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        depth = len(self.stack)
        if self.fixed and "fixed" in (a.get("style") or ""):
            self.fixed_hits.append(self._desc(tag, attrs))
        if self.capture is None and a.get("id") in self.ids:
            self.capture = depth
            self.lines.append("")
        if self.capture is not None and depth - self.capture <= self.max_depth:
            self.lines.append("  " * (depth - self.capture) + self._desc(tag, attrs))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t = self.stack.pop()
            if self.capture is not None and len(self.stack) == self.capture:
                self.capture = None
            if t == tag:
                break

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if text and self.capture is not None:
            depth = len(self.stack)
            if depth - self.capture <= self.max_depth + 1:
                self.lines.append("  " * (depth - self.capture) + '"' + text[:70] + '"')


def main():
    args = sys.argv[1:]
    depth = 12
    fixed = "--fixed" in args
    if "--depth" in args:
        i = args.index("--depth")
        depth = int(args[i + 1])
        del args[i:i + 2]
    args = [a for a in args if a != "--fixed"]
    if len(args) < 2:
        print(__doc__)
        return 2
    path, ids = args[0], args[1:]
    p = Outline(ids, depth, fixed)
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    print("\n".join(p.lines))
    if fixed:
        print("\n-- inline position: fixed --")
        print("\n".join(p.fixed_hits) or "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

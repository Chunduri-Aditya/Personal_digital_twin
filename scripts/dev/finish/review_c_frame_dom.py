"""Review helper (P3 frame, round 1): read a saved DOM dump (default: scripts/dev/shots/before_c/measure_ask_400_light.html)
and print the structure frame.css and the frame contract rely on. Reads files only."""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.text = tag, dict(attrs), parent, [], ""

    def label(self):
        a = self.attrs
        bits = [self.tag]
        if a.get("id"):
            bits.append("#" + a["id"])
        cls = [c for c in (a.get("class") or "").split() if not c.startswith("svelte-")]
        if cls:
            bits.append("." + ".".join(cls[:4]))
        for k in ("role", "aria-label", "aria-selected"):
            if k in a:
                bits.append(f"[{k}={a[k]!r}]")
        return "".join(bits)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root
        self.all: list[Node] = []

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        self.all.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        self.all.append(n)

    def handle_endtag(self, tag):
        c = self.cur
        while c is not None and c.tag != tag:
            c = c.parent
        if c is not None and c.parent is not None:
            self.cur = c.parent

    def handle_data(self, data):
        if data.strip():
            self.cur.text += data.strip() + " "


def chain(n: Node, depth=5):
    out = []
    while n is not None and depth:
        out.append(n.label())
        n, depth = n.parent, depth - 1
    return " < ".join(out)


def outline(n: Node, depth: int, indent=0, max_children=12):
    print("  " * indent + n.label() + (f"  '{n.text[:40]}'" if n.text else ""))
    if depth:
        for c in n.children[:max_children]:
            outline(c, depth - 1, indent + 1, max_children)
        if len(n.children) > max_children:
            print("  " * (indent + 1) + f"... {len(n.children) - max_children} more")


def all_text(n: Node) -> str:
    return (n.text + " ".join(all_text(c) for c in n.children)).strip()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scripts/dev/shots/before_c/measure_ask_400_light.html"
    t = Tree()
    t.feed(path.read_text(encoding="utf-8"))
    by_id = {n.attrs.get("id"): n for n in t.all if n.attrs.get("id")}
    print("dump:", path)
    tabs = by_id.get("twin-tabs")
    print("\n==== #twin-tabs outline (depth 3) ====")
    if tabs:
        outline(tabs, 3)
        print("\ndirect children of #twin-tabs:", [c.label() for c in tabs.children])
    print("\n==== [role=tab] chains ====")
    for n in [n for n in t.all if n.attrs.get("role") == "tab"][:3]:
        print("  ", chain(n, 4))
    print("\n==== More tabs ====")
    for n in [n for n in t.all if n.attrs.get("aria-label") == "More tabs"]:
        print("  ", chain(n, 4))
        sib = n.parent.children
        i = sib.index(n)
        print("   next sibling:", sib[i + 1].label() if i + 1 < len(sib) else None)
    print("\n==== tabpanels ====")
    for n in [n for n in t.all if n.attrs.get("role") == "tabpanel"]:
        print("  ", n.label(), "parent:", n.parent.label())
    print("\n==== buttons with text Send / Clear and their parents ====")
    for n in t.all:
        if n.tag == "button" and all_text(n) in ("Send", "Clear"):
            print("  ", repr(all_text(n)), chain(n, 5))
            print("     class attr:", n.attrs.get("class"))
    print("\n==== #status-strip children ====")
    ss = by_id.get("status-strip")
    if ss:
        outline(ss, 3, max_children=6)
    print("\n==== <html>/<body> attrs ====")
    for n in t.all:
        if n.tag in ("html", "body"):
            print("  ", n.tag, {k: v for k, v in n.attrs.items() if k in ("class", "style", "lang")})
    print("\n==== meta theme-color ====", [n.attrs for n in t.all if n.tag == "meta" and n.attrs.get("name") == "theme-color"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

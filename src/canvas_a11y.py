"""Check canvas-paste.html against the Canvas Rich Content Editor accessibility checker's rules.

Rules (Canvas RCE a11y checker): headings start at h2 and never skip a level; headings <= 120 chars;
tables have a caption, a header row, and scope on every <th>; images have alt text that is not a
file name and is <= 120 chars; adjacent links don't share a URL; text that looks like a list is a
real list; inline text colours meet 4.5:1 contrast (3:1 for large text).
Run: python src/canvas_a11y.py [file]   (exit 1 if anything fails)
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lum(hex_):
    hex_ = hex_.lstrip("#")
    if len(hex_) == 3:
        hex_ = "".join(c * 2 for c in hex_)
    rgb = [int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def style_val(style, prop):
    m = re.search(r"(?:^|;)\s*" + prop + r"\s*:\s*(#[0-9a-fA-F]{3,6})", style or "")
    return m.group(1) if m else None


class Checker(HTMLParser):
    VOID = {"img", "br", "hr", "meta", "link", "input"}

    def __init__(self):
        super().__init__()
        self.problems = []
        self.last_heading = 1  # Canvas supplies the page's h1
        self.stack = []        # (tag, attrs, colour, background)
        self.heading = None
        self.tables = []       # per open table: {caption, header_row, rows}
        self.links = []        # (href, text, start_pos)
        self.cur_link = None
        self.text_since_link = ""
        self.para = None

    def where(self):
        return f"line {self.getpos()[0]}"

    def colours(self):
        fg, bg = "#2d3b45", "#ffffff"  # Canvas body text and page background
        for _, _, c, b in self.stack:
            fg, bg = c or fg, b or bg
        return fg, bg

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        st = a.get("style", "")
        if tag not in self.VOID:
            self.stack.append((tag, a, style_val(st, "color"), style_val(st, "background(?:-color)?")))
        if re.fullmatch(r"h[1-6]", tag):
            level = int(tag[1])
            if level == 1:
                self.problems.append(f"{self.where()}: h1 in content (Canvas page title is the h1)")
            elif level > self.last_heading + 1:
                self.problems.append(f"{self.where()}: heading skips from h{self.last_heading} to h{level}")
            self.last_heading = level
            self.heading = ""
        if tag == "table":
            self.tables.append({"caption": False, "header": False, "line": self.where()})
        if tag == "caption" and self.tables:
            self.tables[-1]["caption"] = True
        if tag == "th":
            if self.tables:
                self.tables[-1]["header"] = True
            if a.get("scope") not in ("col", "row", "colgroup", "rowgroup"):
                self.problems.append(f"{self.where()}: <th> without scope")
        if tag == "img":
            alt = a.get("alt")
            if alt is None or (not alt.strip() and a.get("role") != "presentation"):
                self.problems.append(f"{self.where()}: image without alt text")
            elif re.search(r"\.(png|jpe?g|gif|svg|webp)$", alt.strip(), re.I):
                self.problems.append(f"{self.where()}: alt text is a file name")
            elif len(alt) > 120:
                self.problems.append(f"{self.where()}: alt text over 120 chars ({len(alt)})")
        if tag == "a":
            self.cur_link = [a.get("href", ""), ""]
        if tag == "p":
            self.para = ""

    def handle_endtag(self, tag):
        if self.heading is not None and re.fullmatch(r"h[1-6]", tag):
            if len(self.heading.strip()) > 120:
                self.problems.append(f"{self.where()}: heading over 120 chars")
            self.heading = None
        if tag == "table" and self.tables:
            t = self.tables.pop()
            if not t["caption"]:
                self.problems.append(f"{t['line']}: table without caption")
            if not t["header"]:
                self.problems.append(f"{t['line']}: table without header cells")
        if tag == "a" and self.cur_link:
            href, text = self.cur_link
            if self.links and self.links[-1][0] == href and not self.text_since_link.strip():
                self.problems.append(f"{self.where()}: adjacent links to the same URL ({href})")
            if text.strip().lower() in {"here", "click here", "link", "more", "read more"} or text.strip() == href:
                self.problems.append(f"{self.where()}: link text not descriptive: {text.strip()!r}")
            self.links.append((href, text))
            self.text_since_link = ""
            self.cur_link = None
        if tag == "p" and self.para is not None:
            if re.match(r"\s*(\d+[.)]|[-*•])\s", self.para):
                self.problems.append(f"{self.where()}: paragraph looks like a list item: {self.para.strip()[:50]!r}")
            self.para = None
        if tag not in self.VOID:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        if self.heading is not None:
            self.heading += data
        if self.cur_link is not None:
            self.cur_link[1] += data
        else:
            self.text_since_link += data
        if self.para is not None:
            self.para += data
        if data.strip():
            fg, bg = self.colours()
            large = any(t in ("h1", "h2", "h3") for t, *_ in self.stack)
            need = 3.0 if large else 4.5
            ratio = contrast(fg, bg)
            if ratio < need:
                self.problems.append(f"{self.where()}: contrast {ratio:.2f}:1 ({fg} on {bg}) below {need}:1")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "canvas-paste.html"
    c = Checker()
    c.feed(path.read_text(encoding="utf-8"))
    problems = list(dict.fromkeys(c.problems))
    for p in problems:
        print("FAIL", p)
    print(f"{len(problems)} problem(s) in {path.name}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

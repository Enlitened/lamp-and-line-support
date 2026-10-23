#!/usr/bin/env python3
"""Write a static page for every chapter of the Berean Standard Bible.

    python3 tools/build_bible.py PATH/TO/scripture.sqlite

The database is the app's own, built by the importer in the app repository
(`Resources/Generated/scripture.sqlite`, made by `make` there), so the site and
the app set the same text the same way: poetry keeps its lines, prose flows as
paragraphs, headings stand as headings and footnotes are lettered through each
chapter and set apart below the text, where they cannot be read as Scripture.

It writes, and owns:

- `bible/index.html`, every book, Old and New Testament;
- `bible/<book>/index.html`, a grid of the book's chapters;
- `bible/<book>/<n>.html`, one page per chapter, 1,189 of them;
- `sitemap-bible.xml`, the chapter pages (robots.txt names it);
- the block of `sitemap.xml` between the `bible` comments: the index and the
  66 book pages.

Anything else under `bible/` is deleted, so a renamed slug leaves nothing behind.
Output is deterministic: the same database gives byte-identical files. That is
why the sitemap date is a constant here rather than today — bump `SITE_DATE`
when the pages change.

Stdlib only and Python 3.9, like the app repository's tooling.
"""

import html
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bible"
SITE = "https://lampandline.app/"
SITE_DATE = "2026-10-23"
APP_ID = "6808235223"
# One campaign token per kind of page, so App Analytics can tell a download that
# began on a chapter from one that began on the book list. No script, no SDK.
STORE_CHAPTER = ("https://apps.apple.com/app/apple-store/id6808235223"
                 "?pt=129383521&ct=web-chapter&mt=8")
STORE_BIBLE = ("https://apps.apple.com/app/apple-store/id6808235223"
               "?pt=129383521&ct=web-bible&mt=8")
LICENCE = "https://berean.bible/licensing.htm"

# Block styles that end a line: poetry, lists and the centred line. Prose
# (`m`, `pmo`) flows. Mirrors `BlockStyle.breaksAtEndOfLine` in ScriptureKit.
LINE_STYLES = {"q1", "q2", "qr", "li1", "li2", "pc"}

# The divine name, set as capital and small capitals the way a printed Bible
# sets it. Mirrors `SmallCapitals` in LampAndLineCore: only the letters after
# the first are marked, the text itself is untouched, and an inscription (the
# name beside another all-capital word, "KING OF KINGS AND LORD OF LORDS") is
# left in full capitals.
NAMES = {"LORD", "GOD"}
WORD = re.compile(r"[^\W\d_]+")


def esc(text):
    return html.escape(text, quote=False)


def attr(text):
    return html.escape(text, quote=True)


def small_caps_ranges(text):
    if "LORD" not in text and "GOD" not in text:
        return []
    words = [(m.group(), m.start()) for m in WORD.finditer(text)]

    def inscribed(word):
        return len(word) >= 2 and word not in NAMES and word.isupper()

    ranges = []
    for i, (word, start) in enumerate(words):
        if word not in NAMES:
            continue
        if i > 0 and inscribed(words[i - 1][0]):
            continue
        if i + 1 < len(words) and inscribed(words[i + 1][0]):
            continue
        ranges.append((start + 1, start + len(word)))
    return ranges


def letter(index):
    """a, b, … z, aa, ab, … — `ScriptureTypesetter.letter(at:)`."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    if index < 26:
        return letters[index]
    return letters[(index // 26 - 1) % 26] + letters[index % 26]


def styled_text(text, notes, small_caps=True):
    """`text` as HTML, with each note's marker at its offset.

    `notes` is a list of (offset, letter). Offsets count characters, as Swift's
    String does; the BSB has no combining marks, so a Python index is the same
    count (the build checks).
    """
    caps = small_caps_ranges(text) if small_caps else []

    def piece(start, end):
        out = []
        cursor = start
        for lo, hi in caps:
            lo, hi = max(lo, start), min(hi, end)
            if lo >= hi:
                continue
            out.append(esc(text[cursor:lo]))
            out.append('<span class="sc">%s</span>' % esc(text[lo:hi]))
            cursor = hi
        out.append(esc(text[cursor:end]))
        return "".join(out)

    out = []
    cursor = 0
    for offset, mark in sorted(notes):
        anchor = min(max(offset, 0), len(text))
        out.append(piece(cursor, anchor))
        out.append('<sup class="fn"><a href="#fn-%s" id="fr-%s">%s</a></sup>' % (mark, mark, mark))
        cursor = anchor
    out.append(piece(cursor, len(text)))
    return "".join(out)


# --- data -------------------------------------------------------------------

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def chapter_label(book, number):
    """"Psalm 23", not "Psalms 23": the book is plural, one of it is not."""
    name = "Psalm" if book["usfm"] == "PSA" else book["name"]
    return "%s %d" % (name, number)


def load(db):
    books = []
    for row in db.execute(
        "SELECT id, usfm_code, name, testament, chapter_count FROM books ORDER BY canonical_order"
    ):
        books.append({
            "id": row[0], "usfm": row[1], "name": row[2], "testament": row[3],
            "chapters": row[4], "slug": slug(row[2]),
        })
    assert len({b["slug"] for b in books}) == len(books), "two books share a slug"
    return books


def chapter_elements(db, chapter_id):
    """Headings and verse segments in reading order, with their notes."""
    verse_notes, section_notes = {}, {}
    for verse_id, section_id, origin, text, offset, note_id in db.execute(
        "SELECT f.verse_id, f.section_id, f.origin, f.text, f.offset, f.id FROM footnotes f "
        "LEFT JOIN verses v ON v.id = f.verse_id LEFT JOIN sections s ON s.id = f.section_id "
        "WHERE v.chapter_id = ? OR s.chapter_id = ? ORDER BY f.offset, f.id",
        (chapter_id, chapter_id),
    ):
        note = {"origin": origin, "text": text, "offset": offset, "id": note_id}
        if verse_id is not None:
            verse_notes.setdefault(verse_id, []).append(note)
        else:
            section_notes.setdefault(section_id, []).append(note)

    elements = []
    for row in db.execute(
        "SELECT id, position, number, segment, text, block_style, paragraph_start, blank_before "
        "FROM verses WHERE chapter_id = ?", (chapter_id,)
    ):
        elements.append((row[1], {
            "kind": "verse", "verse": row[2], "segment": row[3], "text": row[4],
            "style": row[5], "starts": bool(row[6]), "blank": bool(row[7]),
            "notes": verse_notes.get(row[0], []),
        }))
    for row in db.execute(
        "SELECT id, position, style, title FROM sections WHERE chapter_id = ?", (chapter_id,)
    ):
        elements.append((row[1], {
            "kind": "heading", "style": row[2], "title": row[3],
            "notes": section_notes.get(row[0], []),
        }))
    elements.sort(key=lambda pair: pair[0])
    return [element for _, element in elements]


# --- rendering ----------------------------------------------------------------

def head(title, description, path, depth, og_title, crumbs):
    """The <head>, matching the hand-written pages'. `path` is the canonical
    path under the site root; `depth` how many directories down the page is."""
    up = "../" * depth
    url = SITE + path
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="apple-itunes-app" content="app-id=%s">' % APP_ID,
        "<title>%s</title>" % esc(title),
        '<meta name="description" content="%s">' % attr(description),
        '<meta property="og:title" content="%s">' % attr(og_title),
        '<meta property="og:description" content="%s">' % attr(description),
        '<meta property="og:image" content="%sassets/og-card.png">' % SITE,
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Lamp &amp; Line">',
        '<meta property="og:url" content="%s">' % attr(url),
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:image" content="%sassets/og-card.png">' % SITE,
        '<link rel="icon" href="%sassets/icon-512.png">' % up,
        '<link rel="apple-touch-icon" href="%sassets/icon-512.png">' % up,
        '<link rel="canonical" href="%s">' % attr(url),
        '<link rel="stylesheet" href="%sstyle.css">' % up,
    ]
    if crumbs:
        data = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE + crumb_path}
                for i, (name, crumb_path) in enumerate(crumbs)
            ],
        }
        lines.append('<script type="application/ld+json">')
        lines.append(json.dumps(data, indent=2, ensure_ascii=False).replace("</", "<\\/"))
        lines.append("</script>")
    lines += ["</head>", "<body>"]
    return "\n".join(lines) + "\n"


def footer(depth, here):
    up = "../" * depth
    links = [
        ('<a href="%s">Lamp &amp; Line</a>' % (up or "./")),
        ('<a href="%sbible/">The Bible</a>' % up) if here != "index" else None,
        '<a href="%sberean-standard-bible-app.html">The BSB app</a>' % up,
        '<a href="%ssupport.html">Support</a>' % up,
        '<a href="%sprivacy.html">Privacy policy</a>' % up,
    ]
    return (
        "  <footer>\n"
        '    <p class="rights">Scripture: the <a href="%s">Berean Standard Bible (BSB), public domain</a>.</p>\n'
        "    %s\n"
        "  </footer>\n"
        "</main>\n</body>\n</html>\n"
    ) % (LICENCE, "\n    ".join(link for link in links if link))


def offline_card(heading, body, store):
    return (
        '  <aside class="card offline">\n'
        "    <h2>%s</h2>\n"
        "    <p>%s</p>\n"
        '    <p class="cta"><a class="store" href="%s">Download on the App&nbsp;Store</a></p>\n'
        "  </aside>\n"
    ) % (heading, body, attr(store))


HEADING_TAGS = {
    # style: (tag, class). Section headings are editorial; the superscription
    # (`d`) and the acrostic letters (`qa`) are the translation's own text.
    "ms1": ("h2", "ms"),
    "mr": ("p", "mr"),
    "s1": ("h2", None),
    "s2": ("h3", None),
    "r": ("p", "r"),
    "d": ("p", "d"),
    "qa": ("h3", "qa"),
}


def render_scripture(elements, letters):
    """The chapter's text. Every segment that opens a block opens a paragraph
    of its style; one that does not continues the open paragraph after a space
    — prose flowing, or a verse that starts mid-line (Exodus 20:4–6, Psalm
    55:2–3). So a poetry line is a paragraph, which is what lets CSS hang its
    continuation, and a prose paragraph holds as many verses as the BSB gives it.
    """
    out = []
    para = None  # [style, blank, parts]
    seen = set()

    def close():
        nonlocal para
        if para is None:
            return
        style, blank, parts = para
        cls = style + (" b" if blank else "")
        out.append('<p class="%s">%s</p>' % (cls, " ".join(parts)))
        para = None

    for element in elements:
        notes = [(n["offset"], letters[n["id"]]) for n in element["notes"]]
        if element["kind"] == "heading":
            close()
            tag, cls = HEADING_TAGS[element["style"]]
            body = styled_text(element["title"], notes)
            out.append("<%s%s>%s</%s>" % (tag, ' class="%s"' % cls if cls else "", body, tag))
            continue
        if para is None or element["starts"]:
            close()
            para = [element["style"], element["blank"], []]
        text = styled_text(element["text"], notes)
        if element["verse"] not in seen:
            seen.add(element["verse"])
            v = element["verse"]
            # A no-break space, so a number never ends a line apart from its verse.
            text = '<sup class="v" id="v%d">%d</sup>&nbsp;%s' % (v, v, text)
        para[2].append(text)
    close()
    return "\n".join(out)


def omitted_note(number, notes, letters):
    """The line for a verse the BSB does not print, and the note that gives it,
    if one does ("BYZ and TR include 21 …")."""
    pattern = re.compile(r"\binclude[sd]?\b.*?\b%d\b" % number)
    found = next((n for n in notes if pattern.search(n["text"])), None)
    line = "The BSB does not print verse %d: it follows the critical Greek text, which does not have it." % number
    if found:
        mark = letters[found["id"]]
        line += ' Note <a href="#fn-%s">%s</a> gives the words other manuscripts have.' % (mark, mark)
    return line, found is not None


def describe(elements, limit=150):
    text = " ".join(e["text"] for e in elements if e["kind"] == "verse")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(" ", 1)[0].rstrip(",;:—–-“‘ ")
    return cut + "…"


def chapter_page(book, number, elements, prev_link, next_link, omitted_report):
    label = chapter_label(book, number)
    all_notes = [n for e in elements for n in e["notes"]]
    # Lettered in reading order across headings and verses alike.
    letters = {n["id"]: letter(i) for i, n in enumerate(all_notes)}

    verses = sorted({e["verse"] for e in elements if e["kind"] == "verse"})
    missing = [n for n in range(1, verses[-1] + 1) if n not in set(verses)]

    path = "bible/%s/%d.html" % (book["slug"], number)
    title = "%s — Berean Standard Bible (BSB) | Lamp & Line" % label
    parts = [head(
        title, describe(elements), path, 2, "%s — Berean Standard Bible (BSB)" % label,
        [("Bible", "bible/"), (book["name"], "bible/%s/" % book["slug"]), (label, path)],
    )]
    parts.append('<main class="bible">\n')
    parts.append('  <nav class="crumbs" aria-label="Breadcrumb"><a href="../">Bible</a> › '
                 '<a href="./">%s</a></nav>\n' % esc(book["name"]))
    parts.append("  <h1>%s</h1>\n" % esc(label))
    parts.append('  <p class="stamp">Berean Standard Bible</p>\n')
    parts.append('  <article class="scripture">\n%s\n  </article>\n' % render_scripture(elements, letters))

    if all_notes or missing:
        parts.append('  <section class="notes" aria-label="Notes">\n    <h2>Notes</h2>\n')
        for n in missing:
            line, found = omitted_note(n, all_notes, letters)
            omitted_report.append((label, n, found))
            parts.append('    <p class="omitted" id="v%d">%s</p>\n' % (n, line))
        if all_notes:
            parts.append("    <ol>\n")
            for n in all_notes:
                mark = letters[n["id"]]
                origin = n["origin"]
                where = "Title" if origin.endswith(":0") else origin
                parts.append(
                    '      <li id="fn-%s"><a class="back" href="#fr-%s">%s</a> '
                    '<span class="at">%s</span> %s</li>\n'
                    % (mark, mark, mark, esc(where), esc(n["text"]))
                )
            parts.append("    </ol>\n")
        parts.append("  </section>\n")

    parts.append('  <nav class="pager" aria-label="Chapters">\n')
    parts.append("    %s\n" % (
        '<a rel="prev" href="%s">‹ %s</a>' % prev_link if prev_link else "<span></span>"))
    parts.append("    %s\n" % (
        '<a rel="next" href="%s">%s ›</a>' % next_link if next_link else "<span></span>"))
    parts.append("  </nav>\n")
    parts.append(offline_card(
        "Read %s offline" % esc(label),
        "Lamp &amp; Line keeps the whole Berean Standard Bible on your iPhone, iPad and Apple Watch: "
        "poetry set as poetry, notes a tap away, and nothing to sign in to. Free, no ads, nothing collected.",
        STORE_CHAPTER,
    ))
    parts.append(footer(2, "chapter"))
    return "".join(parts)


def book_page(book, prev_book, next_book):
    n = book["chapters"]
    path = "bible/%s/" % book["slug"]
    title = "%s — Berean Standard Bible (BSB) | Lamp & Line" % book["name"]
    testament = "Old Testament" if book["testament"] == "old" else "New Testament"
    count = "1 chapter" if n == 1 else "%d chapters" % n
    description = ("Read %s in the Berean Standard Bible (BSB): %s, with the translators’ "
                   "headings and footnotes. Public domain, free to read.") % (book["name"], count)
    parts = [head(title, description, path, 2, "%s — Berean Standard Bible (BSB)" % book["name"],
                  [("Bible", "bible/"), (book["name"], path)])]
    parts.append('<main class="bible">\n')
    parts.append('  <nav class="crumbs" aria-label="Breadcrumb"><a href="../">Bible</a></nav>\n')
    parts.append("  <h1>%s</h1>\n" % esc(book["name"]))
    parts.append('  <p class="stamp">%s · %s · Berean Standard Bible</p>\n' % (testament, count))
    parts.append('  <ol class="chapters">\n')
    for c in range(1, n + 1):
        parts.append('    <li><a href="%d.html" aria-label="%s">%d</a></li>\n'
                     % (c, attr(chapter_label(book, c)), c))
    parts.append("  </ol>\n")
    parts.append('  <nav class="pager" aria-label="Books">\n')
    parts.append("    %s\n" % ('<a rel="prev" href="../%s/">‹ %s</a>' % (prev_book["slug"], esc(prev_book["name"]))
                                if prev_book else "<span></span>"))
    parts.append("    %s\n" % ('<a rel="next" href="../%s/">%s ›</a>' % (next_book["slug"], esc(next_book["name"]))
                                if next_book else "<span></span>"))
    parts.append("  </nav>\n")
    parts.append(offline_card(
        "Read %s offline" % esc(book["name"]),
        "Lamp &amp; Line keeps the whole Berean Standard Bible on your iPhone, iPad and Apple Watch, "
        "with nothing to sign in to. Free, no ads, nothing collected.",
        STORE_BIBLE,
    ))
    parts.append(footer(2, "book"))
    return "".join(parts)


def index_page(books, chapters, verses):
    title = "Read the Berean Standard Bible (BSB), every book and chapter | Lamp & Line"
    description = ("The complete Berean Standard Bible (BSB) to read online: all 66 books and "
                   "1,189 chapters, with the translators’ headings and footnotes. Public domain.")
    parts = [head(title, description, "bible/", 1, "The Berean Standard Bible (BSB)", None)]
    parts.append('<main class="bible">\n')
    parts.append("  <h1>The Berean Standard Bible</h1>\n")
    parts.append(
        '  <p class="lede">The whole Berean Standard Bible (BSB), one page to a chapter: '
        "%d books, %s chapters and %s verses, with the translators’ section headings and footnotes. "
        "(%s rather than the traditional 31,102, because the BSB, following the critical Greek "
        "text, does not print sixteen verses in its running text; each chapter’s notes say where.)</p>\n"
        % (len(books), format(chapters, ","), format(verses, ","), format(verses, ","))
    )
    for key, heading in (("old", "Old Testament"), ("new", "New Testament")):
        group = [b for b in books if b["testament"] == key]
        parts.append("  <h2>%s</h2>\n" % heading)
        parts.append('  <ul class="books">\n')
        for b in group:
            parts.append('    <li><a href="%s/">%s</a></li>\n' % (b["slug"], esc(b["name"])))
        parts.append("  </ul>\n")
    parts.append(offline_card(
        "Read it offline",
        "Lamp &amp; Line keeps the whole Berean Standard Bible on your iPhone, iPad and Apple Watch: "
        "poetry set as poetry, search across every verse, and nothing to sign in to. "
        "Free, no ads, nothing collected.",
        STORE_BIBLE,
    ))
    parts.append(footer(1, "index"))
    return "".join(parts)


# --- sitemaps -------------------------------------------------------------------

def url_entry(loc, priority=None):
    lines = ["  <url>", "    <loc>%s</loc>" % esc(loc), "    <lastmod>%s</lastmod>" % SITE_DATE]
    if priority:
        lines.append("    <priority>%s</priority>" % priority)
    lines.append("  </url>")
    return "\n".join(lines)


def write_sitemaps(books, chapter_paths):
    entries = [url_entry(SITE + p) for p in chapter_paths]
    (ROOT / "sitemap-bible.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Every chapter page. Written by tools/build_bible.py; robots.txt names it. -->\n"
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries) + "\n</urlset>\n",
        encoding="utf-8",
    )

    start, end = "  <!-- bible: written by tools/build_bible.py -->", "  <!-- /bible -->"
    block = [start, url_entry(SITE + "bible/", "0.6")]
    block += [url_entry(SITE + "bible/%s/" % b["slug"], "0.5") for b in books]
    block.append(end)
    sitemap = ROOT / "sitemap.xml"
    text = sitemap.read_text(encoding="utf-8")
    if start in text:
        before = text[:text.index(start)]
        after = text[text.index(end) + len(end):]
        text = before + "\n".join(block) + after
    else:
        text = text.replace("</urlset>", "\n".join(block) + "\n</urlset>")
    sitemap.write_text(text, encoding="utf-8")


# --- main ---------------------------------------------------------------------

def main(argv):
    if len(argv) != 2:
        sys.exit("usage: build_bible.py PATH/TO/scripture.sqlite")
    db = sqlite3.connect("file:%s?mode=ro" % Path(argv[1]).resolve(), uri=True)

    import unicodedata
    for (text,) in db.execute("SELECT text FROM verses UNION ALL SELECT title FROM sections"):
        if any(unicodedata.combining(ch) or ord(ch) > 0xFFFF for ch in text):
            sys.exit("the text has a combining mark or astral character; footnote offsets "
                     "count Swift Characters and would need grapheme counting here")

    books = load(db)
    sequence = []  # (book, number, chapter_id) in canonical order
    for b in books:
        for chapter_id, number in db.execute(
            "SELECT id, number FROM chapters WHERE book_id = ? ORDER BY number", (b["id"],)
        ):
            sequence.append((b, number, chapter_id))

    written = set()

    def write(rel, content):
        target = OUT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.add(target)

    omitted = []
    verse_total = 0
    chapter_paths = []
    for i, (b, number, chapter_id) in enumerate(sequence):
        def link(j):
            if not 0 <= j < len(sequence):
                return None
            ob, on, _ = sequence[j]
            href = "%d.html" % on if ob is b else "../%s/%d.html" % (ob["slug"], on)
            return (href, esc(chapter_label(ob, on)))

        elements = chapter_elements(db, chapter_id)
        verse_total += len({e["verse"] for e in elements if e["kind"] == "verse"})
        write("%s/%d.html" % (b["slug"], number),
              chapter_page(b, number, elements, link(i - 1), link(i + 1), omitted))
        chapter_paths.append("bible/%s/%d.html" % (b["slug"], number))

    for i, b in enumerate(books):
        write("%s/index.html" % b["slug"],
              book_page(b, books[i - 1] if i else None, books[i + 1] if i + 1 < len(books) else None))
    write("index.html", index_page(books, len(sequence), verse_total))

    for path in sorted(OUT.rglob("*"), reverse=True):
        if path.is_file() and path not in written:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()

    write_sitemaps(books, chapter_paths)

    print("%d books, %d chapters, %d verses, %d pages" % (len(books), len(sequence), verse_total, len(written)))
    for label, n, found in omitted:
        print("  omitted %s:%d%s" % (label, n, "" if found else " (no note found)"))


if __name__ == "__main__":
    main(sys.argv)

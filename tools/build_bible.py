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
import math
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
# Both CC BY 4.0, so every page that shows them names them.
CROSS_REFERENCE_SOURCE = "https://www.openbible.info/labs/cross-references/"
LEXICON_SOURCE = "https://github.com/STEPBible/STEPBible-Data"

# The app's pitch, said once so the three kinds of page cannot drift apart. The
# whole Bible on Apple Watch is Full (decision 0009), so the free claim names
# iPhone and iPad only.
APP_PITCH = ("Lamp &amp; Line keeps the whole Berean Standard Bible on your iPhone and iPad, "
             "free: %s, and nothing to sign in to. No ads, nothing collected. Lamp &amp; Line Full "
             "adds the Hebrew and Greek behind every word, and the whole Bible on Apple Watch.")

# What the reader sees beside each chapter: a few cross references a verse and
# a few of the chapter's words in the original. Enough to be worth reading on
# the page, and to link the chapters to one another; the rest is in the app.
CROSS_REFERENCES_PER_VERSE = 3
WORDS_PER_CHAPTER = 8
# A word used this often is grammar more than vocabulary ("to say", "LORD",
# "and", "the"), and would head every chapter's list.
COMMON_WORD = 1000
# The verbs a sentence leans on rather than speaks of: to be, to come, to go, to
# say, to see, to have, to do, to give, to take, can, to know, to answer. Rarer
# than COMMON_WORD, but a long chapter uses them so often they would crowd out
# the word it is about ("Word" in John 1).
LIGHT_WORDS = {
    "G0565", "G0611", "G1096", "G1325", "G1410", "G1492", "G1510", "G2036", "G2046",
    "G2064", "G2192", "G2983", "G3004", "G3708", "G4160", "G4198",
    "H0559", "H0560", "H0935", "H1934", "H1961", "H1980", "H3318", "H3947", "H5414",
    "H6213", "H7200",
}

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
        "SELECT id, usfm_code, name, testament, chapter_count, canonical_order FROM books "
        "ORDER BY canonical_order"
    ):
        books.append({
            "id": row[0], "usfm": row[1], "name": row[2], "testament": row[3],
            "chapters": row[4], "order": row[5], "slug": slug(row[2]),
        })
    assert len({b["slug"] for b in books}) == len(books), "two books share a slug"
    return books


def verse_key(book, chapter, verse):
    """`VerseKey` in ScriptureKit: BBCCCVVV, the book by canonical order."""
    return book["order"] * 1_000_000 + chapter * 1_000 + verse


def split_key(key):
    return key // 1_000_000, key // 1_000 % 1_000, key % 1_000


def varints(data):
    """`WordStudyPacking`'s unsigned LEB128 integers and length-prefixed UTF-8
    strings, read as one flat stream: callers know the shape."""
    i = 0

    def number():
        nonlocal i
        value, shift = 0, 0
        while True:
            byte = data[i]
            i += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7

    def string():
        nonlocal i
        length = number()
        text = data[i:i + length].decode("utf-8")
        i += length
        return text

    return number, string, lambda: i >= len(data)


def unpack_words(data):
    """`WordStudyPacking.unpackWords`: (lexeme, parsing, form, rendering) each."""
    number, string, done = varints(data)
    words = []
    while not done():
        words.append((number(), number(), number(), string()))
    return words


def load_word_study(db):
    """The lexicon, and which parsings mark a word worth showing: a verb, a
    common noun or an adjective. Hebrew codes join prefixes to the word
    ("Conj-w | V-Qal-ConsecImperf-3ms"), so every part is looked at."""
    lexemes = {}
    for row in db.execute(
        "SELECT id, strongs, language, lemma, transliteration, gloss, occurrence_count FROM lexemes"
    ):
        lexemes[row[0]] = {
            "strongs": row[1], "language": row[2], "lemma": row[3],
            "transliteration": row[4], "gloss": row[5], "count": row[6],
        }
    content = set()
    for parsing_id, code in db.execute("SELECT id, code FROM parsings"):
        parts = [p.strip() for p in re.split(r"[|,]", code)]
        if any(p.startswith(("V-", "Adj")) or (p.startswith("N-") and not p.startswith("N-proper"))
               for p in parts):
            content.add(parsing_id)
    return lexemes, content


def aramaic(book, chapter, verse):
    """`OldTestamentLanguage` in ScriptureKit, for one verse."""
    place = (chapter, verse)
    usfm = book["usfm"]
    return ((usfm == "DAN" and (2, 5) <= place <= (7, 28))
            or (usfm == "EZR" and ((4, 8) <= place <= (6, 18) or (7, 12) <= place <= (7, 26)))
            or (usfm == "JER" and place == (10, 11)))


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
    lines += [
        "</head>",
        "<body>",
        # The bar the hand-written pages open with.
        '<header class="bar"><div>',
        '  <a class="mark" href="%s"><img src="%sassets/icon-512.png" width="28" height="28" alt=""> Lamp &amp; Line</a>'
        % (up or "./", up),
        '  <a href="%sbible/">Read the Bible</a>' % up,
        "</div></header>",
    ]
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


def reference_label(by_order, start, end):
    """"Romans 5:8", "Romans 5:6–8", "Genesis 1:1–2:3", as the app sets them."""
    b, c, v = split_key(start)
    label = "%s:%d" % (chapter_label(by_order[b], c), v)
    if end is None:
        return label
    eb, ec, ev = split_key(end)
    if eb != b:
        return "%s–%s:%d" % (label, chapter_label(by_order[eb], ec), ev)
    if ec != c:
        return "%s–%d:%d" % (label, ec, ev)
    return "%s–%d" % (label, ev)


def reference_href(by_order, book, number, key):
    """A link from chapter `number` of `book` to the verse `key` names."""
    b, c, v = split_key(key)
    target = by_order[b]
    if target is book and c == number:
        return "#v%d" % v
    if target is book:
        return "%d.html#v%d" % (c, v)
    return "../%s/%d.html#v%d" % (target["slug"], c, v)


def cross_references_section(context, book, number, verses):
    db, by_order = context["db"], context["by_order"]
    first, last = verse_key(book, number, 1), verse_key(book, number, 999)
    by_verse = {}
    for from_key, to_start, to_end in db.execute(
        "SELECT from_key, to_start, to_end FROM cross_references "
        "WHERE from_key BETWEEN ? AND ? AND rank <= ? ORDER BY from_key, rank",
        (first, last, CROSS_REFERENCES_PER_VERSE),
    ):
        by_verse.setdefault(from_key % 1000, []).append((to_start, to_end))
    if not by_verse:
        return ""
    lines = []
    for v in sorted(by_verse):
        if v not in verses:
            continue
        links = "; ".join(
            '<a href="%s">%s</a>' % (reference_href(by_order, book, number, start),
                                     esc(reference_label(by_order, start, end)))
            for start, end in by_verse[v]
        )
        lines.append('      <li><a class="at" href="#v%d">%d:%d</a> %s</li>\n' % (v, number, v, links))
    return (
        '  <section class="notes xrefs" aria-label="Cross references">\n'
        "    <h2>Cross references</h2>\n"
        "    <ol>\n%s    </ol>\n"
        '    <p class="credit">Cross references: <a href="%s">openbible.info</a>, CC BY 4.0. '
        "Lamp &amp; Line shows every one, with its words beside the verse.</p>\n"
        "  </section>\n"
    ) % ("".join(lines), CROSS_REFERENCE_SOURCE)


def words_section(context, book, number, verses):
    """The chapter's words in the original that say the most about it, in the
    order they first appear: verbs, nouns and adjectives, not names."""
    db, lexemes, content = context["db"], context["lexemes"], context["content"]
    first, last = verse_key(book, number, 1), verse_key(book, number, 999)
    found = {}  # lexeme id → {"verses": [...], "renderings": {text: count}, "order": n}
    languages = set()
    order = 0
    for key, data in db.execute(
        "SELECT verse_key, data FROM verse_words WHERE verse_key BETWEEN ? AND ? ORDER BY verse_key",
        (first, last),
    ):
        v = key % 1000
        if book["testament"] != "new":
            languages.add("Aramaic" if aramaic(book, number, v) else "Hebrew")
        for lexeme, parsing, _, rendering in unpack_words(data):
            entry = lexemes.get(lexeme)
            if (not entry or parsing not in content or entry["count"] > COMMON_WORD
                    or entry["strongs"] in LIGHT_WORDS):
                continue
            # Greek parsings do not mark a name as Hebrew's do; its capital does.
            if entry["language"] == "G" and entry["lemma"][:1].isupper():
                continue
            word = found.setdefault(lexeme, {"verses": [], "renderings": {}, "order": order, "hits": 0})
            order += 1
            word["hits"] += 1
            if v not in word["verses"]:
                word["verses"].append(v)
            rendering = rendering.strip()
            if rendering:
                word["renderings"][rendering] = word["renderings"].get(rendering, 0) + 1
    if not found:
        return ""

    # How often the chapter uses a word, weighed (heavily) against how common it
    # is in the whole Bible: "born" in John 3 outranks "to come", which is in
    # nearly every chapter.
    def weight(item):
        lexeme, word = item
        rarity = math.log(context["totals"][lexemes[lexeme]["language"]] / lexemes[lexeme]["count"])
        return (-word["hits"] * rarity * rarity, lexeme)

    chosen = sorted(found.items(), key=weight)
    chosen = sorted(chosen[:WORDS_PER_CHAPTER], key=lambda item: item[1]["order"])

    if book["testament"] == "new":
        language, lang = "Greek", "grc"
    else:
        language = " and ".join(sorted(languages, key=lambda name: name != "Hebrew"))
        lang = "arc" if languages == {"Aramaic"} else "he"
    items = []
    for lexeme, word in chosen:
        entry = lexemes[lexeme]
        # A bracketed word is one the translators supplied ("[John’s disciples]
        # came"), not the original's. "Everyone" opening a sentence is folded
        # into "everyone" when that is there too; "God" and "Son" are kept.
        plain = {t: c for t, c in word["renderings"].items() if "[" not in t}
        folded = {}
        for text, count in plain.items():
            lower = text[:1].lower() + text[1:]
            key = lower if lower != text and lower in plain else text
            folded[key] = folded.get(key, 0) + count
        renderings = sorted(folded.items(), key=lambda item: (-item[1], item[0]))[:3]
        rendered = ", ".join("“%s”" % esc(text) for text, _ in renderings)
        places = ", ".join('<a href="#v%d">%d</a>' % (v, v) for v in word["verses"])
        items.append(
            '      <li><span class="lemma" lang="%s">%s</span> <i>%s</i> <span class="sn">%s</span> '
            "%s.%s <span class=\"in\">%s %s</span></li>\n"
            % (lang, esc(entry["lemma"]), esc(entry["transliteration"]), esc(entry["strongs"]),
               esc(entry["gloss"]),
               " Rendered %s." % rendered if rendered else "",
               "Verse" if len(word["verses"]) == 1 else "Verses", places)
        )
    label = chapter_label(book, number)
    return (
        '  <section class="notes words" aria-label="%s words">\n'
        "    <h2>%s words in %s</h2>\n"
        "    <ul>\n%s    </ul>\n"
        '    <p class="credit">Every word of every verse, with its grammar and every place it occurs, '
        "is in Lamp &amp; Line Full’s word study. Lexicon: <a href=\"%s\">STEP Bible</a>, CC BY 4.0.</p>\n"
        "  </section>\n"
    ) % (language, language, esc(label), "".join(items), LEXICON_SOURCE)


def first_heading(elements):
    """The chapter's first section heading, for its title: what someone who
    remembers the story rather than the number searches for."""
    for e in elements:
        if e["kind"] == "heading" and e["style"] == "s1":
            return e["title"].strip().rstrip(".:;,")
    return None


def describe(elements, lead="", limit=160):
    """`lead`, then the chapter's opening words, cut at a word to fit."""
    text = lead + " ".join(e["text"] for e in elements if e["kind"] == "verse")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit + 1].rsplit(" ", 1)[0].rstrip(",;:—–-“‘ ")
    return cut + "…"


def chapter_page(context, book, number, elements, prev_link, next_link, omitted_report):
    label = chapter_label(book, number)
    all_notes = [n for e in elements for n in e["notes"]]
    # Lettered in reading order across headings and verses alike.
    letters = {n["id"]: letter(i) for i, n in enumerate(all_notes)}

    verses = sorted({e["verse"] for e in elements if e["kind"] == "verse"})
    missing = [n for n in range(1, verses[-1] + 1) if n not in set(verses)]

    path = "bible/%s/%d.html" % (book["slug"], number)
    heading = first_heading(elements)
    if heading:
        og_title = "%s: %s (BSB)" % (label, heading)
        lead = "%s, Berean Standard Bible: %s. " % (label, heading)
    else:
        og_title = "%s — Berean Standard Bible (BSB)" % label
        lead = "%s, Berean Standard Bible. " % label
    parts = [head(
        og_title + " | Lamp & Line", describe(elements, lead), path, 2, og_title,
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

    present = set(verses)
    parts.append(words_section(context, book, number, present))
    parts.append(cross_references_section(context, book, number, present))

    parts.append('  <nav class="pager" aria-label="Chapters">\n')
    parts.append("    %s\n" % (
        '<a rel="prev" href="%s">‹ %s</a>' % prev_link if prev_link else "<span></span>"))
    parts.append("    %s\n" % (
        '<a rel="next" href="%s">%s ›</a>' % next_link if next_link else "<span></span>"))
    parts.append("  </nav>\n")
    parts.append(offline_card(
        "Read %s offline" % esc(label),
        APP_PITCH % "poetry set as poetry, notes a tap away",
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
        APP_PITCH % "poetry set as poetry, search across every verse",
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
        APP_PITCH % "poetry set as poetry, search across every verse",
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
    lexemes, content = load_word_study(db)
    context = {"db": db, "by_order": {b["order"]: b for b in books},
               "lexemes": lexemes, "content": content,
               "totals": {lang: sum(e["count"] for e in lexemes.values() if e["language"] == lang)
                          for lang in ("H", "G")}}
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
              chapter_page(context, b, number, elements, link(i - 1), link(i + 1), omitted))
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

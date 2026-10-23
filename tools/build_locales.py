#!/usr/bin/env python3
"""Write a landing page in each language the App Store listing is translated into.

    python3 tools/build_locales.py PATH/TO/lamp-and-line/AppStore/metadata

The words are the listing's own, read from the app repository's
`AppStore/metadata/<locale>/` (name, subtitle, promotional text, description and
the Scripture-language notice), so a page never says what the listing does not,
and both change together: edit the listing there, then run this again.

These are for the stores where the app ranks in the local language and the
reader is looking for the Bible in English ("Bibel auf Englisch", "英語の聖書").
Each page says the Bible text is English before anything else can suggest
otherwise. Simplified Chinese is left out: the app is not on sale in China
mainland (MARKETING.md, 16 Oct).

It writes, and owns:

- `<dir>/index.html` for each locale below;
- the block of `index.html` between the `locales` comments in its <head>: the
  hreflang alternates, which every page in the set must carry alike;
- the block of `index.html` between the `languages` comments: the links to them;
- the block of `sitemap.xml` between the `locales` comments.

Output is deterministic, like `build_bible.py`; bump `SITE_DATE` when the pages
change. Stdlib only and Python 3.9.
"""

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://lampandline.app/"
SITE_DATE = "2026-10-23"
APP_ID = "6808235223"

# metadata folder, site folder, hreflang, og:locale, the App Store badge's own
# words in that language, and the page's few strings of its own.
LOCALES = [
    ("de-DE", "de", "de", "de_DE", "Laden im App Store", "Deutsch", {
        "read": "Die Bibel online lesen (Englisch)", "support": "Support",
        "privacy": "Datenschutzerklärung", "languages": "Sprachen"}),
    ("es-ES", "es", "es", "es_ES", "Descargar en el App Store", "Español", {
        "read": "Leer la Biblia en línea (en inglés)", "support": "Soporte",
        "privacy": "Política de privacidad", "languages": "Idiomas"}),
    ("es-MX", "es-mx", "es-MX", "es_MX", "Descargar en el App Store", "Español (México)", {
        "read": "Leer la Biblia en línea (en inglés)", "support": "Soporte",
        "privacy": "Política de privacidad", "languages": "Idiomas"}),
    ("fr-FR", "fr", "fr", "fr_FR", "Télécharger dans l’App Store", "Français", {
        "read": "Lire la Bible en ligne (en anglais)", "support": "Assistance",
        "privacy": "Politique de confidentialité", "languages": "Langues"}),
    ("it", "it", "it", "it_IT", "Scarica su App Store", "Italiano", {
        "read": "Leggi la Bibbia online (in inglese)", "support": "Supporto",
        "privacy": "Informativa sulla privacy", "languages": "Lingue"}),
    ("nl-NL", "nl", "nl", "nl_NL", "Download in de App Store", "Nederlands", {
        "read": "Lees de Bijbel online (Engels)", "support": "Ondersteuning",
        "privacy": "Privacybeleid", "languages": "Talen"}),
    ("pt-BR", "pt-br", "pt-BR", "pt_BR", "Baixar na App Store", "Português (Brasil)", {
        "read": "Ler a Bíblia online (em inglês)", "support": "Suporte",
        "privacy": "Política de privacidade", "languages": "Idiomas"}),
    ("ja", "ja", "ja", "ja_JP", "App Storeからダウンロード", "日本語", {
        "read": "聖書をオンラインで読む（英語）", "support": "サポート",
        "privacy": "プライバシーポリシー", "languages": "言語"}),
    ("ko", "ko", "ko", "ko_KR", "App Store에서 다운로드", "한국어", {
        "read": "온라인으로 성경 읽기 (영어)", "support": "지원",
        "privacy": "개인정보 처리방침", "languages": "언어"}),
]


def esc(text):
    return html.escape(text, quote=False)


def attr(text):
    return html.escape(text, quote=True)


def store_link(folder):
    # A campaign token per language (`web-de`, …), so App Analytics can say
    # which of these pages brings downloads. Apple sends the visitor to their
    # own storefront.
    return ("https://apps.apple.com/app/apple-store/id%s?pt=129383521&ct=web-%s&mt=8"
            % (APP_ID, folder))


def read(metadata, locale, name):
    return (metadata / locale / name).read_text(encoding="utf-8").strip()


def alternates(indent=""):
    """Every page in the set names every other, and itself; English is the
    home page and the default for any other language."""
    lines = ['<link rel="alternate" hreflang="en" href="%s">' % SITE]
    lines += ['<link rel="alternate" hreflang="%s" href="%s%s/">' % (hreflang, SITE, folder)
              for _, folder, hreflang, _, _, _, _ in LOCALES]
    lines.append('<link rel="alternate" hreflang="x-default" href="%s">' % SITE)
    return "\n".join(indent + line for line in lines)


def language_links(up, current):
    if current is None:
        links = ['<span aria-current="page">English</span>']
    else:
        links = ['<a href="%s" hreflang="en" lang="en">English</a>' % (up or "./")]
    for _, folder, hreflang, _, _, label, _ in LOCALES:
        if folder == current:
            links.append('<span aria-current="page">%s</span>' % esc(label))
        else:
            links.append('<a href="%s%s/" hreflang="%s" lang="%s">%s</a>'
                         % (up, folder, hreflang, hreflang, esc(label)))
    return " · ".join(links)


def page(metadata, entry):
    locale, folder, hreflang, og_locale, badge, _, words = entry
    name = read(metadata, locale, "name.txt")
    subtitle = read(metadata, locale, "subtitle.txt")
    promo = read(metadata, locale, "promotional_text.txt")
    notice = read(metadata, locale, "scripture_language_notice.txt")
    paragraphs = [p.strip() for p in read(metadata, locale, "description.txt").split("\n\n") if p.strip()]
    url = "%s%s/" % (SITE, folder)
    title = "%s — %s" % (name, subtitle)
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": name,
        "alternateName": "Lamp & Line",
        "applicationCategory": "ReferenceApplication",
        "operatingSystem": "iOS, iPadOS, watchOS",
        "url": url,
        "sameAs": ["https://apps.apple.com/app/id%s" % APP_ID],
        "downloadUrl": "https://apps.apple.com/app/id%s" % APP_ID,
        "image": SITE + "assets/og-card.png",
        "description": promo,
        "inLanguage": hreflang,
        "author": {"@type": "Person", "name": "Colin Sergay"},
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD",
                   "availability": "https://schema.org/InStock"},
    }
    out = [
        "<!doctype html>",
        '<html lang="%s">' % hreflang,
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="apple-itunes-app" content="app-id=%s">' % APP_ID,
        "<title>%s</title>" % esc(title),
        '<meta name="description" content="%s">' % attr(promo),
        '<meta property="og:title" content="%s">' % attr(title),
        '<meta property="og:description" content="%s">' % attr(promo),
        '<meta property="og:image" content="%sassets/og-card.png">' % SITE,
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:type" content="website">',
        '<meta property="og:locale" content="%s">' % og_locale,
        '<meta property="og:site_name" content="Lamp &amp; Line">',
        '<meta property="og:url" content="%s">' % url,
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:image" content="%sassets/og-card.png">' % SITE,
        '<link rel="icon" href="../assets/icon-512.png">',
        '<link rel="apple-touch-icon" href="../assets/icon-512.png">',
        '<link rel="canonical" href="%s">' % url,
        alternates(),
        '<link rel="stylesheet" href="../style.css">',
        '<script type="application/ld+json">',
        json.dumps(data, indent=2, ensure_ascii=False).replace("</", "<\\/"),
        "</script>",
        "</head>",
        "<body>",
        '<header class="bar"><div>',
        '  <a class="mark" href="../"><img src="../assets/icon-512.png" width="28" height="28" alt=""> Lamp &amp; Line</a>',
        '  <a href="../bible/" hreflang="en">%s</a>' % esc(words["read"]),
        "</div></header>",
        '<main class="bible locale">',
        "  <h1>%s</h1>" % esc(name),
        '  <p class="stamp">%s</p>' % esc(subtitle),
        '  <p class="notice">%s</p>' % esc(notice),
        '  <p class="lede">%s</p>' % esc(promo),
        '  <p class="cta"><a class="store" href="%s">%s</a></p>' % (attr(store_link(folder)), esc(badge)),
        '  <div class="description">',
    ]
    out += ["    <p>%s</p>" % esc(p) for p in paragraphs]
    out += [
        "  </div>",
        '  <p class="cta"><a class="store" href="%s">%s</a></p>' % (attr(store_link(folder)), esc(badge)),
        "  <footer>",
        '    <p class="languages"><span>%s:</span> %s</p>' % (esc(words["languages"]), language_links("../", folder)),
        '    <a href="../bible/" hreflang="en">%s</a>' % esc(words["read"]),
        '    <a href="../support.html" hreflang="en">%s</a>' % esc(words["support"]),
        '    <a href="../privacy.html" hreflang="en">%s</a>' % esc(words["privacy"]),
        "  </footer>",
        "</main>",
        "</body>",
        "</html>",
    ]
    return "\n".join(out) + "\n"


def replace_block(path, start, end, body, anchor):
    """Put `body` between the `start` and `end` lines of `path`, or before
    `anchor` the first time."""
    text = path.read_text(encoding="utf-8")
    block = "%s\n%s\n%s" % (start, body, end)
    if start in text:
        text = text[:text.index(start)] + block + text[text.index(end) + len(end):]
    else:
        assert anchor in text, "%s: no %r to put the block before" % (path.name, anchor)
        text = text.replace(anchor, block + "\n" + anchor, 1)
    path.write_text(text, encoding="utf-8")


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: build_locales.py PATH/TO/lamp-and-line/AppStore/metadata")
    metadata = Path(argv[1]).resolve()

    for entry in LOCALES:
        target = ROOT / entry[1] / "index.html"
        target.parent.mkdir(exist_ok=True)
        target.write_text(page(metadata, entry), encoding="utf-8")

    home = ROOT / "index.html"
    replace_block(home, "<!-- locales: written by tools/build_locales.py -->", "<!-- /locales -->",
                  alternates(), '<link rel="stylesheet" href="style.css">')
    replace_block(home, "  <!-- languages: written by tools/build_locales.py -->", "  <!-- /languages -->",
                  '  <p class="languages">%s</p>' % language_links("", None), "</footer>\n</body>")

    entries = "\n".join(
        "  <url>\n    <loc>%s%s/</loc>\n    <lastmod>%s</lastmod>\n    <priority>0.7</priority>\n  </url>"
        % (SITE, folder, SITE_DATE)
        for _, folder, _, _, _, _, _ in LOCALES
    )
    replace_block(ROOT / "sitemap.xml", "  <!-- locales: written by tools/build_locales.py -->",
                  "  <!-- /locales -->", entries, "  <!-- bible: written by tools/build_bible.py -->")

    print("%d language pages" % len(LOCALES))


if __name__ == "__main__":
    main(sys.argv)

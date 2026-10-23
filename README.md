# Lamp & Line — site, support and privacy

The public pages for [Lamp & Line](https://apps.apple.com/app/id6808235223), a
quiet Bible for iPhone, iPad and Apple Watch. Published with GitHub Pages from
`main`.

- Landing page — <https://lampandline.app/>
  (the App Store listing's Marketing URL)
- Support — <https://lampandline.app/support.html>
- Privacy policy — <https://lampandline.app/privacy.html>

All three URLs are the ones filed in App Store Connect. The source of truth for
the support and privacy text is `AppStore/SUPPORT.md` and `AppStore/PRIVACY.md`
in the app repository; edit there first, then bring the change across. The
landing page's copy is the listing's description, likewise brought across from
`AppStore/metadata/en-US/`.

`assets/` holds the icon and two framed screenshots, resized from the app
repository's `AppStore/assets/`.

`bible/` is the whole Berean Standard Bible, a page per chapter, written by
`tools/build_bible.py` from the app's Scripture database (stdlib Python 3.9):

    python3 tools/build_bible.py ~/dev/lamp-and-line/Resources/Generated/scripture.sqlite

It also writes `sitemap-bible.xml` (the chapters, named in robots.txt) and the
marked `bible` block of `sitemap.xml`. Do not edit its output by hand; change
the script and run it again. The same database gives byte-identical files.
Under each chapter it sets a few of the chapter's Hebrew, Aramaic or Greek
words (STEP Bible's lexicon) and three cross references a verse (openbible.info);
both are CC BY 4.0, and each section names its source.

`de/`, `es/`, `es-mx/`, `fr/`, `it/`, `nl/`, `pt-br/`, `ja/` and `ko/` are the
landing page in the listing's other languages, written by
`tools/build_locales.py` from the app repository's store copy:

    python3 tools/build_locales.py ~/dev/lamp-and-line/AppStore/metadata

It also owns the marked `locales` (hreflang) and `languages` blocks of
`index.html` and the `locales` block of `sitemap.xml`. Run it again whenever the
listing's text changes.

`.well-known/apple-app-site-association.json` lets the app open a chapter page
(`/bible/*/*.html`) as a universal link, at the verse its `#v` anchor names
(decision 0034 in the app repository). Apple fetches it at
`/.well-known/apple-app-site-association`, with no extension and no redirect;
`vercel.json` rewrites that path to the `.json` file, because Vercel serves an
extensionless file as `application/octet-stream` and a header rule in
`vercel.json` did not override that. `/.well-known/` is exempt from the
trailing-slash redirect. Apple's CDN caches
it, so check a change at
<https://app-site-association.cdn-apple.com/a/v1/lampandline.app> a day later.
The chapter pages' addresses must not change: shared verses link them for
years, and the app's `WebLinkTests` pin the 66 book slugs.

Contact: csergay@gmail.com

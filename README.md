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

Contact: csergay@gmail.com

"""MASTER BRAIN public UI smoke tests; no network and no betting changes."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = {"radar", "futuros", "padroes", "validacao", "dados"}


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.nav = set()
        self.go = set()
        self.links = []
        self.script_srcs = []
        self.css = []
        self.titles = []
        self._title = False

    def handle_starttag(self, tag, attrs):
        p = dict(attrs)
        if p.get("id"):
            self.ids.add(p["id"])
        if p.get("data-page"):
            self.nav.add(p["data-page"])
        if p.get("data-go"):
            self.go.add(p["data-go"])
        if tag == "a":
            self.links.append(p.get("href", ""))
        if tag == "script" and "src" in p:
            self.script_srcs.append(p["src"])
        if tag == "link" and p.get("rel") == "stylesheet":
            self.css.append(p.get("href"))
        if tag == "title":
            self._title = True

    def handle_data(self, data):
        if self._title:
            self.titles.append(data)

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False


def parse(path):
    doc = Elements()
    doc.feed((DOCS / path).read_text(encoding="utf-8"))
    return doc


class MasterBrainSiteTests(unittest.TestCase):
    def test_primary_dashboard_is_brain_first_with_five_working_tabs(self):
        doc = parse("index.html")
        self.assertEqual(doc.nav, PAGES)
        self.assertEqual(doc.go, {"futuros", "padroes", "validacao", "dados"})
        self.assertTrue(all("page-" + p in doc.ids for p in PAGES))
        self.assertIn("MASTER BRAIN", "".join(doc.titles))
        self.assertIn("./master-brain.js", doc.script_srcs)
        self.assertIn("./master-brain.css", doc.css)
        self.assertIn("./h1.html#h1", doc.links)
        self.assertIn("./h1.html#triples", doc.links)

    def test_all_relative_files_linked_from_main_pages_exist(self):
        for path in ("index.html", "h1.html", "lab-research.html", "lab-pattern-watch.html"):
            html = parse(path)
            for href in html.links + html.css + html.script_srcs:
                if not href or href.startswith(("http:", "https:", "#", "mailto:")):
                    continue
                file_path = href.split("#", 1)[0].split("?", 1)[0]
                if not file_path:
                    continue
                self.assertTrue((DOCS / file_path).is_file(), (path, href))

    def test_h1_old_dashboard_is_preserved_and_separate(self):
        doc = parse("h1.html")
        original_ids = {"view-overview", "view-h1", "view-triples", "view-market",
                        "view-quality", "h1-list", "triple-list", "nav-h1"}
        self.assertTrue(original_ids <= doc.ids)
        self.assertIn("./dashboard.js", doc.script_srcs)
        self.assertIn("./dashboard.css", doc.css)
        new = parse("index.html")
        self.assertFalse(original_ids & new.ids)
        self.assertNotIn("./dashboard.js", new.script_srcs)

    def test_live_datasets_and_legacy_bookmark_migration(self):
        js = (DOCS / "master-brain.js").read_text(encoding="utf-8")
        for name in ("pattern-research.json", "pattern-watch.json", "ft-results.json",
                     "v4-audit.json", "data.json"):
            self.assertIn(name, js)
        for old in ("h1", "triples", "market", "quality", "overview"):
            self.assertIn('"' + old + '"', js)
        self.assertIn("h1.html#", js)
        self.assertIn("Date.now()", js)
        self.assertIn("EXPLORATORIO", (DOCS / "index.html").read_text(encoding="utf-8") +
                      js.replace("EXPLORATÓRIO", "EXPLORATORIO"))

    def test_discovery_radar_has_real_data_source_and_no_betting_actions(self):
        doc = parse("index.html")
        self.assertTrue({"r-discovery", "discovery-filter", "r-detail", "r-prospective"} <= doc.ids)
        self.assertTrue((DOCS / "lab" / "discoveries.json").is_file())
        js = (DOCS / "master-brain.js").read_text(encoding="utf-8")
        for item in ("discoveries.json", "renderChronology()", "renderProspective()",
                     "showEvidence(", "first_detected_at", "out_of_sample"):
            self.assertIn(item, js)
        self.assertIn("SIGN_REVERSAL", js)
        # A function existing in the script does not prove that the UI ever renders it.
        self.assertRegex(js, r"function render\(\)\{[^}]*renderChronology\(\);renderProspective\(\);")
        self.assertIn('$("discovery-filter").addEventListener("change",renderChronology)', js)
        self.assertIn("Cronologia indisponível", js)
        self.assertIn("Histórico prospetivo indisponível", js)

    @unittest.skipUnless(shutil.which("node"), "node unavailable")
    def test_javascript_syntax(self):
        for path in ("master-brain.js", "dashboard.js"):
            proc = subprocess.run(
                ["node", "--check", str(DOCS / path)],
                capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, (path, proc.stderr))


if __name__ == "__main__":
    unittest.main()

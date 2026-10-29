"""Checks for the additive MASTER BRAIN preview; no production modification or network."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        if tag == "link" and a.get("rel") == "stylesheet":
            self.styles.append(a.get("href"))


class PreviewTests(unittest.TestCase):
    def test_six_areas_and_links(self):
        page = Page()
        page.feed((DOCS / "brain-preview.html").read_text(encoding="utf-8"))
        self.assertTrue({"hoje", "passado", "sinais", "teste", "comprovadas", "historico"} <= page.ids)
        self.assertEqual(len([x for x in page.links if x.startswith("#")]), 7)  # six tabs + skip link
        self.assertIn("./brain-preview.js", page.scripts)
        self.assertIn("./brain-pattern-link.js", page.scripts)
        self.assertTrue({"operation-metrics", "operation-warnings"} <= page.ids)
        self.assertIn("./brain-preview.css", page.styles)
        for path in page.scripts + page.styles:
            self.assertTrue((DOCS / path).is_file(), path)

    def test_failure_states_and_statistical_disclaimers(self):
        js = (DOCS / "brain-preview.js").read_text(encoding="utf-8")
        for phrase in ("Promise.allSettled", "Não foi possível apresentar este painel",
                       "MBPatternMatcher.linked", "renderOperations",
                       "Cronologia indisponível", "Histórico prospetivo indisponível",
                       "valor-q", "não ROI", "known>=12", "reference_known>=12",
                       "cache:\"no-store\"", "VALIDADO"):
            self.assertIn(phrase, js)
        self.assertNotIn("placeBet(", js)
        self.assertNotIn("POST", js)
        self.assertNotIn("localStorage", js)

    @unittest.skipUnless(shutil.which("node"), "node unavailable")
    def test_syntax(self):
        for file_name in ("brain-preview.js", "brain-pattern-link.js"):
            proc = subprocess.run(
                ["node", "--check", str(DOCS / file_name)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, (file_name, proc.stderr))

    @unittest.skipUnless(shutil.which("node"), "node unavailable")
    def test_matcher_regressions(self):
        proc = subprocess.run(
            ["node", "--test", str(ROOT / "tests" / "brain-pattern-link.test.cjs")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()

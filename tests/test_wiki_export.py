"""Exercise the Wiki publication command on the repository's actual documentation."""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.export_wiki import export

ROOT = Path(__file__).resolve().parents[1]
COMMAND = [sys.executable, str(ROOT / "scripts/export_wiki.py")]
WIKI = "https://github.com/booarkz-cpu/shop-by-boo/wiki/"
BLOB = "https://github.com/booarkz-cpu/shop-by-boo/blob/main/"
LANGUAGES = ("ru", "en", "uk")


class WikiExportTests(unittest.TestCase):
    def test_each_translation_keeps_its_identity_and_navigation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "pages"
            subprocess.run([*COMMAND, output], check=True, capture_output=True)
            expected = {"Home.md", "_Sidebar.md"}
            home = (output / "Home.md").read_text()
            sidebar = (output / "_Sidebar.md").read_text()
            for lang in LANGUAGES:
                self.assertIn(WIKI + lang + "-Home)", home)
                for source in (ROOT / "docs/wiki" / lang).glob("*.md"):
                    if source.name == "_Sidebar.md":
                        continue
                    name = lang + "-" + source.name
                    expected.add(name)
                    translated = (output / name).read_text()
                    self.assertEqual(translated.splitlines()[0], source.read_text().splitlines()[0])
                    self.assertIn(WIKI + lang + "-" + source.stem + ")", sidebar)
                start = (output / f"{lang}-Home.md").read_text()
                self.assertIn(WIKI + lang + "-Installation)", start)
                for other in set(LANGUAGES) - {lang}:
                    self.assertIn(WIKI + other + "-Home)", start)
            self.assertEqual(expected, {page.name for page in output.iterdir()})
            for lang in ("en", "uk"):
                self.assertIn(BLOB + f"docs/{lang}/guides/README.md", (output / f"{lang}-Home.md").read_text())
            for page in output.iterdir():
                for target in re.findall(r"\]\(([^)\s]+)\)", page.read_text()):
                    if target.startswith(WIKI):
                        slug = unquote(urlsplit(target).path.rsplit("/", 1)[1])
                        self.assertTrue((output / (slug + ".md")).is_file(), (page.name, target))
                    elif target.startswith(BLOB):
                        relative = unquote(urlsplit(target[len(BLOB):]).path)
                        self.assertTrue((ROOT / relative).is_file(), (page.name, target))
                    else:
                        self.assertTrue(target.startswith(("https://", "http://", "mailto:", "#")), (page.name, target))

    def test_existing_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            home = output / "Home.md"
            home.write_text("Existing wiki home\n")
            attempt = subprocess.run([*COMMAND, output], capture_output=True, text=True)
            self.assertNotEqual(attempt.returncode, 0)
            self.assertIn("File exists", attempt.stderr)
            self.assertEqual(list(output.iterdir()), [home])
            self.assertEqual(home.read_text(), "Existing wiki home\n")

    def test_anchors_and_code_examples_survive_and_missing_pages_stop_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "docs/wiki", root / "docs/wiki")
            for lang in ("en", "uk"):
                guide = Path("docs") / lang / "guides/README.md"
                (root / guide).parent.mkdir(parents=True)
                shutil.copyfile(ROOT / guide, root / guide)
            page = root / "docs/wiki/en/Backup.md"
            example = "`[sample](not-a-page.md)`\n\n```md\n[sample](not-a-page.md)\n```\n"
            page.write_text(page.read_text() + "\n[Start](Home.md#start)\n" + example)
            export(root / "pages", root)
            result = (root / "pages/en-Backup.md").read_text()
            self.assertIn(WIKI + "en-Home#start)", result)
            self.assertIn(example, result)
            page.write_text(page.read_text() + "\n[Gone](no-such-guide.md)\n")
            with self.assertRaisesRegex(ValueError, "no-such-guide"):
                export(root / "incomplete", root)
            self.assertFalse((root / "incomplete").exists())

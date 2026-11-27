"""Export the project's three Markdown guides as uniquely named GitHub Wiki pages."""

import argparse
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/booarkz-cpu/shop-by-boo"
LANGUAGES = {"ru": "Русский", "en": "English", "uk": "Українська"}
LINK_OR_CODE = re.compile(
    r"(?P<ticks>`+).*?(?P=ticks)|"
    r"(?P<label>!?\[[^\]\n]*\]\(\s*)(?P<target>[^()\s<>]+)(?=\s*(?:\"[^\"\n]*\"\s*)?\))"
)
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")


def render(source: Path, root: Path, pages: dict[Path, str]) -> str:
    def replace(match: re.Match) -> str:
        link = match["target"]
        if link is None:
            return match[0]
        target = urlsplit(link)
        if target.scheme or target.netloc or not target.path:
            return match[0]
        path = (source.parent / unquote(target.path)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"{source.relative_to(root)}: missing repository target {link}")
        if path in pages:
            url = f"{REPOSITORY}/wiki/{quote(pages[path])}"
        else:
            url = f"{REPOSITORY}/blob/main/{quote(path.relative_to(root).as_posix())}"
        return match["label"] + url + link[len(target.path):]

    output = []
    fence = ""
    for line in source.read_text(encoding="utf-8").splitlines(keepends=True):
        marker = FENCE.fullmatch(line.rstrip("\r\n"))
        if marker and not fence:
            fence = marker[1]
        elif marker and fence and marker[1].startswith(fence) and not marker[2].strip():
            fence = ""
        elif not fence:
            line = LINK_OR_CODE.sub(replace, line)
        output.append(line)
    return "".join(output)


def export(destination: Path, root: Path = ROOT) -> int:
    root = root.resolve()
    wiki = root / "docs/wiki"
    pages = {}
    homes = []
    sidebars = []
    for code, language in LANGUAGES.items():
        folder = wiki / code
        if not (folder / "Home.md").is_file():
            raise ValueError(f"Missing {code}/Home.md")
        for source in sorted(folder.glob("*.md")):
            if source.name != "_Sidebar.md":
                pages[source] = f"{code}-{source.stem.replace(' ', '-')}"
        homes.append(f"- [{language}]({REPOSITORY}/wiki/{code}-Home)")
        sidebars.append(folder / "_Sidebar.md")
    if len({slug.casefold() for slug in pages.values()}) != len(pages):
        raise ValueError("Two source pages would share a GitHub Wiki URL")

    files = {slug + ".md": render(source, root, pages) for source, slug in pages.items()}
    files["Home.md"] = "# VPN Shop by Corgi Lucy\n\n" + "\n".join(homes) + "\n"
    files["_Sidebar.md"] = "\n\n---\n\n".join(render(path, root, pages).strip() for path in sidebars) + "\n"
    destination.mkdir()
    for name, content in files.items():
        (destination / name).write_text(content, encoding="utf-8")
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new directory for the exported Markdown files")
    args = parser.parse_args()
    try:
        count = export(args.destination)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Wiki export failed: {error}\n")
    print(f"Exported {count} Markdown files to {args.destination}")

#!/usr/bin/env python3
"""Generate docs/blog/index.md by listing posts from docs/blog/posts/.

Scans Markdown files (and extension-less files) in docs/blog/posts/, reads
their YAML front matter (title, date, author, category) and produces an index
sorted by descending date. Any hand-authored content located above the sentinel
<!-- blog-index:generated:start --> is preserved across regenerations.

The Zensical blog plugin is not yet supported (Tier 2, Backlog #30), so this
script is a lightweight, dependency-free replacement that runs in CI before
`zensical build`.

No external dependency: the front matter is parsed by hand since the fields
used here are simple scalar strings (title, date, author, category).
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

# --- Configuration -----------------------------------------------------------
POSTS_DIR = Path("docs/blog/posts")
INDEX_FILE = Path("docs/blog/index.md")
START_MARKER = "<!-- blog-index:generated:start -->"
END_MARKER = "<!-- blog-index:generated:end -->"

# A setext header underline: a line made only of = or - characters (and spaces)
_SETEXT_UNDERLINE = re.compile(r"^[ =\-]+$")


# --- Front matter parsing ----------------------------------------------------
def parse_front_matter(text: str) -> tuple[dict, str]:
    """Return (metadata, body). metadata is a plain dict of YAML scalar fields.

    Only the first YAML block delimited by leading and trailing `---` lines is
    read. Values are treated as plain strings; surrounding quotes are stripped.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            # Strip surrounding single or double quotes from scalar values
            meta[key.strip()] = value.strip().strip('"').strip("'")
        i += 1
    # Body is everything after the closing `---`
    body = "\n".join(lines[i + 1 :]).lstrip("\n") if i < len(lines) else ""
    return meta, body


def parse_date(value: str) -> date:
    """Convert a 'YYYY-MM-DD' string into a date. Raises ValueError if invalid."""
    return date.fromisoformat(value.strip())


# --- Post collection ----------------------------------------------------------
def collect_posts() -> list[dict]:
    """Read all eligible post files and return them sorted by date descending."""
    posts = []
    for path in sorted(POSTS_DIR.iterdir()):
        if not path.is_file():
            continue
        # Accept .md files and extension-less files (e.g. open-curriculum)
        if path.suffix not in ("", ".md"):
            continue
        text = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(text)
        # Skip posts missing the mandatory title or date fields
        if not meta.get("date") or not meta.get("title"):
            continue
        try:
            d = parse_date(meta["date"])
        except ValueError:
            print(f"⚠️  Invalid date in {path.name}, skipped", file=sys.stderr)
            continue
        # Slug is the file stem for .md files, or the full name when extension-less
        slug = path.stem if path.suffix else path.name
        posts.append(
            {
                "title": meta.get("title", path.stem),
                "date": d,
                "date_str": d.isoformat(),
                "author": meta.get("author", ""),
                "category": meta.get("category", ""),
                "slug": slug,
                "body": body,
            }
        )
    # Newest posts first
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def is_skippable_line(line: str) -> bool:
    """Return True if a line should not appear in an excerpt.

    Skips images, table rows, ATX headers, setext underlines and HTML comments.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("![", "|", "#", "<!--")):
        return True
    # A standalone line of dashes/equals is a setext header underline
    if _SETEXT_UNDERLINE.match(stripped):
        return True
    return False


def excerpt(body: str, max_chars: int = 200) -> str:
    """Return the first prose paragraph as a preview.

    The excerpt is built from the first non-empty paragraph, stopping at any
    line that is a setext underline or otherwise non-prose. Truncates at the
    last word boundary under max_chars and appends an ellipsis.
    """
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # Keep only the leading prose lines within the paragraph
        kept = []
        for line in block.split("\n"):
            if is_skippable_line(line):
                break
            kept.append(line)
        text = " ".join(line.strip() for line in kept).strip()
        if not text:
            continue
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0] + "…"
    return ""


# --- Index rendering ---------------------------------------------------------
def render_index(posts: list[dict]) -> str:
    """Render the managed blog index Markdown from the collected posts."""
    lines = ["# Blog\n"]
    for p in posts:
        d = p["date"].strftime("%d %B %Y")
        link = f"posts/{p['slug']}/"
        lines.append(f"### [{p['title']}]({link})\n")
        meta_bits = [f"**{d}**"]
        if p["author"]:
            meta_bits.append(f"by {p['author']}")
        if p["category"]:
            meta_bits.append(f"· {p['category']}")
        lines.append(" ".join(meta_bits) + "\n")
        ex = excerpt(p["body"])
        if ex:
            lines.append(ex + "\n")
        lines.append("---\n")
    return "\n".join(lines).rstrip() + "\n"


def write_index(content: str) -> None:
    """Write the index, preserving any hand-authored content above the markers.

    If the markers already exist, only the block between them is replaced. If
    they are absent (first run or empty file), the markers are appended.
    """
    generated_block = f"{START_MARKER}\n{content}{END_MARKER}\n"
    if INDEX_FILE.exists():
        text = INDEX_FILE.read_text(encoding="utf-8")
        if START_MARKER in text and END_MARKER in text:
            # Keep everything before the start marker and after the end marker
            pre = text.split(START_MARKER)[0]
            post = text.split(END_MARKER, 1)[1].lstrip("\n")
            INDEX_FILE.write_text(pre + generated_block + post, encoding="utf-8")
            return
    # First run: file is missing or has no sentinel yet
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(generated_block, encoding="utf-8")


def main() -> int:
    """Entry point: collect posts and write the generated index."""
    if not POSTS_DIR.is_dir():
        print(f"❌ Directory not found: {POSTS_DIR}", file=sys.stderr)
        return 1
    posts = collect_posts()
    if not posts:
        print("⚠️  No posts found", file=sys.stderr)
        return 1
    write_index(render_index(posts))
    print(f"✅ {len(posts)} posts indexed into {INDEX_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

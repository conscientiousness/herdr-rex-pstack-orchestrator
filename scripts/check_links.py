#!/usr/bin/env python3
"""Check relative Markdown links in a Git checkout."""

import argparse
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, unquote


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)")
CODE_OR_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)|(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)", re.S)
CODE_PATH = re.compile(r"\.{1,2}/[^\s<>`?#]+\.md(?:[?#][^\s`]+)?")
ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")
INLINE_LINK = re.compile(
    r"(?<!\\)\[(?=(?:\\.|[^\[\]\\]|\[[^\[\]\n]*\])*\]\(\s*"
    r"(?:<(?P<angle>[^<>\n]*)>|(?P<bare>(?:\\.|[^\s()\\]|\([^()\s]*\))*))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\))"
)
IMAGE_TAG = re.compile(r"<(?:img|source)\b(?:[^'\">]|\"[^\"]*\"|'[^']*')*>", re.I)
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class ImageSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value:
                continue
            if tag == "img" and name == "src":
                self.targets.append(value.strip())
            if name == "srcset":
                while value := value.lstrip(" ,\t\n\r\f"):
                    url, *rest = value.split(maxsplit=1)
                    self.targets.append(url.rstrip(","))
                    value = rest[0] if rest else ""
                    if not url.endswith(","):
                        value = value.partition(",")[2]


def mask(text):
    return re.sub(r"[^\n]", " ", text)


def without_fences(text):
    fence = ""
    lines = []
    for line in text.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence:
            lines.append(mask(line))
            if match and match[1].startswith(fence) and not match[2].strip():
                fence = ""
        elif match and (match[1][0] == "~" or "`" not in match[2]):
            fence = match[1]
            lines.append(mask(line))
        else:
            lines.append(line)
    return "".join(lines)


def targets(text, *, check_code_paths):
    text = without_fences(text)
    if check_code_paths:
        for match in CODE_OR_COMMENT.finditer(text):
            target = (match[2] or "").strip()
            if CODE_PATH.fullmatch(target):
                yield text.count("\n", 0, match.start()) + 1, target
    text = CODE_OR_COMMENT.sub(lambda match: mask(match[0]), text)
    for match in INLINE_LINK.finditer(text):
        target = match["angle"] if match["angle"] is not None else match["bare"]
        yield text.count("\n", 0, match.start()) + 1, unescape(ESCAPE.sub(r"\1", target))
    for match in IMAGE_TAG.finditer(text):
        image = ImageSources()
        image.feed(match[0])
        for target in image.targets:
            yield text.count("\n", 0, match.start()) + 1, target


def tracked_files(root, *patterns):
    output = subprocess.check_output(["git", "-C", root, "ls-files", "-z", "--", *patterns])
    return [Path(os.fsdecode(path)) for path in output.split(b"\0") if path]


def suggestion(destination, source_dir, files):
    parts = Path(destination).parts
    for start in range(len(parts) - 1):
        suffix = parts[start:]
        candidates = [path for path in files if path.parts[-len(suffix):] == suffix]
        if candidates:
            links = [Path(os.path.relpath(path, source_dir)) for path in candidates]
            candidate = min(links, key=lambda path: (len(path.parts), path))
            return quote(candidate.as_posix(), safe="/")
    return None


def upstream_paths(root):
    references = Path("skills/pstack-herdr/references")
    try:
        bundle = json.loads((root / references / "bundle.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set(), set()
    skill_dirs = {Path("skills") / skill["name"] for skill in bundle.get("skills", [])}
    agent_files = {references / "agents" / name for name in bundle.get("agents", {})}
    return skill_dirs, agent_files


def check(root):
    files = tracked_files(root)
    upstream_skill_dirs, upstream_agent_files = upstream_paths(root)
    failures = []
    for path in tracked_files(root, "*.md"):
        # Upstream code examples can assume a different checkout layout.
        upstream_owned = path in upstream_agent_files or any(
            parent in upstream_skill_dirs for parent in path.parents
        )
        links = targets((root / path).read_text(encoding="utf-8"),
                        check_code_paths=not upstream_owned)
        for line, target in sorted(links):
            if target.startswith("/") or SCHEME.match(target):
                continue
            raw_path = re.split(r"[?#]", target, maxsplit=1)[0]
            destination = unquote(raw_path)
            if not destination or (root / path.parent / destination).exists():
                continue
            failures.append(f"{path}:{line}: link '{target}' does not exist")
            fix = suggestion(destination, path.parent, files)
            if fix:
                failures.append(f"  did you mean '{fix}{target[len(raw_path):]}'?")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Git checkout to check (default: this repository)")
    args = parser.parse_args()
    failures = check(args.root.resolve())
    if failures:
        print("\n".join(failures))
        return 1
    print("Relative Markdown links pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

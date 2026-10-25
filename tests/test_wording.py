"""Wording check for text that gets published: prose files, comments, docstrings and golden-set notes.

Published text keeps one neutral documentation voice and carries no personal or machine details, so this scans for
first-person wording, role-style references to the maintainer, usernames and drive paths. String literals in code
and corpus-derived data (questions, passages, reference answers, per-question notes) are out of scope: they quote
the daycare documents or sample model output, where "owner" means a dog owner and a model may speak in first person.
"""
import ast
import io
import json
import re
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROSE_SUFFIXES = {".md", ".txt", ".toml"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "runs"}

FIRST_PERSON = re.compile(r"\b(I|I'm|I've|I'll|I'd|[Mm]y|[Ww]e|[Ww]e're|[Ww]e've|[Oo]ur|[Mm]ine)\b")
MAINTAINER_ROLE = re.compile(r"\b(project|repo|repository) owner\b|\bthe owner of (this|the) (project|repo)", re.I)
OWNER = re.compile(r"\bowners?\b", re.I)
# a line that is about the daycare corpus may say "owner" (a dog owner)
CORPUS_CONTEXT = re.compile(r"\b(dogs?|pets?|puppy|daycare|boarding|vaccin\w*|corpus|documents?|owner agreement)\b", re.I)
PERSONAL = re.compile(r"\bnbhas\b|ryann|haskell|\bgmail\b|[A-Za-z]:[\\/]|/Users/|/home/", re.I)
URL = re.compile(r"https?://\S+")


def candidate_files() -> list[Path]:
    """Tracked files, plus new files that are not git-ignored; falls back to a directory walk without git."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        return [ROOT / name for name in out if (ROOT / name).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def python_prose(source: str) -> list[tuple[int, str]]:
    """Comments and docstrings of a Python file, with their line numbers."""
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            found.append((tok.start[0], tok.string))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                first = node.body[0]
                found.append((first.lineno, doc))
    return found


def markdown_prose(text: str) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks."""
    lines, fenced = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            lines.append((number, line))
    return lines


def golden_notes(path: Path) -> list[tuple[int, str]]:
    """The header `notes` of a golden set. Per-item notes are carried over from the source question files, so they
    are data about the corpus, not project prose."""
    note = json.loads(path.read_text(encoding="utf-8")).get("notes")
    return [(0, note)] if isinstance(note, str) else []


def problems_in(text: str, line_offset: int = 0) -> list[str]:
    """Wording problems in a block of text; each is 'line N: reason: matched text'."""
    problems = []
    for number, line in enumerate(text.splitlines() or [""], 1):
        shown = line_offset + number
        plain = URL.sub("", line)  # a repository URL may name the account; prose may not
        for match in FIRST_PERSON.finditer(plain):
            problems.append(f"line {shown}: first person: {match.group(0)!r}")
        for match in MAINTAINER_ROLE.finditer(plain):
            problems.append(f"line {shown}: refers to the maintainer by role: {match.group(0)!r}")
        if OWNER.search(plain) and not CORPUS_CONTEXT.search(plain) and not MAINTAINER_ROLE.search(plain):
            problems.append(f"line {shown}: 'owner' outside the dog-owner sense")
        for match in PERSONAL.finditer(plain):
            problems.append(f"line {shown}: username, address or drive path: {match.group(0)!r}")
    return problems


def scan(path: Path) -> list[str]:
    relative = path.relative_to(ROOT).as_posix()
    if path.suffix == ".py":
        blocks = python_prose(path.read_text(encoding="utf-8"))
    elif path.suffix == ".md":
        blocks = markdown_prose(path.read_text(encoding="utf-8"))
    elif path.suffix in PROSE_SUFFIXES:
        blocks = [(n, line) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)]
    elif path.suffix == ".json" and path.parent.name == "golden":
        blocks = golden_notes(path)
    else:
        return []
    found = []
    for start, text in blocks:
        found += [f"{relative}: {p}" for p in problems_in(text, max(start - 1, 0))]
    return found


def test_published_text_has_a_neutral_voice():
    problems = [p for path in candidate_files() for p in scan(path)]
    assert not problems, "wording problems:\n" + "\n".join(problems)


@pytest.mark.parametrize("text", [
    "I think this is slow.",
    "We reviewed the answers.",
    "This is my machine's result.",
    "reviewed by the project owner",
    "The owner approved the change.",
    "Saved under C:\\Users\\someone\\citeCheck",
    "See /Users/someone/project",
    "written by nbhas",
    "contact someone@gmail.com",
])
def test_scanner_flags_what_it_should(text):
    assert problems_in(text)


@pytest.mark.parametrize("text", [
    "Owners must send vaccination records for the dog.",
    "The dog owner agreement is signed at the evaluation.",
    "Metrics are written in plain Python.",
    "Source: https://github.com/Nbhaskell/rag-project",
    "Run `py -3.13 -m venv .venv` first.",
    "The harness records the model it used.",
])
def test_scanner_allows_normal_text(text):
    assert not problems_in(text)

"""Check of text that gets published: prose files, comments, docstrings and golden-set notes.

The check does two jobs and keeps them apart in the result.

Personal information (usernames, mail addresses, drive paths) fails the check, and a failed check stops the change.

Doc wording (first person, a role-style reference to the maintainer) is reported as a warning and the check passes,
because a pattern cannot tell the voice of the docs from a quoted customer or model message. Published text still
keeps one neutral documentation voice; only the enforcement is a warning.

String literals in code and corpus-derived data (questions, passages, reference answers, per-question notes) are out
of scope: they quote the daycare documents or sample model output, where "owner" means a dog owner and a model may
speak in first person.
"""
import ast
import io
import json
import re
import subprocess
import tokenize
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROSE_SUFFIXES = {".md", ".txt", ".toml"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "runs"}

# The pronoun before a present-tense verb that ends in "ed" (need, feed, proceed) is not matched; before the past
# tense (needed, proceeded) it is.
NOT_PAST_TENSE = r"(?! (?:need|feed|speed|heed|seed|proceed|succeed|exceed)\b)"
FIRST_PERSON = re.compile(rf"\b(I{NOT_PAST_TENSE}|I'm|I've|I'll|I'd|[Mm]y|[Ww]e|[Ww]e're|[Ww]e've|[Oo]ur|[Mm]ine)\b")
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


class Problem(NamedTuple):
    text: str  # 'line N: reason: matched text'
    warning: bool  # doc wording: reported, does not fail the check


def problems_in(text: str, line_offset: int = 0) -> list[Problem]:
    """Problems in a block of text. Doc-wording problems are warnings; personal information is not."""
    problems = []
    for number, line in enumerate(text.splitlines() or [""], 1):
        shown = line_offset + number
        plain = URL.sub("", line)  # a repository URL may name the account; prose may not
        for match in FIRST_PERSON.finditer(plain):
            problems.append(Problem(f"line {shown}: first person: {match.group(0)!r}", True))
        for match in MAINTAINER_ROLE.finditer(plain):
            problems.append(Problem(f"line {shown}: refers to the maintainer by role: {match.group(0)!r}", True))
        if OWNER.search(plain) and not CORPUS_CONTEXT.search(plain) and not MAINTAINER_ROLE.search(plain):
            problems.append(Problem(f"line {shown}: 'owner' outside the dog-owner sense", True))
        for match in PERSONAL.finditer(plain):
            problems.append(Problem(f"line {shown}: username, address or drive path: {match.group(0)!r}", False))
    return problems


def report(problems: Iterable[Problem]) -> list[str]:
    """Emits one warning that lists the doc-wording problems, and returns the personal-information problems."""
    problems = list(problems)
    wording = [p.text for p in problems if p.warning]
    if wording:
        warnings.warn("doc wording warnings (not blocking):" + "".join(f"\n  {line}" for line in wording)
                      + "\nDescribe the action or the decision in one neutral voice.", stacklevel=2)
    return [p.text for p in problems if not p.warning]


def scan(path: Path) -> list[Problem]:
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
        found += [Problem(f"{relative}: {p.text}", p.warning) for p in problems_in(text, max(start - 1, 0))]
    return found


def test_published_text_has_no_personal_information():
    """Doc-wording problems in the published files are printed in the pytest warnings summary and do not fail."""
    blocking = report(p for path in candidate_files() for p in scan(path))
    assert not blocking, "personal information check failed:\n" + "\n".join(blocking)


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


# --- wording problems warn; personal information fails the check ---------------------------------

PRESENT_TENSE = ["need", "feed", "speed", "heed", "seed", "proceed", "succeed", "exceed"]


@pytest.mark.parametrize("verb", PRESENT_TENSE)
def test_present_tense_verbs_that_end_in_ed_are_not_first_person(verb):
    assert problems_in(f"| 1 | Type: `I {verb} a new record.` | The answer cites the document. |") == []
    assert problems_in(f"I {verb}.") == []


@pytest.mark.parametrize("verb", PRESENT_TENSE)
def test_the_past_tense_forms_are_still_first_person(verb):
    found = problems_in(f"I {verb}ed more data.")
    assert [p.warning for p in found] == [True]
    assert "first person" in found[0].text


def test_wording_problems_are_warnings_and_personal_information_is_not():
    text = "I measured it.\nreviewed by the project owner\nThe owner approved the change.\nwritten by nbhas\n"
    found = problems_in(text)
    assert [p.warning for p in found] == [True, True, True, False]
    assert [p.text.split(":")[0] for p in found] == ["line 1", "line 2", "line 3", "line 4"]
    assert [p.warning for p in problems_in("Saved under C:\\Users\\someone\\citeCheck")] == [False]
    assert [p.warning for p in problems_in("contact someone@gmail.com")] == [False]


def test_report_warns_about_wording_and_returns_nothing_to_fail_on():
    found = problems_in("I measured the run.")
    with pytest.warns(UserWarning, match="line 1: first person"):
        assert report(found) == []


def test_report_returns_personal_information_and_still_warns_about_wording():
    found = problems_in("I measured the run.\nwritten by nbhas")
    with pytest.warns(UserWarning, match="line 1: first person"):
        blocking = report(found)
    assert len(blocking) == 1
    assert blocking[0].startswith("line 2: username, address or drive path")


def test_report_does_not_warn_when_there_is_no_wording_problem(recwarn):
    assert report(problems_in("The harness records the model it used.")) == []
    assert len(recwarn) == 0

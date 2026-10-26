"""Figure grounding: does every figure, date and time in an answer appear in what the answer was built from?

No model is involved, so every number here is deterministic. The judge reads an answer for meaning and often lets a small
change to a figure or a date pass; this check reads it for the figures alone. It finds each money amount, number, date
and time of day in the answer, and asks whether the same value appears in the sources (the passages the target returned, or
the excerpts it cited), in the question, or in the earlier turns of the conversation.

    ungrounded   a figure whose value appears in none of those texts
    underived    an ungrounded number that is also not the sum, difference, product or quotient of two numbers that do
                 appear (answers that add up a price, or multiply it by a count, state numbers no passage prints)

Dates and times of day get the first test only, since arithmetic does not produce them. The second test is lenient on
purpose, so a changed figure that happens to equal such a combination is missed; both counts are reported.

What is compared, and what is not:
    - a money amount or number compares by value, so "$100" matches "100.00"; "44.0 billion" matches "44,000 million"
    - a date compares as (year, month, day) however it is written ("Dec. 31, 2025", "31 December 2025", "2025-12-31")
    - a time of day compares as (hour on a 12-hour clock, minute); am and pm are not told apart
    - a number word in a source or question ("three") counts as its value; number words in an answer are not checked
    - citation markers such as [2], list numbering, and form names such as 10-K are not figures
    - a figure that rests on reading rather than arithmetic ("an hour late" for 7pm against 6pm) is reported as underived
"""
import re

from .citations import MARKER

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
          "september": 9, "october": 10, "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4,
          "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}

DATE_MDY = re.compile(rf"\b({MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})\b", re.I)
DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH})\.?,?\s+(\d{{4}})\b", re.I)
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
TIME_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})(?:\s*[ap]\.?m\.?)?(?!\d)", re.I)
TIME_HOUR = re.compile(r"\b(\d{1,2})\s*[ap]\.?m\b\.?", re.I)
FORM = re.compile(r"\b\d{1,2}-[KQ]\b")
LIST_ITEM = re.compile(r"(?m)^[ \t]*(?:[-*][ \t]+)?\d{1,2}[.)][ \t]+(?=\S)")
NUMBER = re.compile(rf"(?<![\w.])\$?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?(?:\s*({'|'.join(SCALES)})\b)?", re.I)
WORD = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.I)

TRIVIAL_OPERANDS = (0, 1)  # as an operand these put any number one step from another, which would explain too much


def key(value: float) -> float:
    return round(value, 4)


def blank(match: re.Match) -> str:
    return " " * len(match.group(0))


def extract(text: str) -> list[dict]:
    """Every figure in the text as {"kind": date | time | number, "keys": values it matches by, "text": as written}."""
    text = LIST_ITEM.sub(blank, MARKER.sub(" ", text))
    found = []

    def take(pattern, build):
        nonlocal text

        def replace(match):
            found.append({"text": match.group(0).strip().rstrip("."), **build(match)})
            return blank(match)
        text = pattern.sub(replace, text)

    take(DATE_ISO, lambda m: {"kind": "date", "keys": [("date", int(m[1]), int(m[2]), int(m[3]))]})
    take(DATE_MDY, lambda m: {"kind": "date", "keys": [("date", int(m[3]), MONTHS[m[1].lower()], int(m[2]))]})
    take(DATE_DMY, lambda m: {"kind": "date", "keys": [("date", int(m[3]), MONTHS[m[2].lower()], int(m[1]))]})
    take(TIME_CLOCK, lambda m: {"kind": "time", "keys": [("time", int(m[1]) % 12, int(m[2]))]})
    take(TIME_HOUR, lambda m: {"kind": "time", "keys": [("time", int(m[1]) % 12, 0)]})
    text = FORM.sub(blank, text)

    def number(match):
        value = float(re.sub(r"[$,]", "", re.sub(r"\s*[a-z]+$", "", match.group(0), flags=re.I)))
        keys = [key(value)]
        if match.group(1):
            keys.append(key(value * SCALES[match.group(1).lower()]))
        return {"kind": "number", "keys": keys}
    take(NUMBER, number)
    return found


def allowed_keys(texts) -> set:
    """Every value the texts state: their figures, the parts of their dates, and their number words."""
    allowed = set()
    for text in texts:
        for figure in extract(text):
            allowed.update(figure["keys"])
            if figure["kind"] == "date":
                _, year, month, day = figure["keys"][0]
                allowed.update((key(year), key(day)))
        allowed.update(key(WORDS[w.lower()]) for w in WORD.findall(text))
    return allowed


def derivable(value: float, numbers: set) -> bool:
    """Whether value is the sum, difference, product or quotient (or a percentage) of two of the numbers."""
    rounded = {round(n, 2) for n in numbers if n not in TRIVIAL_OPERANDS}
    for a in rounded:
        if a == 0:
            continue
        for candidate in (value - a, a - value, value / a, a / value if value else None, value * 100 / a):
            if candidate is not None and round(candidate, 2) in rounded:
                return True
    return False


def check(answer: str, sources, context=()) -> dict:
    """The figures in an answer, and which of them the sources, the question and the earlier turns do not support."""
    figures = extract(answer)
    allowed = allowed_keys(list(sources) + list(context))
    numbers = {k for k in allowed if isinstance(k, float)}
    ungrounded = [f for f in figures if not any(k in allowed for k in f["keys"])]
    underived = [f for f in ungrounded if f["kind"] != "number" or not derivable(f["keys"][0], numbers)]
    return {"n": len(figures), "ungrounded": [f["text"] for f in ungrounded], "underived": [f["text"] for f in underived]}


def summarize(checks) -> dict:
    """Aggregate check() results, one per answer that was not declined."""
    checks = list(checks)
    with_figures = [c for c in checks if c["n"]]
    return {
        "answers": len(checks), "with_figures": len(with_figures),
        "all_grounded": sum(not c["ungrounded"] for c in with_figures),
        "all_derivable": sum(not c["underived"] for c in with_figures),
        "figures": sum(c["n"] for c in checks),
        "ungrounded": sum(len(c["ungrounded"]) for c in checks),
        "underived": sum(len(c["underived"]) for c in checks)}

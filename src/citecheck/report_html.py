"""HTML pages for reports and comparisons: one self-contained file each, with no script and no outside resources.

The pages are rendered from the JSON copies that sit beside the Markdown pages (`*.report.json` from `report`, `*.compare.json`
from `compare`), so an HTML page holds exactly the numbers its Markdown page holds and nothing is re-scored or re-computed. A
page is first described as blocks, as compare.document() already does for its page:

    ("h1" | "h2" | "h3" | "p", text)      text may use `code` and **bold**
    ("ol" | "ul", [text])
    ("table", header, rows)               a cell is text, a list of texts (shown as a list) or ("link", text, href)
    ("details", summary, open, blocks)    a section the reader can collapse

and blocks_to_html() turns them into the page. Every text is escaped, so nothing in a report can inject markup. The pages follow
the reader's light or dark setting and fit a phone's width; a wide table scrolls inside its own box.
"""
import html
import json
import re
from pathlib import Path

from . import compare, report

CSS = """
:root { --bg:#fbfaf8; --fg:#1d1d1b; --muted:#625f59; --card:#ffffff; --line:#dedbd4; --accent:#2f5d8a; --code:#f0eee8;
  --info-bg:#e1ecf7; --info-fg:#1f4568; --warn-bg:#fff0d4; --warn-fg:#704400; --calm-bg:#ecebe7; --calm-fg:#4a4944; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecebe8; --muted:#a8a69f; --card:#1f1f1d; --line:#3a3932;
  --accent:#86b6e6; --code:#2a2a27; --info-bg:#1e3447; --info-fg:#b6d6f4; --warn-bg:#40300f; --warn-fg:#f0cf8a;
  --calm-bg:#2c2c29; --calm-fg:#c9c7c0; } }
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:70rem; margin:0 auto; padding:16px; }
h1 { font-size:1.7rem; line-height:1.25; margin:.4em 0 .3em; overflow-wrap:anywhere; }
h2 { font-size:1.3rem; margin:2em 0 .5em; padding-top:.6em; border-top:1px solid var(--line); }
h3 { font-size:1.05rem; margin:1.5em 0 .4em; }
p, li { max-width:65ch; overflow-wrap:anywhere; }
a { color:var(--accent); }
code { background:var(--code); padding:.05em .35em; border-radius:4px; font-size:.9em; overflow-wrap:anywhere; }
.crumb, .toc { font-size:.92rem; color:var(--muted); }
.toc { display:flex; flex-wrap:wrap; gap:.4rem 1rem; margin:.8rem 0 0; padding:.5rem 0; border-top:1px solid var(--line); }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card); margin:.6rem 0 1rem; }
table { border-collapse:collapse; width:100%; font-size:.92rem; }
th, td { padding:.45rem .7rem; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }
th { font-weight:600; background:var(--card); }
tr:last-child td { border-bottom:0; }
td ul { margin:0; padding-left:1.1rem; color:var(--muted); font-size:.88rem; }
td ul li { margin:.2rem 0; max-width:none; }
.badge { display:inline-block; padding:.1em .6em; border-radius:999px; font-weight:600; font-size:.85rem; white-space:nowrap; }
.badge.larger { background:var(--info-bg); color:var(--info-fg); }
.badge.unclear { background:var(--warn-bg); color:var(--warn-fg); }
.badge.within { background:var(--calm-bg); color:var(--calm-fg); }
details { margin:.6rem 0 1rem; }
summary { cursor:pointer; color:var(--accent); font-weight:600; }
@media (max-width: 40rem) { main { padding:12px; } h1 { font-size:1.4rem; } th, td { padding:.4rem .5rem; } }
"""

VERDICT = re.compile(r"\*\*(larger than noise|unclear|within noise)\*\*")
BADGE_CLASS = {"larger than noise": "larger", "unclear": "unclear", "within noise": "within"}
CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def inline(text) -> str:
    """Escaped text with `code` and **bold** turned into elements."""
    return BOLD.sub(r"<strong>\1</strong>", CODE.sub(r"<code>\1</code>", esc(text)))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cell_html(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, tuple) and value[0] == "link":
        return f'<a href="{esc(value[2])}">{inline(value[1])}</a>'
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{inline(v)}</li>" for v in value) + "</ul>" if value else "-"
    badge = VERDICT.fullmatch(str(value))
    if badge:
        return f'<span class="badge {BADGE_CLASS[badge.group(1)]}">{esc(badge.group(1))}</span>'
    return inline(value)


def table_html(header, rows) -> str:
    head = "".join(f'<th scope="col">{inline(h)}</th>' for h in header)
    body = "".join("<tr>" + "".join(f"<td>{cell_html(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def blocks_to_html(blocks: list[tuple]) -> str:
    out = []
    for block in blocks:
        kind = block[0]
        if kind == "h1":
            out.append(f"<h1>{inline(block[1])}</h1>")
        elif kind == "h2":
            out.append(f'<h2 id="{slug(block[1])}">{inline(block[1])}</h2>')
        elif kind == "h3":
            out.append(f"<h3>{inline(block[1])}</h3>")
        elif kind in ("ol", "ul"):
            out.append(f"<{kind}>" + "".join(f"<li>{inline(t)}</li>" for t in block[1]) + f"</{kind}>")
        elif kind == "table":
            out.append(table_html(block[1], block[2]))
        elif kind == "details":
            out.append(f"<details{' open' if block[2] else ''}><summary>{inline(block[1])}</summary>{blocks_to_html(block[3])}</details>")
        else:
            out.append(f"<p>{inline(block[1])}</p>")
    return "\n".join(out)


def page(title: str, blocks: list[tuple], back: str | None = None) -> str:
    """A whole HTML page for the blocks. `back` is the address of an index page to link to from the top."""
    headings = [(b[1], slug(b[1])) for b in blocks if b[0] == "h2"]
    toc = ('<nav class="toc" aria-label="Sections">' + "".join(f'<a href="#{s}">{esc(t)}</a>' for t, s in headings) + "</nav>"
           if len(headings) > 2 else "")
    crumb = f'<p class="crumb"><a href="{esc(back)}">All reports</a></p>' if back else ""
    first = next(i for i, b in enumerate(blocks) if b[0] == "h1")
    lead = [b for b in blocks[first + 1:first + 2] if b[0] == "p"]  # the line under the title, shown before the contents
    rest = blocks[first + 1 + len(lead):]
    description = re.sub(r"[`*]", "", lead[0][1] if lead else title)
    return ("<!doctype html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{esc(title)} · CiteCheck</title>\n"
            f'<meta name="description" content="{esc(description)}">\n'
            f"<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
            f"{crumb}\n{blocks_to_html(blocks[first:first + 1] + lead)}\n{toc}\n{blocks_to_html(rest)}\n"
            "</main>\n</body>\n</html>\n")


# --- a report for one scored run -----------------------------------------------------------------------------------

def report_blocks(data: dict) -> list[tuple]:
    """The blocks of render_markdown(), with each row's caveats as a list."""
    run, golden, judge = data["run"], data["golden"], data["judge"]
    server = data["target"]["describe"].get("server", {})
    blocks = [("h1", data["title"]),
              ("p", f"Run `{run['run_id']}`, made {run['created']} with citecheck {str(run['citecheck'].get('commit'))[:10]}"
                    f"{' (uncommitted changes)' if run['citecheck'].get('dirty') else ''}. "
                    f"Question set `{golden['version']}` ({golden['items']} items), hash `{golden['hash'][:12]}`.")]
    if server:
        blocks.append(("p", "Target: " + ", ".join(f"{k} {v}" for k, v in server.items() if not isinstance(v, (list, dict))) + "."))
    declared = data["target"]["describe"].get("declared")
    if declared:
        blocks.append(("p", "Settings the target does not report, recorded by hand: "
                            + ", ".join(f"{k}={v}" for k, v in declared.items()) + "."))
    blocks += [("p", "Judge: " + (report.describe_judge(judge) + f", model digest `{judge['model_digest'][:12]}`." if judge else "none for this report.")),
               ("h2", "How to read this"),
               ("p", "Each score sits beside what is known about how far to trust it. Retrieval and the structure of the citations are "
                     "counted from the target's own output. Faithfulness, correctness, abstention and claim support are a model's verdicts "
                     "and are only as good as the calibration shown next to them. Nothing here compares this target with another: the "
                     "question sets, corpora and checks differ.")]
    for section in ("Retrieval", "Answers", "Citations"):
        rows = [r for r in data["rows"] if r["section"] == section]
        if rows:
            blocks += [("h2", section), ("table", ["Metric", "Result", "n", "Evidence and caveats"],
                                         [[r["metric"], r["result"], r["n"], r["caveats"]] for r in rows])]
    blocks.append(("h2", "By split and category"))
    for title, key in (("By split", "by_split"), ("By category", "by_category")):
        header, body = report.group_table(data[key])
        blocks += [("h3", title), ("table", header, body)]
    blocks += [("h2", "What this cannot tell you"), ("ul", list(data["limits"]))]
    looks = data["items_to_look_at"]
    blocks += [("h2", f"Items to look at ({len(looks)})"),
               ("p", "Every question with something unusual in its result. This is a reading list, not a failure count: a flag from "
                     "the judge may be the judge's mistake.")]
    if looks:
        blocks.append(("details", f"Show the {len(looks)} items", len(looks) <= 15, [
            ("table", ["Item", "Category", "Why"], [[f"`{i['item_id']}`", i["category"], i["reasons"]] for i in looks])]))
    else:
        blocks.append(("p", "None."))
    if data["sources"]:
        blocks += [("h2", "Files"), ("ul", [f"{name}: `{path}`" for name, path in data["sources"].items()])]
    return blocks


def index_blocks(reports: list[dict], names: dict) -> list[tuple]:
    """The index of a folder of reports; `names` maps a run id to the address of its page."""
    rows = []
    for data in sorted(reports, key=lambda r: (r["run"]["created"], r["title"])):
        calibrated = data["calibrated"]
        status = ("no judge" if data["judge"] is None else
                  "judge calibrated for " + (" and ".join(k for k, v in calibrated.items() if v) or "nothing"))
        rows.append([("link", data["title"], names[data["run"]["run_id"]]), data["run"]["created"][:10], data["target"]["name"],
                     f"{data['golden']['version']} ({data['golden']['items']})", status])
    return [("h1", "Reports"),
            ("p", "One report per scored run. They are not ranked and not comparable with each other: each uses its own question set, "
                  "corpus and target, and some checks apply to one target and not another. Read each report's own caveats."),
            ("table", ["Report", "Run date", "Target", "Question set (items)", "Judge"], rows)]


# --- files ---------------------------------------------------------------------------------------------------------

SIDECARS = (".report.json", ".compare.json")


def kind_of(data: dict) -> str:
    if "comparisons" in data:
        return "comparison"
    if "items_to_look_at" in data and "rows" in data:
        return "report"
    raise ValueError("not a report or a comparison JSON file")


def html_name(sidecar: Path) -> Path:
    for suffix in SIDECARS:
        if sidecar.name.endswith(suffix):
            return sidecar.with_name(sidecar.name.removesuffix(suffix) + ".html")
    raise ValueError(f"{sidecar.name} is not a *.report.json or *.compare.json file")


def render_file(path, back: str | None = None) -> tuple[Path, str]:
    """The HTML page for one JSON copy, and where it belongs (beside the JSON)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = compare.document(data) if kind_of(data) == "comparison" else report_blocks(data)
    return html_name(path), page(data["title"], blocks, back)


def render_folder(folder) -> list[Path]:
    """An HTML page for every report and comparison JSON in a folder, and an index of the reports. Returns what was written."""
    folder = Path(folder)
    sidecars = sorted(p for p in folder.iterdir() if p.name.endswith(SIDECARS))
    if not sidecars:
        raise ValueError(f"no *.report.json or *.compare.json files in {folder}")
    written, reports, names = [], [], {}
    for sidecar in sidecars:
        target, text = render_file(sidecar, back="index.html")
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target)
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if kind_of(data) == "report":
            reports.append(data)
            names[data["run"]["run_id"]] = target.name
    if reports:
        index = folder / "index.html"
        index.write_text(page("Reports", index_blocks(reports, names)), encoding="utf-8", newline="\n")
        written.append(index)
    return written

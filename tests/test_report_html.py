import html
import json
import re
from pathlib import Path

import pytest

from citecheck import cli, compare, report_html

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def load(name):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline():
    return load("rag-project-baseline.report.json")


@pytest.fixture(scope="module")
def comparison():
    return load("rag-project-top-k.compare.json")


# --- text and cells ----------------------------------------------------------------------------------------------

def test_text_is_escaped_and_only_code_and_bold_become_elements():
    assert report_html.inline("a <b> & `x < y` and **bold**") == "a &lt;b&gt; &amp; <code>x &lt; y</code> and <strong>bold</strong>"
    assert "<script" not in report_html.inline("<script>alert(1)</script>")


def test_cells_render_lists_links_badges_and_blanks():
    assert report_html.cell_html(None) == report_html.cell_html("") == report_html.cell_html([]) == "-"
    assert report_html.cell_html(["one", "`two`"]) == "<ul><li>one</li><li><code>two</code></li></ul>"
    assert report_html.cell_html(("link", "A & B", "a.html")) == '<a href="a.html">A &amp; B</a>'
    assert report_html.cell_html("**larger than noise**") == '<span class="badge larger">larger than noise</span>'
    assert report_html.cell_html("**unclear**") == '<span class="badge unclear">unclear</span>'
    assert report_html.cell_html("**within noise**") == '<span class="badge within">within noise</span>'
    assert report_html.cell_html(0) == "0"


def test_a_page_is_self_contained_and_has_no_script():
    blocks = [("h1", "Title"), ("p", "Lead with `code`."), ("h2", "One"), ("p", "x"), ("h2", "Two"), ("p", "y"),
              ("h2", "Three"), ("table", ["A"], [["1"]])]
    text = report_html.page("Title", blocks, back="index.html")
    assert text.startswith("<!doctype html>") and '<html lang="en">' in text and 'name="viewport"' in text
    assert "<script" not in text and "http://" not in text and "https://" not in text
    assert '<meta name="description" content="Lead with code.">' in text
    assert '<a href="index.html">All reports</a>' in text
    assert text.count('<nav class="toc"') == 1 and '<a href="#two">Two</a>' in text
    assert "<nav" not in report_html.page("T", [("h1", "T"), ("h2", "Only"), ("p", "x")])  # too few sections for a contents list


def test_markup_in_a_report_cannot_reach_the_page(baseline):
    baseline = json.loads(json.dumps(baseline))
    baseline["limits"].append("<img src=x onerror=alert(1)> and </script>")
    baseline["title"] = "<b>title</b>"
    text = report_html.page(baseline["title"], report_html.report_blocks(baseline))
    assert "<img" not in text and "<b>title</b>" not in text and "&lt;img" in text and "&lt;b&gt;title" in text


# --- a report ----------------------------------------------------------------------------------------------------

def test_a_report_page_holds_every_row_limit_and_item_of_its_data(baseline):
    text = report_html.page(baseline["title"], report_html.report_blocks(baseline))
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    plain_text = lambda value: value.replace("`", "")  # the page shows `code` as code, without the backticks
    for row in baseline["rows"]:
        assert plain_text(row["metric"]) in plain and plain_text(row["result"]) in plain
        for caveat in row["caveats"]:
            assert plain_text(caveat) in plain
    for limit in baseline["limits"]:
        assert plain_text(limit) in plain
    for item in baseline["items_to_look_at"]:
        assert item["item_id"] in plain and all(plain_text(reason) in plain for reason in item["reasons"])
    assert f"Items to look at ({len(baseline['items_to_look_at'])})" in plain
    assert baseline["run"]["run_id"] in plain and baseline["golden"]["hash"][:12] in plain


def test_caveats_are_a_list_beside_their_metric(baseline):
    text = report_html.page(baseline["title"], report_html.report_blocks(baseline))
    assert text.count("<td><ul><li>") >= 4


def test_a_long_reading_list_starts_collapsed_and_a_short_one_open(baseline):
    long_page = report_html.blocks_to_html(report_html.report_blocks(baseline))
    assert "<details><summary>Show the 21 items" in long_page
    short = json.loads(json.dumps(baseline))
    short["items_to_look_at"] = short["items_to_look_at"][:3]
    assert "<details open>" in report_html.blocks_to_html(report_html.report_blocks(short))
    short["items_to_look_at"] = []
    assert "None." in report_html.blocks_to_html(report_html.report_blocks(short))


# --- a comparison ------------------------------------------------------------------------------------------------

def test_a_comparison_page_shows_every_verdict_as_a_badge_with_its_text(comparison):
    text = report_html.page(comparison["title"], compare.document(comparison))
    verdicts = [r["verdict"] for c in comparison["comparisons"] for n, r in c["results"].items() if n in compare.HEADLINE]
    badges = re.findall(r'<span class="badge (\w+)">([^<]+)</span>', text)
    assert sorted(t for _, t in badges) == sorted(verdicts)
    assert {c for c, _ in badges} == {"larger", "unclear", "within"}
    for arm in comparison["arms"]:
        assert arm["label"] in text


def test_the_comparison_blocks_still_give_the_committed_markdown(comparison):
    assert compare.to_markdown(compare.document(comparison)) == (REPORTS / "rag-project-top-k.md").read_text(encoding="utf-8")


# --- the index and the files -------------------------------------------------------------------------------------

def test_the_index_links_each_report_page_and_leaves_out_comparisons(baseline):
    other = load("citewise-baseline.report.json")
    names = {baseline["run"]["run_id"]: "rag-project-baseline.html", other["run"]["run_id"]: "citewise-baseline.html"}
    text = report_html.page("Reports", report_html.index_blocks([baseline, other], names))
    assert 'href="rag-project-baseline.html"' in text and 'href="citewise-baseline.html"' in text
    assert "top-k" not in text and "not comparable with each other" in text


def test_the_command_writes_pages_beside_the_json_and_an_index_for_a_folder(tmp_path, capsys):
    for name in ("rag-project-baseline.report.json", "citewise-baseline.report.json", "rag-project-top-k.compare.json"):
        (tmp_path / name).write_text((REPORTS / name).read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["html", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.html")) == [
        "citewise-baseline.html", "index.html", "rag-project-baseline.html", "rag-project-top-k.html"]
    assert '<a href="index.html">All reports</a>' in (tmp_path / "rag-project-top-k.html").read_text(encoding="utf-8")
    single = tmp_path / "one"
    single.mkdir()
    (single / "x.compare.json").write_text((REPORTS / "rag-project-top-k.compare.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["html", str(single / "x.compare.json"), "--back", "../index.html"]) == 0
    assert 'href="../index.html"' in (single / "x.html").read_text(encoding="utf-8")


def test_the_command_refuses_a_file_that_is_not_a_report(tmp_path, capsys):
    junk = tmp_path / "x.report.json"
    junk.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    assert cli.main(["html", str(junk)]) == 1
    assert "cannot write the page" in capsys.readouterr().out
    other = tmp_path / "y.json"
    other.write_text("{}", encoding="utf-8")
    assert cli.main(["html", str(other)]) == 1


def test_the_committed_html_pages_match_their_json(tmp_path):
    for sidecar in sorted(REPORTS.glob("*.report.json")) + sorted(REPORTS.glob("*.compare.json")):
        target, text = report_html.render_file(sidecar, back="index.html")
        assert target.name.endswith(".html")
        assert (REPORTS / target.name).read_text(encoding="utf-8") == text, f"{target.name} is out of date: run `citecheck html reports`"
    reports = [load(p.name) for p in sorted(REPORTS.glob("*.report.json"))]
    names = {r["run"]["run_id"]: p.name.removesuffix(".report.json") + ".html" for r, p in zip(reports, sorted(REPORTS.glob("*.report.json")))}
    assert (REPORTS / "index.html").read_text(encoding="utf-8") == report_html.page("Reports", report_html.index_blocks(reports, names))


# --- colours -----------------------------------------------------------------------------------------------------

def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tokens(block):
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def test_text_colours_have_enough_contrast_in_the_light_and_dark_themes():
    css = report_html.CSS
    light = tokens(css.split("@media")[0])
    dark = tokens(css.split("@media (prefers-color-scheme: dark)")[1])
    pairs = [("fg", "bg"), ("fg", "card"), ("muted", "bg"), ("muted", "card"), ("accent", "bg"), ("accent", "card"),
             ("info-fg", "info-bg"), ("warn-fg", "warn-bg"), ("calm-fg", "calm-bg"), ("fg", "code")]
    for name, theme in (("light", light), ("dark", {**light, **dark})):
        for foreground, background in pairs:
            assert contrast(theme[foreground], theme[background]) >= 4.5, f"{name}: {foreground} on {background}"
    assert "prefers-color-scheme: dark" in css and "max-width: 40rem" in css

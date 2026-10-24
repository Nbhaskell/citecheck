import json

import pytest

from citecheck import cli, runner
from citecheck.adapters import AdapterError, MockAdapter
from test_runner import make_golden, mock


class Crash(Exception):
    """Stands in for a power cut or Ctrl-C: not an AdapterError, so nothing catches it."""


class CrashesAt(MockAdapter):
    def __init__(self, responses, crash_on):
        super().__init__(responses, settings={"top_k": 4})
        self.crash_on = crash_on

    def query(self, question, **kw):
        if question == self.crash_on:
            raise Crash()
        return super().query(question, **kw)


def interrupted_run(tmp_path, crash_on="Do you take cats?"):
    adapter = CrashesAt(mock().responses, crash_on)
    with pytest.raises(Crash):
        runner.run_golden(make_golden(), adapter, out_dir=tmp_path)
    (partial,) = tmp_path.glob("*.partial.jsonl")
    return partial


def test_every_answer_is_on_disk_before_the_run_ends(tmp_path):
    partial = interrupted_run(tmp_path)
    header, records = runner.load_checkpoint(partial)
    assert header["golden"]["golden_version"] == "test-1.0.0"
    assert [r["item_id"] for r in records] == ["bath", "and-nails"]  # the two answered before the crash


def test_resume_asks_only_what_is_missing_and_matches_an_uninterrupted_run(tmp_path):
    partial = interrupted_run(tmp_path)
    adapter = mock()
    resumed = runner.run_golden(make_golden(), adapter, out_dir=tmp_path, resume_from=partial)
    assert [c["question"] for c in adapter.calls] == ["Do you take cats?"]
    straight = runner.run_golden(make_golden(), mock())
    assert resumed["records"] == straight["records"]
    assert resumed["run_id"] == runner.load_checkpoint(partial)[0]["run_id"]


def test_follow_up_after_a_resume_still_gets_its_parents_answer(tmp_path):
    partial = interrupted_run(tmp_path, crash_on="And nails?")  # crash after the parent, before the follow-up
    adapter = mock()
    runner.run_golden(make_golden(), adapter, out_dir=tmp_path, resume_from=partial)
    assert adapter.calls[0]["history"][1] == {"role": "assistant", "content": "A bath is $50."}


def test_saving_the_finished_run_removes_the_partial_file(tmp_path):
    partial = interrupted_run(tmp_path)
    run = runner.run_golden(make_golden(), mock(), out_dir=tmp_path, resume_from=partial)
    path = runner.save_run(run, tmp_path)
    assert path.exists() and not partial.exists()


def test_errors_are_kept_unless_retry_errors_is_given(tmp_path):
    flaky = mock()
    del flaky.responses["Do you take cats?"]
    runner.run_golden(make_golden(), flaky, out_dir=tmp_path)  # finishes, with one errored answer
    (partial,) = tmp_path.glob("*.partial.jsonl")

    kept = mock()
    run = runner.run_golden(make_golden(), kept, out_dir=tmp_path, resume_from=partial)
    assert kept.calls == [] and run["records"][2]["response"]["error"]

    retried = mock()
    run = runner.run_golden(make_golden(), retried, out_dir=tmp_path, resume_from=partial, retry_errors=True)
    assert [c["question"] for c in retried.calls] == ["Do you take cats?"]
    assert run["records"][2]["response"]["error"] is None
    assert [r["item_id"] for r in runner.load_checkpoint(partial)[1]] == ["bath", "and-nails", "cats"]  # no duplicates


def test_a_line_cut_short_by_a_crash_is_ignored(tmp_path):
    partial = interrupted_run(tmp_path)
    with open(partial, "a", encoding="utf-8") as f:
        f.write('{"record": {"item_id": "cats", "rep')  # the process died mid-write
    assert [r["item_id"] for r in runner.load_checkpoint(partial)[1]] == ["bath", "and-nails"]


def test_resume_refuses_a_changed_golden_set(tmp_path):
    partial = interrupted_run(tmp_path)
    changed = make_golden()
    changed["items"][2]["question"] = "Do you take dogs?"
    with pytest.raises(ValueError, match="golden set has changed"):
        runner.run_golden(changed, mock(), out_dir=tmp_path, resume_from=partial)


def test_resume_refuses_a_target_with_different_settings(tmp_path):
    partial = interrupted_run(tmp_path)
    other = mock()
    other.settings = {"top_k": 8}
    with pytest.raises(ValueError, match="settings differ"):
        runner.run_golden(make_golden(), other, out_dir=tmp_path, resume_from=partial)


def test_cli_run_needs_golden_and_target_unless_resuming(capsys):
    assert cli.main(["run"]) == 2
    assert "--golden and --target are required" in capsys.readouterr().out


def test_not_a_checkpoint_is_rejected(tmp_path):
    bogus = tmp_path / "x.partial.jsonl"
    bogus.write_text(json.dumps({"record": {}}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a CiteCheck partial run"):
        runner.load_checkpoint(bogus)

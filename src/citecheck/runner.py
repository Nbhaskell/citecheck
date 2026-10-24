"""`run`: ask the target every question in a golden set and save the raw responses. Nothing is scored here, so a run can
be scored again later (with different cut-offs, or a better metric) without asking the target anything.

A run file is plain JSON: who ran it (citecheck commit, Python), what was asked (golden-set version and a content hash),
what answered (the adapter's describe()), and one record per question and repeat.
"""
import hashlib
import json
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path

from . import __version__
from .adapters.base import AdapterError, TargetAdapter
from .models import TargetResponse

RUN_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]


def golden_hash(golden: dict) -> str:
    """Hash of the golden set's content, independent of whitespace and line endings in the file."""
    canonical = json.dumps(golden, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def git_state() -> dict:
    def git(*args):
        try:
            done = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def select_items(golden: dict, ids=None, splits=None) -> list[dict]:
    """Items to ask, in file order. A follow-up always brings its parent along, since its history comes from the
    parent's answer in the same run."""
    items = golden["items"]
    by_id = {i["id"]: i for i in items}
    wanted = {i["id"] for i in items
              if (not ids or i["id"] in ids) and (not splits or i["split"] in splits)}
    for item_id in list(wanted):
        parent = by_id[item_id].get("follow_up_to")
        if parent:
            wanted.add(parent)
    return [i for i in items if i["id"] in wanted]


CHECKPOINT_SUFFIX = ".partial.jsonl"


def _append_line(path: Path, obj: dict, mode: str = "a") -> None:
    with open(path, mode, encoding="utf-8", newline="\n") as f:  # closed every time, so a crash loses at most one answer
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_checkpoint(path) -> tuple[dict, list[dict]]:
    """(run header, records) from a partial run. A last line cut short by a crash is ignored."""
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    header, records = None, []
    for number, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if number == len(lines) - 1:
                break
            raise ValueError(f"{path}: line {number + 1} is not valid JSON")
        if "header" in obj:
            header = obj["header"]
        elif "record" in obj:
            records.append(obj["record"])
    if header is None:
        raise ValueError(f"{path} is not a CiteCheck partial run")
    return header, records


def run_golden(golden: dict, adapter: TargetAdapter, *, k: int | None = None, repeats: int = 1, ids=None, splits=None,
               label: str = "run", golden_path: str = "", progress=lambda message: None, out_dir=None,
               resume_from=None, retry_errors: bool = False) -> dict:
    """Ask the target every selected question, `repeats` times, and return the run.

    With out_dir, every answer is also appended to <out_dir>/<run id>.partial.jsonl as it arrives. After an
    interruption, pass that file as resume_from to ask only what is missing (retry_errors also asks again the
    questions that errored). A resumed run keeps the original settings; the golden set and the target must be the
    same as before, or the two halves would not be comparable.
    """
    describe = adapter.describe()  # first, so an unreachable target fails now and not after every question has errored
    done = []
    if resume_from:
        run, done = load_checkpoint(resume_from)
        if run["golden"]["hash"] != golden_hash(golden):
            raise ValueError("the golden set has changed since this run started")
        if run["target"]["describe"] != describe:
            raise ValueError("the target's settings differ from the interrupted run (pass the same --set values, "
                             f"and the same server): was {run['target']['describe']}, now {describe}")
        if retry_errors:
            done = [r for r in done if not r["response"]["error"]]
        config = run["config"]
        k, repeats = config["k"], config["repeats"]
        ids, splits = set(config["ids"] or ()) or None, set(config["splits"] or ()) or None
        checkpoint = Path(resume_from)
        _append_line(checkpoint, {"header": run}, "w")  # rewrite, so retried answers replace the errored ones
        for record in done:
            _append_line(checkpoint, {"record": record})
    else:
        created = datetime.now()
        safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") or "run"
        run = {
            "run_version": RUN_VERSION,
            "run_id": f"{created:%Y-%m-%d_%H%M%S}_{safe_label}",
            "label": label,
            "created": created.isoformat(timespec="seconds"),
            "citecheck": {"version": __version__, **git_state()},
            "python": platform.python_version(),
            "golden": {"path": golden_path, "golden_version": golden["golden_version"], "hash": golden_hash(golden)},
            "target": {"name": adapter.name, "describe": describe},
            "config": {"k": k, "repeats": repeats, "ids": sorted(ids) if ids else None,
                       "splits": sorted(splits) if splits else None},
        }
        checkpoint = None
        if out_dir:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            checkpoint = Path(out_dir) / f"{run['run_id']}{CHECKPOINT_SUFFIX}"
            _append_line(checkpoint, {"header": run}, "w")

    items = select_items(golden, ids, splits)
    if not items:
        raise ValueError("no questions selected")
    by_id = {i["id"]: i for i in items}
    finished = {(r["item_id"], r["repeat"]): r for r in done}
    records = []
    for repeat in range(1, repeats + 1):
        answers = {}  # item id -> its response in this repeat, for follow-up history
        for number, item in enumerate(items, 1):
            key = (item["id"], repeat)
            if key in finished:
                records.append(finished[key])
                answers[item["id"]] = TargetResponse.from_dict(finished[key]["response"])
                continue
            history, response = [], None
            parent = item.get("follow_up_to")
            if parent:
                parent_response = answers.get(parent)
                if parent_response is None or parent_response.error:
                    response = TargetResponse(error=f"not asked: its parent question {parent!r} has no answer")
                else:
                    history = [{"role": "user", "content": by_id[parent]["question"]},
                               {"role": "assistant", "content": parent_response.answer}]
            if response is None:
                try:
                    response = adapter.query(item["question"], history=history, k=k)
                except AdapterError as e:
                    response = TargetResponse(error=str(e))
            answers[item["id"]] = response
            record = {"item_id": item["id"], "repeat": repeat, "history": history, "response": response.to_dict()}
            records.append(record)
            if checkpoint:
                _append_line(checkpoint, {"record": record})
            status = f"ERROR {response.error}" if response.error else f"{len(response.retrieved)} passages"
            progress(f"[{repeat}/{repeats}] {number}/{len(items)} {item['id']}: {status}")

    return {**run, "records": records}


def save_run(run: dict, out_dir) -> Path:
    """Write the finished run, and remove its partial file."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run['run_id']}.run.json"
    path.write_text(json.dumps(run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (out_dir / f"{run['run_id']}{CHECKPOINT_SUFFIX}").unlink(missing_ok=True)
    return path

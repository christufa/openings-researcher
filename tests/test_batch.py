import json

import pytest

from openings_research.batch import plan, save, submit


@pytest.mark.parametrize("names", [[], [" "], ["Italian", " italian "], [None], "Italian", ["x"] * 51])
def test_invalid_batch(names):
    with pytest.raises(ValueError):
        plan(names, 1, "test")


def test_resume_after_ambiguous_submission_reuses_token(tmp_path):
    path = tmp_path / "batch.json"
    manifest = plan(["Italian Game", "French Defense"], 1, "test")
    save(path, manifest)
    submitted = {}
    interrupted = False

    def call(command, *args):
        nonlocal interrupted
        if command == "get":
            return {"settings": {"max_concurrent_runs": 1}}
        request = json.loads(args[1])
        assert request["queue"]["enabled"]
        token = request["idempotency_token"]
        submitted.setdefault(token, len(submitted) + 100)
        if not interrupted:
            interrupted = True
            raise TimeoutError("Response lost after server accepted run")
        return {"run_id": submitted[token]}

    with pytest.raises(TimeoutError):
        submit(manifest, path, call)
    restored = json.loads(path.read_text())
    submit(restored, path, call)
    submit(restored, path, call)
    assert len(submitted) == 2
    assert [r["run_id"] for r in restored["runs"]] == [100, 101]


def test_refuse_parallel_writer(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        submit(
            plan(["Italian Game"], 1, "test"),
            tmp_path / "batch.json",
            lambda *args: {"settings": {"max_concurrent_runs": 2}},
        )

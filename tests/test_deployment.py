from pathlib import Path

import pytest
import yaml

from openings_research.storage import identifier

ROOT = Path(__file__).resolve().parents[1]


def test_job_tasks_share_configuration_and_require_prior_stage():
    job = yaml.safe_load((ROOT / "resources/research_job.yml").read_text())["resources"]["jobs"][
        "openings_research"
    ]
    assert job["max_concurrent_runs"] == 1
    assert "schedule" not in job
    tasks = job["tasks"]
    for index, task in enumerate(tasks):
        assert (
            task["python_wheel_task"]["named_parameters"] == tasks[0]["python_wheel_task"]["named_parameters"]
        )
        if index:
            assert task["depends_on"] == [{"task_key": tasks[index - 1]["task_key"]}]


def test_one_schema_and_volume_artifacts():
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text())
    assert bundle["variables"]["schema"]["default"] == "openings_research"
    assert bundle["workspace"]["artifact_path"].startswith("/Volumes/")


@pytest.mark.parametrize("value", ["x; DROP TABLE y", "a.b", "x`", "a-b", ""])
def test_rejects_unsafe_sql_identifiers(value):
    with pytest.raises(ValueError):
        identifier(value)

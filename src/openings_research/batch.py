"""Submit bounded, resumable batches to the existing single-writer Databricks job."""

import argparse
import json
import subprocess
import uuid
from pathlib import Path


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def plan(openings, job_id, profile):
    if not isinstance(openings, list) or not 1 <= len(openings) <= 50:
        raise ValueError("Provide a JSON list of 1 to 50 opening names")
    if any(not isinstance(name, str) or not name.strip() for name in openings):
        raise ValueError("Opening names must be nonempty strings")
    names = [name.strip() for name in openings]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Duplicate opening names are not allowed")
    return {
        "batch_id": str(uuid.uuid4()),
        "job_id": job_id,
        "profile": profile,
        "parameters": {
            "mode": "refresh",
            "source_run_id": "",
            "agent": "openai",
            "model": "gpt-4.1-mini",
            "review_model": "gpt-4.1-mini",
        },
        "runs": [{"opening": name, "idempotency_token": str(uuid.uuid4())} for name in names],
    }


def submit(manifest, path, call):
    job = call("get", str(manifest["job_id"]))
    if job["settings"].get("max_concurrent_runs") != 1:
        raise ValueError("Batch requires the existing job to allow exactly one concurrent run")
    # Tokens are saved before the first API call; retry after an ambiguous response
    # returns the original run rather than launching duplicate paid research.
    for item in manifest["runs"]:
        if "run_id" in item:
            continue
        request = {
            "job_id": manifest["job_id"],
            "job_parameters": {**manifest["parameters"], "opening": item["opening"]},
            "idempotency_token": item["idempotency_token"],
            "queue": {"enabled": True},
        }
        result = call("run-now", "--json", json.dumps(request), "--no-wait")
        item["run_id"] = result["run_id"]
        save(path, manifest)
        print(json.dumps({"opening": item["opening"], "run_id": item["run_id"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "status"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--openings", type=Path)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--profile", default="brikt")
    parser.add_argument("--cli", default="databricks")
    args = parser.parse_args()
    if args.manifest.exists():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.openings or args.job_id:
            parser.error("For an existing manifest, omit --openings and --job-id; its saved scope is reused")
        if manifest["profile"] != args.profile:
            parser.error("Profile must match the saved manifest")
    else:
        if args.action != "submit" or not args.openings or not args.job_id:
            parser.error("A new submission requires --openings and --job-id")
        manifest = plan(json.loads(args.openings.read_text(encoding="utf-8")), args.job_id, args.profile)
        save(args.manifest, manifest)

    def call(*command):
        result = subprocess.run(
            [args.cli, "jobs", *command, "-p", args.profile, "-o", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=120,
        )
        return json.loads(result.stdout)

    if args.action == "submit":
        submit(manifest, args.manifest, call)
    else:
        for item in manifest["runs"]:
            if "run_id" not in item:
                print(json.dumps({"opening": item["opening"], "status": "not_submitted"}), flush=True)
                continue
            result = call("get-run", str(item["run_id"]))
            item["state"] = result["state"]
            item["url"] = result.get("run_page_url")
            save(args.manifest, manifest)
            print(
                json.dumps({"opening": item["opening"], "run_id": item["run_id"], **item["state"]}),
                flush=True,
            )


if __name__ == "__main__":
    main()

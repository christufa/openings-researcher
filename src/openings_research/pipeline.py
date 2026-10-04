"""Durable five-stage pipeline. Agents and collectors are replaceable boundaries."""

import json
from collections import Counter
from datetime import datetime, timezone

from . import __version__
from .agents import PROMPT_VERSION, SYSTEM_PROMPT
from .contracts import (
    CONTRACT_VERSION,
    AgentOutput,
    ClaimCandidate,
    LineCandidate,
    ResearchInput,
    Source,
    stable_id,
)
from .coverage import COVERAGE_VERSION, coverage_report, gap_records
from .evidence import EVIDENCE_INDEX_VERSION
from .review import REVIEW_PROMPT, REVIEW_VERSION, ReviewOutput, validate_reviews
from .taxonomy import TAXONOMY_VERSION
from .validation import validate_candidate

STAGES = ["collect", "extract", "validate", "review", "publish"]
VALIDATOR_VERSION = "legal-moves-exact-evidence-v1"


class NoValidCandidatesError(ValueError):
    """Nothing can be published; inspect persisted validation results."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Pipeline:
    def __init__(self, store, run_id: str, config: dict):
        self.store = store
        self.run_id = run_id
        self.config = config
        self.opening_id = stable_id("opening-name-v1", config["opening"].strip().casefold())

    def execute(self, stage: str, collector=None, agent=None, reviewer=None):
        if stage not in STAGES:
            raise ValueError("Unknown stage")
        config_json = json.dumps(self.config, sort_keys=True)
        runs = self.store.read("research_runs", run_id=self.run_id)
        if runs:
            run = runs[0]
            if run["config_json"] != config_json:
                raise ValueError("Run configuration changed; use a new run ID")
        else:
            if stage != "collect":
                raise ValueError("Collect must initialize the run")
            run = {
                "run_id": self.run_id,
                "opening_id": self.opening_id,
                "opening": self.config["opening"],
                "config_json": config_json,
                "status": "running",
                "created_at": now(),
                "completed_at": None,
            }
            self.store.upsert("research_runs", [run])
        task_id = stable_id(self.run_id, stage)
        previous = self.store.read("research_tasks", task_id=task_id)
        if previous and previous[0]["status"] == "completed":
            return
        if stage != "collect":
            dependency = self.store.read(
                "research_tasks", task_id=stable_id(self.run_id, STAGES[STAGES.index(stage) - 1])
            )
            if not dependency or dependency[0]["status"] != "completed":
                raise ValueError("Previous stage has not completed")
        task = {
            "task_id": task_id,
            "run_id": self.run_id,
            "stage": stage,
            "status": "running",
            "error_type": None,
            "updated_at": now(),
        }
        self.store.upsert("research_tasks", [task])
        try:
            if stage == "collect":
                self.collect(collector)
            elif stage == "extract":
                self.extract(agent)
            elif stage == "validate":
                self.validate()
            elif stage == "review":
                self.review(reviewer)
            else:
                self.publish()
            if stage == "publish":
                # Last write to publish a run. Readers use completed-run views.
                run.update(status="completed", completed_at=now())
            else:
                run["status"] = "running"
            self.store.upsert("research_runs", [run])
            task.update(status="completed", updated_at=now())
            self.store.upsert("research_tasks", [task])
        except Exception as exc:
            task.update(status="failed", error_type=type(exc).__name__, updated_at=now())
            self.store.upsert("research_tasks", [task])
            # Do not demote an already published run if only its task marker failed.
            if run["status"] != "completed":
                run["status"] = "failed"
                self.store.upsert("research_runs", [run])
            raise

    def collect(self, collector):
        if self.config["mode"] == "reextract":
            parent = self.store.read("research_runs", run_id=self.config["source_run_id"])
            if not parent or parent[0]["opening_id"] != self.opening_id:
                raise ValueError("Source run is missing or belongs to a different opening")
            completed = self.store.read(
                "research_tasks", task_id=stable_id(self.config["source_run_id"], "collect")
            )
            if not completed or completed[0]["status"] != "completed":
                raise ValueError("Source run collection is incomplete")
            sources = self.store.sources_for_run(self.config["source_run_id"])
        else:
            documents = collector.collect(self.config["opening"])
            sources = []
            for document in documents:
                source_id = stable_id(document["url"])
                content_hash = stable_id(document["content"])
                version_id = stable_id(self.run_id, source_id, document["title"], content_hash)
                self.store.upsert("sources", [{"source_id": source_id, "url": document["url"]}])
                self.store.upsert(
                    "source_versions",
                    [
                        {
                            "source_version_id": version_id,
                            "source_id": source_id,
                            "title": document["title"],
                            "content": document["content"],
                            "content_hash": content_hash,
                            "retrieved_at": document["retrieved_at"],
                        }
                    ],
                )
                sources.append({"source_version_id": version_id})
        if not sources:
            raise ValueError("No usable sources collected")
        self.store.upsert(
            "run_sources",
            [
                {
                    "link_id": stable_id(self.run_id, s["source_version_id"]),
                    "run_id": self.run_id,
                    "source_version_id": s["source_version_id"],
                }
                for s in sources
            ],
        )

    def extract(self, agent):
        cached = self.store.read("agent_outputs", run_id=self.run_id)
        if cached:
            output = AgentOutput.model_validate_json(cached[0]["output_json"])
        else:
            prior_id = self.config.get("source_run_id")
            previous = self.store.read("claims", run_id=prior_id) if prior_id else []
            reports = self.store.read("coverage_reports", run_id=prior_id) if prior_id else []
            gaps = json.loads(reports[0]["report_json"])["gaps"] if reports else []
            request = ResearchInput(
                opening=self.config["opening"],
                sources=self.sources(),
                existing_claims=[c["text"] for c in previous],
                coverage_gaps=[f"{g['side']} {g['topic']}: {g['reason']}" for g in gaps],
            )
            result = agent.extract(request)
            output = AgentOutput.model_validate(result.output)
            self.store.upsert(
                "agent_outputs",
                [
                    {
                        "run_id": self.run_id,
                        "output_json": output.model_dump_json(),
                        "raw_response": result.raw_response,
                        "usage_json": result.usage_json,
                        "created_at": now(),
                    }
                ],
            )
        candidates = []
        for kind, items in [("line", output.lines), ("claim", output.claims)]:
            for item in items:
                payload = item.model_dump_json()
                candidates.append(
                    {
                        "candidate_id": stable_id(self.run_id, kind, payload),
                        "run_id": self.run_id,
                        "kind": kind,
                        "payload_json": payload,
                    }
                )
        if not candidates:
            raise ValueError("Agent returned no candidates; inspect unresolved questions")
        self.store.upsert("candidate_records", candidates)
        print(
            json.dumps(
                {
                    "event": "extraction_summary",
                    "run_id": self.run_id,
                    "lines": len(output.lines),
                    "claims": len(output.claims),
                    "unresolved_questions": len(output.unresolved_questions),
                }
            ),
            flush=True,
        )

    def sources(self) -> list[Source]:
        return [Source.model_validate(s) for s in self.store.sources_for_run(self.run_id)]

    def validate(self):
        sources = self.sources()
        results = []
        for record in self.store.read("candidate_records", run_id=self.run_id):
            result = {
                "candidate_id": record["candidate_id"],
                "run_id": self.run_id,
                "valid": False,
                "reason": None,
                "normalized_json": "{}",
                "validator_version": VALIDATOR_VERSION,
            }
            try:
                cls = LineCandidate if record["kind"] == "line" else ClaimCandidate
                normalized = validate_candidate(cls.model_validate_json(record["payload_json"]), sources)
                result.update(valid=True, normalized_json=json.dumps(normalized))
            except ValueError as exc:
                # Validation errors contain source/notation data, not provider credentials.
                result["reason"] = str(exc)[:1000]
            results.append(result)
        self.store.upsert("validation_results", results)
        valid = sum(r["valid"] for r in results)
        print(
            json.dumps(
                {
                    "event": "validation_summary",
                    "run_id": self.run_id,
                    "valid": valid,
                    "rejected": len(results) - valid,
                }
            ),
            flush=True,
        )

    def review(self, reviewer):
        valid = {
            r["candidate_id"] for r in self.store.read("validation_results", run_id=self.run_id) if r["valid"]
        }
        candidates = [
            c for c in self.store.read("candidate_records", run_id=self.run_id) if c["candidate_id"] in valid
        ]
        cached = self.store.read("review_outputs", run_id=self.run_id)
        if cached:
            output = ReviewOutput.model_validate_json(cached[0]["output_json"])
        elif candidates:
            result = reviewer.review(
                self.config["opening"], candidates, {s.source_version_id: s.url for s in self.sources()}
            )
            output = ReviewOutput.model_validate(result.output)
            self.store.upsert(
                "review_outputs",
                [
                    {
                        "run_id": self.run_id,
                        "output_json": output.model_dump_json(),
                        "raw_response": result.raw_response,
                        "usage_json": result.usage_json,
                        "created_at": now(),
                    }
                ],
            )
        else:
            output = ReviewOutput(reviews=[])
        validate_reviews(output, candidates)
        self.store.upsert(
            "candidate_reviews",
            [
                {**r.model_dump(), "run_id": self.run_id, "reviewer_version": REVIEW_VERSION}
                for r in output.reviews
            ],
        )
        print(
            json.dumps(
                {
                    "event": "review_summary",
                    "run_id": self.run_id,
                    "decisions": dict(Counter(r.decision for r in output.reviews)),
                }
            ),
            flush=True,
        )

    def publish(self):
        candidates = {r["candidate_id"]: r for r in self.store.read("candidate_records", run_id=self.run_id)}
        results = self.store.read("validation_results", run_id=self.run_id)
        if set(candidates) != {r["candidate_id"] for r in results}:
            raise ValueError("Validation does not cover the entire candidate batch")
        valid = [r for r in results if r["valid"]]
        reviews = self.store.read("candidate_reviews", run_id=self.run_id)
        output = ReviewOutput.model_validate(
            {
                "reviews": [
                    {k: r[k] for k in ("candidate_id", "decision", "category", "rationale")} for r in reviews
                ]
            }
        )
        validate_reviews(output, [candidates[r["candidate_id"]] for r in valid])
        by_id = {r["candidate_id"]: r for r in reviews}
        accepted = [r for r in valid if by_id[r["candidate_id"]]["decision"] == "accept"]
        if not accepted:
            raise NoValidCandidatesError(
                "No candidates passed validation and review; previous published run remains current"
            )
        self.store.upsert("openings", [{"opening_id": self.opening_id, "name": self.config["opening"]}])
        batches = {
            name: []
            for name in ["positions", "position_moves", "lines", "opening_lines", "claims", "claim_evidence"]
        }
        for result in accepted:
            record = candidates[result["candidate_id"]]
            payload = json.loads(record["payload_json"])
            normalized = json.loads(result["normalized_json"])
            common = {
                "run_id": self.run_id,
                "opening_id": self.opening_id,
                "candidate_id": record["candidate_id"],
                "review_status": "fixture_reviewed"
                if self.config["agent"] == "fixture"
                else "model_reviewed",
            }
            if record["kind"] == "line":
                batches["positions"].extend(normalized["positions"])
                batches["position_moves"].extend(normalized["moves"])
                batches["lines"].append(
                    {
                        "line_id": normalized["line_id"],
                        "start_position_id": normalized["positions"][0]["position_id"],
                        "end_position_id": normalized["positions"][-1]["position_id"],
                        "moves_uci": normalized["moves_uci"],
                    }
                )
                batches["opening_lines"].append(
                    {
                        **common,
                        "record_id": record["candidate_id"],
                        "line_id": normalized["line_id"],
                        "name": payload["name"],
                    }
                )
            else:
                position = normalized["position"]
                if position:
                    batches["positions"].append(position)
                batches["claims"].append(
                    {
                        **common,
                        "record_id": record["candidate_id"],
                        "claim_id": stable_id(
                            self.opening_id,
                            payload["text"],
                            by_id[record["candidate_id"]]["category"],
                            payload["side"],
                            position,
                        ),
                        "text": payload["text"],
                        "category": by_id[record["candidate_id"]]["category"],
                        "side": payload["side"],
                        "position_id": position["position_id"] if position else None,
                    }
                )
            for evidence in payload["evidence"]:
                batches["claim_evidence"].append(
                    {
                        **evidence,
                        "run_id": self.run_id,
                        "candidate_id": record["candidate_id"],
                        "evidence_id": stable_id(record["candidate_id"], evidence),
                    }
                )
        for table, rows in batches.items():
            self.store.upsert(table, rows)
        report = coverage_report(
            self.config["opening"],
            batches["claims"],
            batches["opening_lines"],
            batches["claim_evidence"],
            self.sources(),
            {"valid": len(valid), "rejected": len(results) - len(valid)},
            dict(Counter(r["decision"] for r in reviews)),
        )
        self.store.upsert(
            "coverage_reports",
            [
                {
                    "run_id": self.run_id,
                    "opening_id": self.opening_id,
                    "report_json": json.dumps(report),
                    "created_at": now(),
                }
            ],
        )
        self.store.upsert("research_gaps", gap_records(self.run_id, self.opening_id, report))
        print(
            json.dumps(
                {
                    "event": "coverage_summary",
                    "run_id": self.run_id,
                    "published_claims": report["published_claims"],
                    "published_lines": report["published_lines"],
                    "gaps": len(report["gaps"]),
                }
            ),
            flush=True,
        )


def provenance_config(**kwargs) -> dict:
    return {
        **kwargs,
        "package_version": __version__,
        "contract_version": CONTRACT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": stable_id(SYSTEM_PROMPT),
        "evidence_index_version": EVIDENCE_INDEX_VERSION,
        "reviewer_version": REVIEW_VERSION,
        "review_prompt_hash": stable_id(REVIEW_PROMPT),
        "taxonomy_version": TAXONOMY_VERSION,
        "coverage_version": COVERAGE_VERSION,
        "validator_version": VALIDATOR_VERSION,
    }

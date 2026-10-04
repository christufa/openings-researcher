"""Databricks wheel entry points. Secrets are fetched only for the stage needing them."""

import argparse
import json
import os

from .agents import make_agent
from .collectors import FixtureCollector, TavilyCollector
from .pipeline import Pipeline, provenance_config
from .review import make_reviewer
from .storage import DeltaStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--catalog", default="brikt")
    result.add_argument("--schema", default="openings_research")
    result.add_argument("--run-id", required=True)
    result.add_argument("--opening", default="Italian Game")
    result.add_argument("--mode", choices=["refresh", "reextract"], default="refresh")
    result.add_argument("--source-run-id", default="")
    result.add_argument("--agent", choices=["openai", "fixture"], default="openai")
    result.add_argument("--model", default="gpt-4.1-mini")
    result.add_argument("--review-model", default="gpt-4.1-mini")
    result.add_argument("--secret-scope", default="openings_research")
    result.add_argument("--code-version", default="local")
    return result


def run(stage: str):
    args = parser().parse_args()
    if args.mode == "reextract" and (not args.source_run_id or args.source_run_id == args.run_id):
        raise ValueError("Re-extraction requires a different source run ID")
    if args.agent == "fixture" and args.opening != "__smoke_italian__":
        raise ValueError("Fixture adapter requires opening=__smoke_italian__")
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    store = DeltaStore(spark, args.catalog, args.schema)
    store.bootstrap()
    config = provenance_config(
        opening=args.opening,
        mode=args.mode,
        source_run_id=args.source_run_id,
        agent=args.agent,
        model=args.model,
        review_model=args.review_model,
        code_version=args.code_version,
    )
    pipeline = Pipeline(store, args.run_id, config)

    def secret(key: str, env_name: str) -> str:
        if os.getenv(env_name):
            return os.environ[env_name]
        from pyspark.dbutils import DBUtils

        return DBUtils(spark).secrets.get(scope=args.secret_scope, key=key)

    collector = agent = None

    # Construct clients lazily inside the stage, after cached-completion checks.
    class LazyCollector:
        def collect(self, opening):
            instance = (
                FixtureCollector()
                if args.agent == "fixture"
                else TavilyCollector(secret("tavily-api-key", "TAVILY_API_KEY"), store, args.run_id)
            )
            return instance.collect(opening)

    class LazyAgent:
        def extract(self, request):
            return make_agent(
                args.agent,
                args.model,
                secret("openai-api-key", "OPENAI_API_KEY") if args.agent == "openai" else "",
            ).extract(request)

    class LazyReviewer:
        def review(self, opening, candidates, source_urls):
            return make_reviewer(
                args.agent,
                args.review_model,
                secret("openai-api-key", "OPENAI_API_KEY") if args.agent == "openai" else "",
            ).review(opening, candidates, source_urls)

    collector, agent = LazyCollector(), LazyAgent()
    print(json.dumps({"event": "stage_started", "stage": stage, "run_id": args.run_id}), flush=True)
    try:
        pipeline.execute(stage, collector=collector, agent=agent, reviewer=LazyReviewer())
    except Exception as exc:
        # Provider exception text may contain request data; emit only the type.
        print(
            json.dumps(
                {
                    "event": "stage_failed",
                    "stage": stage,
                    "run_id": args.run_id,
                    "error_type": type(exc).__name__,
                }
            ),
            flush=True,
        )
        raise RuntimeError(
            f"{stage} failed ({type(exc).__name__}); inspect research_tasks and validation_results"
        ) from None
    print(json.dumps({"event": "stage_completed", "stage": stage, "run_id": args.run_id}), flush=True)


def collect():
    run("collect")


def extract():
    run("extract")


def validate():
    run("validate")


def publish():
    run("publish")


def review():
    run("review")

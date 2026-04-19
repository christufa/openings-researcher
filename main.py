import argparse
import json
import logging
import re
import time
from pathlib import Path
from agent import OpeningResearchAgent


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def collect_all(
    openings_file: str,
    data_dir: Path,
    request_delay: float,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)

    with open(openings_file) as f:
        openings: list[str] = json.load(f)

    log = logging.getLogger(__name__)
    log.info(f"Loaded {len(openings)} openings from {openings_file}")
    log.info(f"Output directory: {data_dir.resolve()}")

    agent = OpeningResearchAgent(request_delay=request_delay)
    summary: dict = {"completed": [], "skipped": [], "failed": []}

    for i, opening in enumerate(openings, 1):
        slug = slugify(opening)
        out_path = data_dir / f"{slug}.json"

        if out_path.exists():
            log.info(f"[{i}/{len(openings)}] Skipping (exists): {opening}")
            summary["skipped"].append(opening)
            continue

        log.info(f"[{i}/{len(openings)}] Researching: {opening}")
        try:
            result = agent.run(opening)
            result["_meta"] = {"opening": opening, "slug": slug}
            out_path.write_text(json.dumps(result, indent=2))
            log.info(f"  Saved → {out_path}")
            summary["completed"].append(opening)
        except Exception as e:
            log.error(f"  Failed: {opening} — {e}")
            summary["failed"].append({"opening": opening, "error": str(e)})

        time.sleep(request_delay)

    manifest_path = data_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(summary, indent=2))
    log.info(
        f"Done. completed={len(summary['completed'])} "
        f"skipped={len(summary['skipped'])} "
        f"failed={len(summary['failed'])}"
    )
    return summary


def research_one(opening: str, data_dir: Path, request_delay: float) -> None:
    log = logging.getLogger(__name__)
    data_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(opening)
    out_path = data_dir / f"{slug}.json"

    agent = OpeningResearchAgent(request_delay=request_delay)
    log.info(f"Researching: {opening}")
    result = agent.run(opening)
    result["_meta"] = {"opening": opening, "slug": slug}
    out_path.write_text(json.dumps(result, indent=2))
    log.info(f"Saved → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research chess openings and generate structured coaching reports."
    )
    parser.add_argument(
        "--opening",
        metavar="NAME",
        help="Research a single opening by name (skips --openings-file).",
    )
    parser.add_argument(
        "--openings-file",
        default="openings.json",
        metavar="PATH",
        help="JSON file containing a list of opening names (default: openings.json).",
    )
    parser.add_argument(
        "--data-dir",
        default="./data",
        metavar="PATH",
        help="Directory where output JSON files are saved (default: ./data).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds to wait between openings (default: 1.0).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    data_dir = Path(args.data_dir)

    if args.opening:
        research_one(args.opening, data_dir, args.request_delay)
    else:
        collect_all(args.openings_file, data_dir, args.request_delay)


if __name__ == "__main__":
    main()

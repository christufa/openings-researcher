# Openings Researcher

A replayable opening-research pipeline deployed to Databricks from GitHub.
All Delta tables live in **`brikt.openings_research`** (catalog and schema are configurable).
Agents produce candidates; the pipeline owns source snapshots, chess validation,
publication, and run history. Games remain in the separate Lichess pipeline.

```text
Tavily or saved sources -> collect -> extract -> validate -> publish
                                      |            |          |
                              replaceable agent  checks   Delta views
```

## What works

- Four serverless wheel tasks, with retries and durable stage markers.
- Tavily searches across three topics, deduplicates URLs, and extracts up to six
  documents. Raw responses (including extraction failures) are retained. The agent
  sees up to 10,000 characters per document; the saved source version is that exact
  excerpt, while the raw response retains the full returned text.
- An OpenAI structured-output adapter (configurable model, default `gpt-4.1-mini`)
  extracts move sequences, plans, pawn breaks, maneuvers, tactics and assessments.
  It selects numbered source passages; the pipeline copies their original text
  into evidence records. The model does not generate evidence quotations.
- A credential-free fixture adapter exercises the same contracts and tables.
- Legal-move, FEN, source-reference and exact-excerpt validation. Rejected
  candidates remain inspectable; prose semantics are **unreviewed**, not verified.
- Re-extraction using another model against the exact same saved sources.
- Stable chess entity IDs, idempotent merges, history per run, and current views
  that select only completed publication batches.

## Repository layout

| Location | Purpose |
| --- | --- |
| `src/openings_research/contracts.py` | Versioned Pydantic input/output and position identity |
| `agents.py` | Agent protocol, OpenAI adapter and smoke adapter |
| `evidence.py` | Deterministic passage catalog and source-reference resolution |
| `collectors.py` | Tavily discovery/extraction and request caching |
| `pipeline.py` | Agent-independent orchestration and repair logic |
| `validation.py` | Deterministic chess and evidence checks |
| `schema.py`, `storage.py` | Explicit Delta schemas, merges and views |
| `cli.py` | Installed Databricks wheel entry points |
| `resources/research_job.yml` | Four-task serverless job |
| `.github/workflows/databricks.yml` | Public-repository CI and develop deployment |
| `tests/` | Identity, evidence, replay, failure recovery and deployment checks |

The original root-level scripts and notebook remain as the legacy report tool;
they are not imported by the deployed wheel. See [legacy usage](docs/legacy-reports.md).

## Tables and publication

All tables and views use one schema, `openings_research`:

| Tables | Grain / purpose |
| --- | --- |
| `research_runs`, `research_tasks` | Run configuration and stage status |
| `raw_responses` | Cached provider response per request per run |
| `sources`, `source_versions`, `run_sources` | URL identity, captured text and run membership |
| `agent_outputs` | Original structured response, parsed output and token usage |
| `candidate_records`, `validation_results` | Proposed records and mechanical checks |
| `openings` | Requested opening identity, normalized by trimmed case-folded name |
| `positions`, `position_moves` | Canonical chess graph |
| `lines`, `opening_lines` | Ordered UCI sequences and named opening associations |
| `claims`, `claim_evidence` | Assertions and source evidence (also used for line candidates) |

Use `current_claims` and `current_lines`, which join `latest_completed_runs`.
Each completed run is a replacement snapshot for that requested opening, not an
incremental union of every historical claim. Compare runs before treating a new
agent as an improvement. Accepted here means mechanically valid; every published
claim and line association has `review_status = 'unreviewed'`.

Publication writes all entity tables before marking the run completed. Delta
transactions are table-scoped; the completed-run view is the publication boundary.
Direct reads of base tables can include partial/unpublished records. An interrupted
publish can be repaired without duplicate keys. No valid candidates means a failed
run, leaving the previous completed run current. Some rejected candidates do not
prevent publishing valid ones; inspect `validation_results` for partial coverage.

Only this job should write these tables. It allows one concurrent run. Do not
deploy another writer into the same schema. Schema changes require explicit
migrations; `CREATE TABLE IF NOT EXISTS` does not migrate existing tables.

## Databricks setup

Requires Unity Catalog, serverless jobs, outbound access to PyPI/Tavily/OpenAI,
and a deployment/job identity with schema, volume and table privileges.

1. Authenticate: `databricks auth login --host https://YOUR_WORKSPACE`.
2. Bootstrap the artifact volume before deployment (wheel upload precedes tasks):

   ```sh
   databricks schemas create openings_research brikt
   databricks volumes create brikt openings_research artifacts MANAGED
   ```

3. Store API keys using the interactive prompts; never put them in Git or job parameters:

   ```sh
   databricks secrets create-scope openings_research
   databricks secrets put-secret openings_research tavily-api-key
   databricks secrets put-secret openings_research openai-api-key
   ```

4. Install/build and deploy:

   ```sh
   python -m pip install -r requirements-dev.txt
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   ```

The bundle uploads a versioned wheel under the schema's `artifacts` volume,
following the neighboring Lichess project. There is no automatic research schedule.
Deploying creates/updates the job; it does not start paid API research.

## Run and rerun

Credential-free smoke run (writes a separate `__smoke_italian__` opening):

```sh
databricks bundle run -t dev openings_research --params 'agent=fixture,opening=__smoke_italian__'
```

Collect new web sources and research an opening:

```sh
databricks bundle run -t dev openings_research --params 'opening=Italian Game'
```

Use the original Databricks job run ID to extract again from saved sources:

```sh
databricks bundle run -t dev openings_research --params 'opening=Italian Game,mode=reextract,source_run_id=123456,model=gpt-4.1-mini'
```

Choose a different supported model to compare it; a new run ID preserves both
results. Source reuse requires the same requested opening identity and a completed
collection stage. It does not require the original extraction to have succeeded.
Use Databricks **Repair run** for unchanged failed tasks. Changing agent/model,
prompt or code configuration requires a new run instead of repairing the old one.

Requests are cached after their responses are committed. An interruption between
a remote API response and the cache write can repeat that paid request. Collection
is bounded to three searches and one batch extract per fresh run; extraction uses
one model call capped at 8,000 output tokens (provider/task retries can add calls).
There is no dollar-budget enforcement yet. Token usage is recorded when returned.

## GitHub deployment

PRs and pushes to `main`/`develop` run lint, tests and wheel builds. Successful
pushes to **`develop`** deploy the dev bundle. Main currently runs checks only.
PR jobs cannot access deployment secrets. Actions are pinned to commit SHAs.

Configure the `databricks-dev` GitHub environment, restricted to `develop`, with:

- Variable `DATABRICKS_HOST` (workspace URL).
- Variable `DATABRICKS_DEPLOY_USER` (the identity owning this dev deployment).
- Secret `DATABRICKS_TOKEN` (dedicated deployment PAT; rotate before expiration).

The workflow checks deployment identity, serializes deployments, uses bundle
locking, and refuses deployment during an active job. Git commit SHA is recorded
as `code_version`. Model API keys stay in Databricks Secrets, not GitHub.

The initial workspace schema, artifact volume, API secret scope and GitHub
environment were provisioned on October 3, 2026. The dedicated deployment token
expires January 1, 2027 at 20:08 UTC; rotate the GitHub environment secret before
then. No token values are stored in this repository.

## Position identity / games integration

`position_id` is SHA-256 over a canonical JSON encoding of the identity version
and normalized FEN. Normalized FEN includes piece placement, side to move,
castling rights and **legally available** en passant; move counters are excluded.
The current identity version is `standard-legal-ep-v1`. Only standard chess is
supported. Lines preserve ordered UCI moves separately, so transpositions share
positions without collapsing distinct move orders. Full game history is still
needed for repetition and fifty-move-rule state.

Use the same `position_record()` function when deriving position IDs from the
Lichess games' FENs. This project does not modify or reingest that dataset.

## Adding an agent

Implement `ResearchAgent.extract(ResearchInput) -> Extraction` and register it in
`make_agent()` and the CLI's agent choices. Return `AgentOutput` candidates with
source-version IDs and exact excerpts. Adapters must not write core tables.
Agent configuration, contract/prompt/validator versions and code SHA are recorded
with each run. To add another source type, implement the collector's `collect()`
interface and retain source snapshots. Keep API calls on the driver, outside Spark
UDFs, so Spark task retries cannot silently multiply provider requests.

The OpenAI adapter uses an internal reference schema whose allowed passage IDs
are enumerated for each request. It divides source text into chunks of at most
1,200 characters, preferring paragraph/newline boundaries, and preserves Markdown,
Unicode punctuation and whitespace exactly. Source order is deterministic. A
request with more than 500 passages fails explicitly and must be split rather
than silently losing coverage. Blank sources are ignored.

The adapter resolves passage IDs to the existing `AgentOutput` evidence format;
the public contract and Delta table schemas are unchanged. `agent_outputs.raw_response`
now contains a JSON envelope with the original provider response, the evidence-index
version, and passage-to-source offsets (Unicode character offsets, end exclusive).
Old runs retain their original response format. Unknown references fail closed.
The validator still checks exact source membership and legal moves. A matching
passage is traceable evidence, not proof that it supports every assertion; semantic
review remains separate and published records remain `unreviewed`.

Task output includes `extraction_summary` and `validation_summary` with candidate
and rejection counts. An all-rejected batch fails publication with
`NoValidCandidatesError`. To retry a failed extraction with the updated prompt,
start a **new reextract run** pointing at the original source run; do not repair
the old run with a changed code/prompt configuration.

## Tests and next steps

```sh
python -m ruff check src tests
python -m pytest -q
python -m build --wheel
```

Local tests use an in-memory store to exercise orchestration; a deployed fixture
run verifies actual Spark/Delta execution, permissions and wheel installation.
Live Tavily/OpenAI research additionally requires working provider credentials.

This is the first usable foundation. Explicit opening aliases/ECO imports,
structured-dataset collectors, semantic evidence review, engine analysis,
coverage-driven task planning, report generation and run-comparison UI remain
future work. Existing knowledge is represented in the agent contract but is not
yet populated automatically. No claims of comprehensive opening coverage are made.

References: [Databricks wheel bundles](https://docs.databricks.com/aws/en/dev-tools/bundles/python-wheel),
[Delta merge](https://docs.databricks.com/aws/en/delta/merge),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract).

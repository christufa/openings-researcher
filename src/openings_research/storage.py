"""Small, bounded research batches; Spark handles Delta persistence, not API calls."""

import re

from .schema import KEYS, TABLES


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Catalog/schema identifiers must contain only letters, digits and underscores")
    return value


class DeltaStore:
    def __init__(self, spark, catalog: str, schema: str):
        self.spark = spark
        self.namespace = f"{identifier(catalog)}.{identifier(schema)}"

    def table(self, name: str) -> str:
        if name not in TABLES:
            raise ValueError("Unknown table")
        return f"{self.namespace}.{name}"

    def bootstrap(self):
        self.spark.sql(f"CREATE SCHEMA IF NOT EXISTS {self.namespace}")
        for name, ddl in TABLES.items():
            self.spark.sql(f"CREATE TABLE IF NOT EXISTS {self.table(name)} ({ddl}) USING DELTA")
        self.spark.sql(f"""CREATE OR REPLACE VIEW {self.namespace}.latest_completed_runs AS
            SELECT * EXCEPT (rn) FROM (
              SELECT *, row_number() OVER (
                PARTITION BY opening_id ORDER BY completed_at DESC, run_id DESC
              ) rn FROM {self.table("research_runs")} WHERE status = 'completed'
            ) WHERE rn = 1""")
        for table, view in [("claims", "current_claims"), ("opening_lines", "current_lines")]:
            self.spark.sql(f"""CREATE OR REPLACE VIEW {self.namespace}.{view} AS
                SELECT data.* FROM {self.table(table)} data
                JOIN {self.namespace}.latest_completed_runs runs ON data.run_id = runs.run_id""")

    def upsert(self, name: str, rows: list[dict]):
        if not rows:
            return
        from delta.tables import DeltaTable

        key = KEYS[name]
        unique = {}
        for row in rows:
            if row[key] in unique and unique[row[key]] != row:
                raise ValueError(f"Conflicting duplicate key in {name}")
            unique[row[key]] = row
        frame = self.spark.createDataFrame(list(unique.values()), schema=TABLES[name])
        (
            DeltaTable.forName(self.spark, self.table(name))
            .alias("target")
            .merge(frame.alias("source"), f"target.{key} = source.{key}")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )

    def read(self, name: str, **filters) -> list[dict]:
        from pyspark.sql import functions as F

        frame = self.spark.table(self.table(name))
        for key, value in filters.items():
            frame = frame.where(F.col(key) == F.lit(value))
        # Research batches are bounded by the collector; never use this for games.
        return [row.asDict(recursive=True) for row in frame.collect()]

    def sources_for_run(self, run_id: str) -> list[dict]:
        from pyspark.sql import functions as F

        links = self.spark.table(self.table("run_sources")).where(F.col("run_id") == F.lit(run_id))
        versions = self.spark.table(self.table("source_versions"))
        sources = self.spark.table(self.table("sources"))
        return [
            r.asDict()
            for r in links.join(versions, "source_version_id")
            .join(sources, "source_id")
            .select("source_version_id", "url", "title", "content")
            .collect()
        ]

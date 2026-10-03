"""Bounded collection with durable request caching, outside Spark executors."""

import json

from .contracts import stable_id
from .pipeline import now

FIXTURE_CONTENT = "Italian Game: 1. e4 e5 2. Nf3 Nc6 3. Bc4. White develops the bishop to c4."


class FixtureCollector:
    def collect(self, opening: str) -> list[dict]:
        if opening != "__smoke_italian__":
            raise ValueError("Fixture collection requires the isolated __smoke_italian__ target")
        return [
            {
                "url": "fixture://italian-v1",
                "title": "Authored smoke fixture",
                "content": FIXTURE_CONTENT,
                "retrieved_at": "2026-01-01T00:00:00+00:00",
            }
        ]


class TavilyCollector:
    def __init__(self, api_key: str, store, run_id: str):
        from tavily import TavilyClient

        self.client = TavilyClient(api_key=api_key)
        self.store = store
        self.run_id = run_id

    def request(self, method: str, **kwargs) -> tuple[dict, str]:
        request = json.dumps({"method": method, **kwargs}, sort_keys=True)
        response_id = stable_id(self.run_id, request)
        cached = self.store.read("raw_responses", response_id=response_id)
        if cached:
            return json.loads(cached[0]["response_json"]), cached[0]["created_at"]
        response = getattr(self.client, method)(**kwargs)
        timestamp = now()
        self.store.upsert(
            "raw_responses",
            [
                {
                    "response_id": response_id,
                    "run_id": self.run_id,
                    "provider": "tavily",
                    "request_json": request,
                    "response_json": json.dumps(response),
                    "created_at": timestamp,
                }
            ],
        )
        return response, timestamp

    def collect(self, opening: str) -> list[dict]:
        # Round-robin selection gives each topic room; no early-topic truncation.
        groups = []
        for topic in ["main lines move orders", "plans pawn breaks", "tactics mistakes"]:
            response, _ = self.request(
                "search",
                query=f"{opening} chess {topic}",
                search_depth="advanced",
                max_results=3,
                include_answer=False,
            )
            groups.append(response.get("results", []))
        selected = {}
        for index in range(3):
            for group in groups:
                if index < len(group):
                    item = group[index]
                    if item.get("url", "").startswith(("http://", "https://")):
                        selected.setdefault(item["url"], item)
        urls = list(selected)[:6]
        if not urls:
            return []
        response, retrieved = self.request("extract", urls=urls, extract_depth="advanced")
        documents = []
        for result in response.get("results", []):
            content = (result.get("raw_content") or "").strip()
            url = result.get("url")
            if content and url in selected:
                documents.append(
                    {
                        "url": url,
                        "title": selected[url].get("title") or url,
                        "content": content[:10000],
                        "retrieved_at": retrieved,
                    }
                )
        # Full provider responses and per-URL failures remain in raw_responses.
        return documents

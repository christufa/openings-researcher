import os
from tavily import TavilyClient

_tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def search_web(query: str, max_results: int = 3) -> tuple[list[str], list[dict]]:
    """Return (content_chunks, article_refs).

    article_refs entries: {title, url, description}
    """
    response = _tavily.search(
        query=query,
        search_depth="advanced",
        max_results=max_results,
        include_answer=True,
    )
    contents: list[str] = []
    articles: list[dict] = []
    if response.get("answer"):
        contents.append(response["answer"])
    for r in response.get("results", []):
        if r.get("content"):
            contents.append(r["content"])
        if r.get("url") and r.get("title"):
            articles.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": (r.get("content") or "")[:200].strip(),
            })
    return contents, articles

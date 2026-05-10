"""Search tools."""

from __future__ import annotations

import json
import os
from typing import Optional


def scholar_search(
    query: str,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    num_results: int = 10,
    page: int = 1,
) -> dict:
    """Search for scholarly literature on Google Scholar via the SearchAPI."""
    try:
        import requests
        from dotenv import load_dotenv

        load_dotenv(override=True)
        api_key = os.getenv("SEARCH_API_KEY")
        if not api_key:
            return {
                "ok": False,
                "error": "SEARCH_API_KEY is not set. Add it to your .env to use ScholarSearch.",
            }

        params: dict = {
            "engine": "google_scholar",
            "api_key": api_key,
            "q": query,
            "num": num_results,
            "page": page,
        }
        if year_from:
            params["as_ylo"] = year_from
        if year_to:
            params["as_yhi"] = year_to

        response = requests.get(
            "https://www.searchapi.io/api/v1/search",
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            return {"ok": False, "error": f"API returned status {response.status_code}: {response.text}"}

        data = response.json()
        if "error" in data:
            return {"ok": False, "error": f"Error from API: {data['error']}"}

        organic_results = data.get("organic_results", [])
        search_info = data.get("search_information", {})
        profiles = data.get("profiles", [])

        articles = []
        for result in organic_results:
            authors = [a.get("name", "Unknown") for a in result.get("authors", [])]
            inline_links = result.get("inline_links", {})
            cited_by = inline_links.get("cited_by", {})
            versions = inline_links.get("versions", {})
            resource = result.get("resource", {})

            article: dict = {
                "title": result.get("title"),
                "link": result.get("link"),
                "publication": result.get("publication"),
                "snippet": result.get("snippet"),
                "authors": authors,
                "citations": cited_by.get("total"),
                "cites_id": cited_by.get("cites_id"),
                "versions_count": versions.get("total"),
                "cluster_id": versions.get("cluster_id"),
            }
            if resource:
                article["resource"] = {
                    "name": resource.get("name"),
                    "format": resource.get("format"),
                    "link": resource.get("link"),
                }
            if inline_links.get("related_articles_link"):
                article["related_articles_link"] = inline_links.get("related_articles_link")
            articles.append(article)

        author_profiles = [
            {
                "name": p.get("name"),
                "affiliations": p.get("affiliations"),
                "email_domain": p.get("email"),
                "total_citations": p.get("cited_by", {}).get("total"),
                "profile_link": p.get("link"),
                "author_id": p.get("author_id"),
            }
            for p in profiles
        ]

        result_payload: dict = {
            "ok": True,
            "query": query,
            "filters": {"year_from": year_from, "year_to": year_to},
            "total_results": search_info.get("total_results"),
            "page": page,
            "articles_count": len(articles),
            "articles": articles,
        }
        if author_profiles:
            result_payload["author_profiles"] = author_profiles
        return result_payload

    except Exception as e:
        return {"ok": False, "error": f"Error searching scholar: {e}"}

"""Replay a shared Airtable view request and optionally capture headers with Browser-Use.

Usage:
    AIRTABLE_COOKIE="<your_cookie_header>" uv run examples/airtable_scrape.py

The script:
1) Rebuilds the readSharedViewData URL with the same query parameters seen in devtools.
2) Replays the request with httpx using the provided cookies/headers.
3) Saves the JSON (or decoded msgpack) to investigation_results/airtable_read_shared_view.json.
4) Provides helpers to record a HAR with Browser-Use and extract the matching request URL/headers.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx
from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse

try:
    import msgpack
except Exception:  # pragma: no cover - optional dependency
    msgpack = None


DEFAULT_ALLOWED_ACTIONS = [
    {"modelClassName": "view", "modelIdSelector": "viw2BuXqXMTdAlSy8", "action": "readSharedViewData"},
    {"modelClassName": "view", "modelIdSelector": "viw2BuXqXMTdAlSy8", "action": "getMetadataForPrinting"},
    {"modelClassName": "view", "modelIdSelector": "viw2BuXqXMTdAlSy8", "action": "readSignedAttachmentUrls"},
    {
        "modelClassName": "row",
        "modelIdSelector": "rows *[displayedInView=viw2BuXqXMTdAlSy8]",
        "action": "createDocumentPreviewSession",
    },
]


class AirtableRequestConfig(BaseModel):
    base_url: str = "https://airtable.com/v0.3/view"
    view_id: str = "viw2BuXqXMTdAlSy8"
    share_id: str = "shrGtTkoHk6QOpsrT"
    application_id: str = "appfLUDj8A9RFqyxy"
    generation_number: int = 0
    expires: str = "2025-12-18T00:00:00.000Z"
    signature: str = "703b558f470297c2c349725d8eaf5b45e6fa8db7a4e539a36bb18f3c6fba2f97"
    allowed_actions: Iterable[Dict[str, str]] = Field(default_factory=lambda: DEFAULT_ALLOWED_ACTIONS)
    should_use_nested_response_format: bool = True
    allow_msgpack_of_result: bool = True

    def build_access_policy(self) -> Dict[str, Any]:
        return {
            "allowedActions": list(self.allowed_actions),
            "shareId": self.share_id,
            "applicationId": self.application_id,
            "generationNumber": self.generation_number,
            "expires": self.expires,
            "signature": self.signature,
        }

    def build_stringified_object_params(self) -> str:
        payload = {"shouldUseNestedResponseFormat": self.should_use_nested_response_format}
        if self.allow_msgpack_of_result:
            payload["allowMsgpackOfResult"] = True
        return json.dumps(payload, separators=(",", ":"))

    def build_query_params(self) -> Dict[str, str]:
        return {
            "stringifiedObjectParams": self.build_stringified_object_params(),
            "requestId": f"req{uuid.uuid4().hex[:16]}",
            "accessPolicy": json.dumps(self.build_access_policy(), separators=(",", ":")),
        }

    def build_url(self) -> str:
        query = httpx.QueryParams(self.build_query_params())
        return f"{self.base_url}/{self.view_id}/readSharedViewData?{query}"


def build_headers(config: AirtableRequestConfig, cookie: Optional[str]) -> Dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "x-airtable-application-id": config.application_id,
        "x-airtable-inter-service-client": "webClient",
        "x-airtable-page-load-id": "pglUhkf9b90Qk7b4l",
        "x-requested-with": "XMLHttpRequest",
        "x-time-zone": "Europe/Paris",
        "x-user-locale": "fr-FR",
    }
    if config.allow_msgpack_of_result:
        headers["x-airtable-accept-msgpack"] = "true"
    if cookie:
        headers["cookie"] = cookie
    return headers


def decode_response(response: httpx.Response) -> Dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return response.json()
        except Exception as e:
            return {"error": f"Failed to decode JSON: {e}", "raw_bytes": response.content.hex()}
    if "application/msgpack" in content_type and msgpack:
        try:
            # Essayer de décoder avec différentes options
            try:
                # Essayer avec strict_map_key=False pour plus de flexibilité
                return msgpack.unpackb(response.content, raw=False, strict_map_key=False)
            except msgpack.exceptions.ExtraData:
                # Si on a des données supplémentaires, utiliser l'Unpacker de manière itérative
                # pour décoder tous les objets valides
                unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
                unpacker.feed(response.content)
                results = []
                try:
                    while True:
                        results.append(unpacker.unpack())
                except msgpack.exceptions.OutOfData:
                    pass
                if results:
                    # Si on a plusieurs objets, les combiner ou retourner le premier
                    if len(results) == 1:
                        return results[0]
                    elif all(isinstance(r, dict) for r in results):
                        # Combiner tous les dictionnaires
                        combined = {}
                        for r in results:
                            combined.update(r)
                        return combined
                    else:
                        return {"items": results}
                raise ValueError("No valid msgpack data found")
            except Exception as e:
                raise e
        except Exception as e:
            # Si msgpack échoue, essayer JSON en fallback
            try:
                return response.json()
            except Exception:
                return {"error": f"Failed to decode msgpack: {e}", "raw_bytes": response.content.hex()[:1000]}
    # Essayer JSON par défaut si le content-type n'est pas clair
    try:
        return response.json()
    except Exception:
        return {"raw_bytes": response.content.hex(), "content_type": content_type}


def fetch_airtable_view(config: AirtableRequestConfig, cookie: Optional[str]) -> Dict[str, Any]:
    url = config.build_url()
    headers = build_headers(config, cookie)
    # HTTP/2 désactivé par défaut car nécessite le package 'h2'
    # Pour activer HTTP/2: pip install httpx[http2] ou uv pip install httpx[http2]
    with httpx.Client(http2=False, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = decode_response(response)
        return {
            "url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "payload": payload,
        }


async def record_har_and_extract_requests(page_url: str, har_path: Path) -> Dict[str, Any]:
    browser = Browser(record_har_path=str(har_path))
    agent = Agent(
        task=f"Ouvre {page_url} et attends que les donnees se chargent.",
        browser=browser,
        llm=ChatBrowserUse(),
    )
    await agent.run(max_steps=6)
    har = json.loads(har_path.read_text())
    matches: list[Dict[str, Any]] = []
    for entry in har.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        url = request.get("url", "")
        if "readSharedViewData" in url:
            matches.append({"url": url, "headers": {h["name"].lower(): h["value"] for h in request.get("headers", [])}})
    return {"matches": matches, "har_path": str(har_path)}


def json_serialize(obj: Any) -> Any:
    """Helper pour sérialiser les objets non-JSON (bytes, etc.)"""
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, dict):
        return {k: json_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_serialize(item) for item in obj]
    return obj


def main() -> None:
    cookie = os.getenv("AIRTABLE_COOKIE")
    config = AirtableRequestConfig()
    result = fetch_airtable_view(config, cookie)

    # Sérialiser le résultat en convertissant les bytes
    serializable_result = json_serialize(result)

    output_path = Path("investigation_results/airtable_read_shared_view.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(serializable_result, indent=2, ensure_ascii=True))
    print(f"Fetched {result['status_code']} from {result['url']}")
    print(f"Saved response to {output_path}")
    if not cookie:
        print("Note: set AIRTABLE_COOKIE to replay authenticated traffic (may be required for private views).")


if __name__ == "__main__":
    main()

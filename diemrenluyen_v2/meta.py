"""Meta Graph API client for reading Facebook Page posts.

Honesty note: reading a Page you do not manage requires Meta's **Page Public
Content Access** feature (app review, possibly business verification — approval
is controlled by Meta and is not guaranteed). Without it, only Pages your
token's app/user can manage are readable. The engine degrades gracefully:
per-page failures are recorded and never stop the rest of the poll cycle.
"""

from __future__ import annotations

import logging
from typing import Any

import requests


LOG = logging.getLogger("diemrenluyen.meta")


class MetaError(RuntimeError):
    """Raised when the Meta Graph API cannot serve a request."""


class MetaClient:
    def __init__(self, api_version: str, timeout: int = 30) -> None:
        self.base_url = f"https://graph.facebook.com/{api_version}"
        self.session = requests.Session()
        self.timeout = timeout

    def get_page_name(self, page_id: str, access_token: str) -> str:
        data = self._get(
            f"{self.base_url}/{page_id}",
            params={"fields": "name", "access_token": access_token},
        )
        return str(data.get("name", page_id))

    def get_recent_posts(
        self, page_id: str, access_token: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.base_url}/{page_id}/posts",
            params={
                "fields": "id,message,created_time,permalink_url",
                "limit": limit,
                "access_token": access_token,
            },
        )
        posts = data.get("data", [])
        if not isinstance(posts, list):
            raise MetaError("Meta returned an unexpected posts response")
        return posts

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise MetaError(f"Network error talking to Meta: {exc}") from exc
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise MetaError(f"Meta returned HTTP {response.status_code}") from exc
        if not response.ok or "error" in payload:
            error = payload.get("error", {})
            message = error.get("message", f"HTTP {response.status_code}")
            code = error.get("code", "?")
            raise MetaError(f"Meta API error (code {code}): {message}")
        return payload

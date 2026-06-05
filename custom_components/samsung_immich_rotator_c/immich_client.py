"""
Immich public-share API client.

Uses only Immich's public-share endpoints — no user account or API key required.

Endpoints:
  GET /api/shared-links/me             - resolve album UUID from the share key
  GET /api/albums/<albumId>            - album metadata + asset list
  GET /api/assets/<assetId>/original   - download original image bytes
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class ImmichAsset:
    """Minimal representation of an Immich image asset."""

    id: str
    file_name: str


class ImmichError(Exception):
    """Raised for any Immich API error."""


class ImmichClient:
    """Client for Immich's public-share API.

    Args:
        share_url: Full public share URL, e.g.
            ``https://immich.example.com/share/<key>``.
        session: The shared aiohttp session from HA.
    """

    def __init__(self, share_url: str, session: aiohttp.ClientSession) -> None:
        self._share_url = share_url
        self._share_key = self._extract_share_key(share_url)
        self._base_url = self._extract_base_url(share_url)
        self._session = session
        self._album_id: Optional[str] = None

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _extract_share_key(url: str) -> str:
        m = re.search(r"/share/([^/?#]+)", url)
        if not m:
            raise ImmichError(
                f"Invalid Immich share URL — no /share/<key> segment: {url!r}"
            )
        return m.group(1)

    @staticmethod
    def _extract_base_url(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def _get(self, path: str, **params) -> dict:
        """Perform an authenticated GET against the Immich API."""
        url = f"{self._base_url}{path}"
        params.setdefault("key", self._share_key)
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status in (401, 403):
                    raise ImmichError(
                        f"Immich auth failed ({resp.status}). "
                        "The share key may be invalid, expired, or the album may no longer "
                        "match this share. Regenerate the share link in Immich."
                    )
                if resp.status == 404:
                    raise ImmichError(f"Immich resource not found: {path}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(f"Immich API error {resp.status}: {body[:200]}")
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" not in content_type:
                    text = await resp.text()
                    raise ImmichError(
                        f"Expected JSON from {path}, got {content_type}: {text[:200]}"
                    )
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise ImmichError(f"Network error reaching Immich: {exc}") from exc

    # ------------------------------------------------------------------ public API

    async def validate_share(self) -> str:
        """Validate the share URL and return the album ID.

        Calls ``/api/shared-links/me`` and verifies the share is of type ALBUM.
        Raises ``ImmichError`` on failure (used during config-flow validation).
        """
        data = await self._get("/api/shared-links/me")
        if not isinstance(data, dict):
            raise ImmichError("Unexpected response from /api/shared-links/me")
        share_type = data.get("type")
        if share_type != "ALBUM":
            raise ImmichError(
                f"Share type is {share_type!r} — this integration requires an ALBUM share. "
                "Create a share with 'Share album' in Immich."
            )
        album = data.get("album") or {}
        album_id = album.get("id")
        if not album_id:
            raise ImmichError("Share response missing album.id")
        self._album_id = album_id
        return album_id

    async def get_album_id(self) -> str:
        """Return the cached album ID, resolving it if necessary."""
        if self._album_id is None:
            await self.validate_share()
        return self._album_id  # type: ignore[return-value]

    async def list_assets(self) -> List[ImmichAsset]:
        """Return all IMAGE assets in the shared album.

        Args: None — resolves the album ID automatically.
        Returns: List of ``ImmichAsset`` objects (images only, no videos).
        """
        album_id = await self.get_album_id()
        data = await self._get(
            f"/api/albums/{album_id}", **{"withoutAssets": "false"}
        )
        assets_raw = data.get("assets", [])
        result: List[ImmichAsset] = []
        for a in assets_raw:
            if a.get("type") == "IMAGE" or a.get("isImage"):
                result.append(
                    ImmichAsset(
                        id=a["id"],
                        file_name=a.get("originalFileName", f"{a['id']}.jpg"),
                    )
                )
        _LOGGER.info("Found %d image assets in album %s", len(result), album_id)
        return result

    async def download_original(self, asset_id: str) -> bytes:
        """Download the original image bytes for an asset.

        Args:
            asset_id: Immich asset UUID.
        Returns: Raw image bytes.
        Raises: ``ImmichError`` on HTTP error or network failure.
        """
        url = f"{self._base_url}/api/assets/{asset_id}/original"
        params = {"key": self._share_key}
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise ImmichError(
                        f"Download failed for asset {asset_id}: {resp.status} {body[:200]}"
                    )
                return await resp.read()
        except aiohttp.ClientError as exc:
            raise ImmichError(f"Network error downloading asset {asset_id}: {exc}") from exc

"""
Async state persistence for the rotation engine.

Stores JSON in <ha_config>/.storage/samsung_immich_rotator_c/<entry_id>_state.json.
All file I/O runs in worker threads (asyncio.to_thread) — the HA event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_LOGGER = logging.getLogger(__name__)


@dataclass
class RotationState:
    """Full rotation state persisted across HA restarts."""

    current_index: int = 0
    asset_order: List[str] = field(default_factory=list)
    uploaded: Dict[str, str] = field(default_factory=dict)  # immich_id -> frame content_id
    current_immich_id: Optional[str] = None
    last_rotation: Optional[str] = None       # tz-aware ISO string
    last_rotation_status: Optional[str] = None  # "ok" | "error" | "skipped"
    last_rotation_error: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RotationState":
        """Deserialize from a dict loaded from JSON."""
        return cls(
            current_index=d.get("current_index", 0),
            asset_order=d.get("asset_order", []),
            uploaded=d.get("uploaded", {}),
            current_immich_id=d.get("current_immich_id"),
            last_rotation=d.get("last_rotation"),
            last_rotation_status=d.get("last_rotation_status"),
            last_rotation_error=d.get("last_rotation_error"),
        )


class StateStore:
    """Thread-safe, asyncio-safe state persistence.

    Construction does zero file I/O — call `await load()` explicitly from
    `async_setup_entry` after constructing this object.
    """

    def __init__(self, path: Path | str) -> None:
        # Normalise to Path defensively; hass.config.path() returns str in HA 2024.4+.
        self._path = Path(path)
        self._lock = threading.RLock()
        self._state = RotationState()

    # ------------------------------------------------------------------ sync workers

    def _sync_load(self) -> RotationState:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                state = RotationState.from_dict(data)
                _LOGGER.info(
                    "Loaded state from %s (index=%d, %d assets, %d uploaded)",
                    self._path,
                    state.current_index,
                    len(state.asset_order),
                    len(state.uploaded),
                )
                return state
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                _LOGGER.warning("State file corrupt, starting fresh: %s", exc)
        return RotationState()

    def _sync_save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._state.to_dict(), indent=2), encoding="utf-8"
            )
            tmp.replace(self._path)

    def _sync_update_assets(self, asset_ids: List[str]) -> bool:
        """Replace the asset list; return True if it changed."""
        with self._lock:
            if set(asset_ids) == set(self._state.asset_order):
                return False
            self._state.asset_order = list(asset_ids)
            if self._state.current_index >= len(asset_ids):
                self._state.current_index = 0
            self._sync_save()
            _LOGGER.info("Asset list updated: %d images", len(asset_ids))
            return True

    def _sync_advance(self) -> int:
        """Advance the round-robin index and save; return the new index."""
        with self._lock:
            if not self._state.asset_order:
                return 0
            self._state.current_index = (
                (self._state.current_index + 1) % len(self._state.asset_order)
            )
            self._sync_save()
            return self._state.current_index

    def _sync_mark_uploaded(self, immich_id: str, frame_content_id: str) -> None:
        with self._lock:
            self._state.uploaded[immich_id] = frame_content_id
            self._state.current_immich_id = immich_id
            self._sync_save()

    def _sync_set_last_rotation(self, status: str, error: Optional[str]) -> None:
        with self._lock:
            # tz-aware UTC — HA's timestamp device_class requires this.
            self._state.last_rotation = datetime.now(timezone.utc).isoformat()
            self._state.last_rotation_status = status
            self._state.last_rotation_error = error
            self._sync_save()

    # ------------------------------------------------------------------ async public API

    async def load(self) -> None:
        """Load state from disk (worker thread). Await once after construction."""
        try:
            self._state = await asyncio.to_thread(self._sync_load)
        except OSError as exc:
            _LOGGER.warning("Could not read state file: %s", exc)
            self._state = RotationState()

    async def save(self) -> None:
        """Persist current in-memory state to disk."""
        await asyncio.to_thread(self._sync_save)

    async def update_assets(self, asset_ids: List[str]) -> bool:
        """Update the asset list; return True if it changed."""
        return await asyncio.to_thread(self._sync_update_assets, list(asset_ids))

    async def advance(self) -> int:
        """Advance round-robin index and persist; return new index."""
        return await asyncio.to_thread(self._sync_advance)

    async def mark_uploaded(self, immich_id: str, frame_content_id: str) -> None:
        """Record that an image has been uploaded to the Frame."""
        await asyncio.to_thread(self._sync_mark_uploaded, immich_id, frame_content_id)

    async def set_last_rotation(self, status: str, error: Optional[str] = None) -> None:
        """Record the outcome of a rotation attempt."""
        await asyncio.to_thread(self._sync_set_last_rotation, status, error)

    # ------------------------------------------------------------------ sync read API (no I/O)

    @property
    def state(self) -> RotationState:
        """Return the current in-memory state (read-only)."""
        return self._state

    def get_frame_content_id(self, immich_id: str) -> Optional[str]:
        """Return the Frame content_id for an Immich asset, or None if not uploaded yet."""
        with self._lock:
            return self._state.uploaded.get(immich_id)

    def current_asset_id(self) -> Optional[str]:
        """Return the Immich asset ID at the current index."""
        with self._lock:
            if not self._state.asset_order:
                return None
            return self._state.asset_order[self._state.current_index]

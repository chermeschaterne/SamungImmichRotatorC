"""
Samsung Frame TV client.

Wraps the ``samsungtvws`` WebSocket library with production robustness:

- Wake-on-LAN fallback when the TV is in deep sleep.
- KEY_POWER priming to unblock the art WebSocket (Tizen quirk).
- ``_with_timeout``: daemon-thread hard cutoff protecting against hung ``recv()``.
- ``robust_call``: exception-based retry with per-attempt timeout.
- Post-upload artmode enable (NOT before upload — causes 8-16s blocking).
- ``tv.art()`` returning ``None`` treated as a failed connect (2023+ Frame bug).
- Token persistence via caller-managed token property.
"""
from __future__ import annotations

import asyncio
import io
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Optional

from PIL import Image

_LOGGER = logging.getLogger(__name__)

FRAME_W, FRAME_H = 3840, 2160
FRAME_QUALITY = 92


# ---------------------------------------------------------------------------
# Low-level robustness helpers
# ---------------------------------------------------------------------------


def _with_timeout(func, *args, timeout: float = 12.0, **kwargs):
    """Run a sync callable in a daemon thread with a hard wall-clock deadline.

    Returns:
        (value, exception). On timeout: (None, TimeoutError).
    """
    result: list = [None, None]

    def _runner():
        try:
            result[0] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            result[1] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        return None, TimeoutError(f"call exceeded {timeout:.1f}s wall-clock deadline")
    return result[0], result[1]


def robust_call(
    func,
    *args,
    max_attempts: int = 2,
    retry_delay: float = 2.5,
    timeout: float = 12.0,
    **kwargs,
):
    """Call ``func`` with retry on exception and a hard timeout per attempt.

    Args:
        func: Sync callable.
        max_attempts: Total number of attempts.
        retry_delay: Seconds to sleep between attempts.
        timeout: Wall-clock deadline per attempt.
    Returns: The return value of ``func`` on success.
    Raises: The last exception if all attempts fail.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        value, exc = _with_timeout(func, *args, timeout=timeout, **kwargs)
        if exc is None:
            if attempt > 1:
                _LOGGER.info("robust_call succeeded on attempt %d", attempt)
            return value
        if isinstance(exc, TimeoutError):
            _LOGGER.warning(
                "robust_call attempt %d/%d timed out (%.1fs)", attempt, max_attempts, timeout
            )
        else:
            _LOGGER.warning(
                "robust_call attempt %d/%d: %s: %s",
                attempt, max_attempts, type(exc).__name__, exc,
            )
        last_exc = exc
        if attempt < max_attempts:
            time.sleep(retry_delay)
    raise last_exc or RuntimeError("robust_call: all attempts failed")


# ---------------------------------------------------------------------------
# Wake-on-LAN
# ---------------------------------------------------------------------------


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a Wake-on-LAN magic packet to ``mac``.

    Args:
        mac: MAC address in colon or hyphen notation.
        broadcast: Broadcast address (default: 255.255.255.255).
        port: UDP port (default: 9).
    Raises: ``ValueError`` if the MAC is malformed.
    """
    mac_clean = mac.replace(":", "").replace("-", "").lower()
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address for WoL: {mac!r}")
    try:
        mac_bytes = bytes.fromhex(mac_clean)
    except ValueError as exc:
        raise ValueError(f"Invalid hex in MAC address {mac!r}: {exc}") from None

    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    _LOGGER.info("Sent Wake-on-LAN packet to %s via %s:%d", mac, broadcast, port)


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------


def resize_for_frame(
    input_bytes: bytes,
    target: tuple[int, int] = (FRAME_W, FRAME_H),
    quality: int = FRAME_QUALITY,
) -> bytes:
    """Resize an image to the Frame's native resolution (center-crop, preserve aspect).

    Args:
        input_bytes: Raw image bytes (any PIL-supported format).
        target: (width, height) output resolution.
        quality: JPEG quality (1-95).
    Returns: JPEG bytes ready for upload.
    """
    img = Image.open(io.BytesIO(input_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    target_w, target_h = target
    ratio = img.width / img.height
    target_ratio = target_w / target_h

    if ratio > target_ratio:
        new_w = target_w
        new_h = int(target_w / ratio)
    else:
        new_h = target_h
        new_w = int(target_h * ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    if left or top or new_w != target_w or new_h != target_h:
        img = img.crop((left, top, left + target_w, top + target_h))

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    _LOGGER.debug("Resized image to %dx%d JPEG (%d bytes)", target_w, target_h, buf.tell())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------


class FrameClient:
    """High-level client for Samsung Frame TV art operations.

    Args:
        host: TV IP address.
        mac: TV MAC address (used for WoL).
        client_name: Name shown in the TV's "Allow connection?" popup.
        matte: Matte/frame style (``"none"`` disables the matte).
        token: Auth token from a previous session (or None for first-time setup).
        port: WebSocket port (default: 8002).
    """

    def __init__(
        self,
        host: str,
        mac: str,
        client_name: str = "SamsungImmichRotatorC",
        matte: str = "none",
        token: Optional[str] = None,
        port: int = 8002,
    ) -> None:
        self.host = host
        self.mac = mac
        self.client_name = client_name
        self.matte = matte
        self.port = port
        self._token = token
        self._tv = None
        self._art = None

    # ------------------------------------------------------------------ helpers

    @property
    def token(self) -> Optional[str]:
        """Current auth token (may be updated after a successful connect)."""
        return self._token

    @token.setter
    def token(self, value: Optional[str]) -> None:
        self._token = value

    def _is_reachable(self, timeout: float = 3.0) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def _new_tv(self):
        from samsungtvws import SamsungTVWS  # deferred import — only available in HA container

        return SamsungTVWS(
            host=self.host,
            port=self.port,
            token=self._token,
            timeout=30,
            name=self.client_name,
        )

    def _prime_connection(self) -> None:
        """Send KEY_POWER via the remote API to unblock the art WebSocket."""
        if self._tv is None:
            return
        try:
            remote = self._tv.remote()
            remote.send_key("KEY_POWER")
        except Exception:  # noqa: BLE001
            pass  # priming is best-effort; failure is non-fatal

    # ------------------------------------------------------------------ lifecycle

    async def connect(self, wake_if_needed: bool = True) -> bool:
        """Establish WebSocket connection, with WoL fallback.

        Args:
            wake_if_needed: Send a WoL packet if the TV is not reachable.
        Returns: True on success, False if the TV could not be reached.
        """
        if not await asyncio.to_thread(self._is_reachable):
            if not wake_if_needed:
                _LOGGER.warning("Frame %s:%d not reachable", self.host, self.port)
                return False
            _LOGGER.info("Frame not reachable — sending Wake-on-LAN to %s", self.mac)
            try:
                await asyncio.to_thread(send_wol, self.mac)
            except ValueError as exc:
                _LOGGER.warning("WoL: bad MAC address: %s", exc)

            deadline = 30
            waited = 0
            while waited < deadline:
                await asyncio.sleep(2)
                waited += 2
                if await asyncio.to_thread(self._is_reachable):
                    _LOGGER.info("Frame reachable after %ds WoL wait", waited)
                    break
            else:
                _LOGGER.error(
                    "Frame %s still unreachable after %ds WoL wait", self.host, deadline
                )
                return False

        # Build the TV object
        try:
            self._tv = await asyncio.to_thread(self._new_tv)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to initialise SamsungTVWS: %s", exc)
            return False

        # Prime the connection (best-effort, non-fatal)
        try:
            await asyncio.to_thread(self._prime_connection)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("KEY_POWER priming failed (non-fatal): %s", exc)

        # Obtain the art handle
        try:
            self._art = await asyncio.to_thread(self._tv.art)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to obtain art handle from TV: %s", exc)
            return False

        # 2023+ Frame models occasionally return None instead of raising.
        if self._art is None:
            _LOGGER.error(
                "tv.art() returned None — Frame WebSocket state may be polluted. "
                "Hard-reset the TV (unplug 3 min, wait 10 min) then reload the integration."
            )
            return False

        # Capture any new token the TV issued (e.g. first-time approval)
        if self._tv.token and self._tv.token != self._token:
            self._token = self._tv.token
            _LOGGER.info("Captured new TV token (first-time approval or token refresh)")

        return True

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._tv is not None:
            try:
                await asyncio.to_thread(self._tv.close)
            except Exception:  # noqa: BLE001
                pass
            self._tv = None
            self._art = None

    # ------------------------------------------------------------------ art operations

    async def is_in_art_mode(self) -> bool:
        """Check if the TV is currently in art mode."""
        if self._art is None:
            return False
        try:
            value, exc = await asyncio.to_thread(
                _with_timeout, self._art.get_artmode, timeout=8.0
            )
            if exc is not None:
                _LOGGER.debug("get_artmode error: %s", exc)
                return False
            return str(value).lower() == "on"
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("is_in_art_mode: %s", exc)
            return False

    async def upload_image(self, image_bytes: bytes) -> Optional[str]:
        """Resize and upload an image to the Frame; return the content_id.

        Args:
            image_bytes: Raw image bytes (any format Pillow can read).
        Returns: Frame ``content_id`` string on success, or ``None`` on failure.
        """
        if self._art is None:
            _LOGGER.error("upload_image() called before connect()")
            return None

        try:
            jpeg_bytes = await asyncio.to_thread(resize_for_frame, image_bytes)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Image resize failed: %s", exc)
            return None

        def _do_upload():
            return self._art.upload(
                jpeg_bytes, file_type="JPEG",
                matte=self.matte, portrait_matte=self.matte,
            )

        try:
            content_id = await asyncio.to_thread(
                robust_call, _do_upload, max_attempts=2, retry_delay=2.5, timeout=60.0
            )
            if isinstance(content_id, dict):
                content_id = content_id.get("content_id") or content_id.get("id")
            _LOGGER.info("Uploaded image to Frame, content_id=%s", content_id)
            return str(content_id) if content_id else None
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Upload failed: %s", exc)
            return None

    async def select_image(self, content_id: str, show: bool = False) -> bool:
        """Select an image by content_id.

        Args:
            content_id: Frame content ID from a previous upload.
            show: If True, wake the panel. Keep False for silent rotation.
        Returns: True on success.
        """
        if self._art is None:
            return False

        def _do_select():
            return self._art.select_image(content_id, show=show)

        try:
            await asyncio.to_thread(
                robust_call, _do_select, max_attempts=2, retry_delay=2.0, timeout=10.0
            )
            _LOGGER.info("Selected image %s (show=%s)", content_id, show)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("select_image(%s) failed: %s", content_id, exc)
            return False

    async def set_art_mode(self, enabled: bool) -> bool:
        """Enable or disable art mode (panel on/off).

        Args:
            enabled: True = art mode on (panel visible), False = standby.
        Returns: True on success.
        """
        if self._art is None:
            return False

        def _do_set():
            return self._art.set_artmode(enabled)

        try:
            await asyncio.to_thread(
                robust_call, _do_set, max_attempts=2, retry_delay=2.0, timeout=10.0
            )
            _LOGGER.info("Set art mode = %s", enabled)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("set_artmode(%s) failed: %s", enabled, exc)
            return False

    async def set_brightness(self, level: int, disable_sensor: bool = True) -> bool:
        """Set brightness level and optionally disable the ambient-light sensor.

        Args:
            level: Brightness 1–10.
            disable_sensor: If True, disable the ambient-light sensor (recommended).
        Returns: True if all requested operations succeeded.
        """
        if self._art is None:
            return False
        level = max(1, min(10, level))

        def _do_brightness():
            return self._art.set_brightness(level)

        def _do_sensor_off():
            return self._art.set_brightness_sensor_setting(False)

        ok_brightness = False
        ok_sensor = True  # default: success if not requested

        try:
            await asyncio.to_thread(
                robust_call, _do_brightness, max_attempts=2, retry_delay=2.0, timeout=10.0
            )
            ok_brightness = True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("set_brightness(%d) failed: %s", level, exc)

        if disable_sensor:
            ok_sensor = False
            try:
                await asyncio.to_thread(
                    robust_call, _do_sensor_off, max_attempts=2, retry_delay=2.0, timeout=10.0
                )
                ok_sensor = True
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("set_brightness_sensor_setting(False) failed: %s", exc)

        if ok_brightness:
            _LOGGER.info(
                "Set brightness=%d (sensor disabled=%s)", level, disable_sensor and ok_sensor
            )
        return ok_brightness and ok_sensor

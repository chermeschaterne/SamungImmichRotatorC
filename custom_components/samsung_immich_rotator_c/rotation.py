"""
Rotation engine — performs one full image-rotation cycle.

A rotation cycle:
  1. Fetch the list of artworks currently on the Frame TV (art.available()).
  2. Pick the next image via round-robin (index wraps to 0 at end of list).
  3. Select the image on the Frame.
  4. Set brightness + disable ambient-light sensor.
  5. Record result in state.

Called from the coordinator's daily timer and the manual "Rotate Now" button.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import RotatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def run_rotation(coordinator: "RotatorCoordinator") -> None:
    """Execute one rotation cycle.

    Mutates coordinator state and triggers a coordinator refresh on completion
    so entity states update immediately.

    Args:
        coordinator: The active ``RotatorCoordinator`` instance.
    """
    state_store = coordinator.state_store
    frame = coordinator.frame
    brightness: int = coordinator.options_brightness
    disable_ambient: bool = coordinator.options_disable_ambient

    _LOGGER.info("Starting rotation cycle")

    # Step 1: Connect to the TV
    connected = await frame.connect(wake_if_needed=True)
    if not connected:
        msg = "Frame unreachable (WoL did not help)"
        _LOGGER.error("Rotation: %s", msg)
        await state_store.set_last_rotation("error", msg)
        coordinator.async_update_listeners()
        return

    # Step 2: Fetch list of artworks currently on the Frame TV
    try:
        artworks = await frame.list_available_artworks()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Rotation: failed to list Frame artworks: %s", exc)
        await state_store.set_last_rotation("error", f"list artworks: {exc}")
        await frame.close()
        coordinator.async_update_listeners()
        return

    if not artworks:
        _LOGGER.info("Rotation: Frame gallery is empty — skipping")
        await state_store.set_last_rotation("skipped", "empty gallery")
        await frame.close()
        coordinator.async_update_listeners()
        return

    # Extract content_ids from the artwork list
    content_ids = [art.get("content_id") for art in artworks if art.get("content_id")]
    if not content_ids:
        _LOGGER.error("Rotation: no valid content_ids in Frame gallery")
        await state_store.set_last_rotation("error", "no valid content_ids")
        await frame.close()
        coordinator.async_update_listeners()
        return

    # Update state with the current gallery list (ensures index is valid)
    await state_store.update_assets(content_ids)

    # Step 3: Advance to the next image (round-robin with wrap-around)
    new_index = await state_store.advance()
    content_id = state_store.state.asset_order[new_index]
    _LOGGER.info(
        "Rotation: selected content_id %s (index %d/%d)", content_id, new_index, len(content_ids)
    )

    # Step 4: Select the image (show=False for silent rotation)
    ok = await frame.select_image(content_id, show=False)
    if not ok:
        await state_store.set_last_rotation("error", "select_image failed")
        await frame.close()
        coordinator.async_update_listeners()
        return

    # Step 5: Set brightness after image change
    await frame.set_brightness(brightness, disable_sensor=disable_ambient)

    await frame.close()

    # Step 6: Record success
    await state_store.set_last_rotation("ok")
    _LOGGER.info("Rotation: complete (content_id=%s, brightness=%d)", content_id, brightness)
    coordinator.async_update_listeners()

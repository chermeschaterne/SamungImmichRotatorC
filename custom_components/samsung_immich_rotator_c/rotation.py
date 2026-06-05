"""
Rotation engine — performs one full image-rotation cycle.

A rotation cycle:
  1. Fetch current album assets from Immich.
  2. Pick the next image via round-robin (StateStore.advance).
  3. If already uploaded: just select_image on the Frame (silent, no panel wake).
  4. If new: download → resize → upload → select_image.
  5. set_brightness + disable ambient-light sensor.
  6. Record result in state.

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
    immich = coordinator.immich
    frame = coordinator.frame
    brightness: int = coordinator.options_brightness
    disable_ambient: bool = coordinator.options_disable_ambient

    _LOGGER.info("Starting rotation cycle")

    # Step 1: Fetch album assets
    try:
        assets = await immich.list_assets()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Rotation: failed to list Immich assets: %s", exc)
        await state_store.set_last_rotation("error", f"fetch assets: {exc}")
        coordinator.async_update_listeners()
        return

    if not assets:
        _LOGGER.info("Rotation: album is empty — skipping")
        await state_store.set_last_rotation("skipped", "empty album")
        coordinator.async_update_listeners()
        return

    # Update the asset list (may change current_index if the list shrank)
    asset_ids = [a.id for a in assets]
    await state_store.update_assets(asset_ids)

    # Step 2: Advance to the next image
    new_index = await state_store.advance()
    immich_id = state_store.state.asset_order[new_index]
    _LOGGER.info(
        "Rotation: selected asset %s (index %d/%d)", immich_id, new_index, len(assets)
    )

    # Step 3/4: Connect to the TV, upload if needed
    connected = await frame.connect(wake_if_needed=True)
    if not connected:
        msg = "frame unreachable (WoL did not help)"
        _LOGGER.error("Rotation: %s", msg)
        await state_store.set_last_rotation("error", msg)
        coordinator.async_update_listeners()
        return

    existing_content_id = state_store.get_frame_content_id(immich_id)

    if existing_content_id:
        # Already uploaded — just select it silently
        _LOGGER.info("Rotation: image already on Frame (%s), selecting silently", existing_content_id)
        ok = await frame.select_image(existing_content_id, show=False)
        if not ok:
            await state_store.set_last_rotation("error", "select_image failed (cached)")
            await frame.close()
            coordinator.async_update_listeners()
            return
    else:
        # New image — download, resize, upload
        try:
            raw_bytes = await immich.download_original(immich_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Rotation: download failed for %s: %s", immich_id, exc)
            await state_store.set_last_rotation("error", f"download: {exc}")
            await frame.close()
            coordinator.async_update_listeners()
            return

        content_id = await frame.upload_image(raw_bytes)
        if not content_id:
            await state_store.set_last_rotation("error", "upload to Frame failed")
            await frame.close()
            coordinator.async_update_listeners()
            return

        await state_store.mark_uploaded(immich_id, content_id)

        # Select after upload (NOT before — pre-upload artmode causes 8-16s blocking)
        ok = await frame.select_image(content_id, show=False)
        if not ok:
            await state_store.set_last_rotation("error", "select_image failed (new upload)")
            await frame.close()
            coordinator.async_update_listeners()
            return

    # Step 5: Brightness
    await frame.set_brightness(brightness, disable_sensor=disable_ambient)

    await frame.close()

    # Step 6: Record success
    await state_store.set_last_rotation("ok")
    _LOGGER.info("Rotation: complete (asset=%s, brightness=%d)", immich_id, brightness)
    coordinator.async_update_listeners()

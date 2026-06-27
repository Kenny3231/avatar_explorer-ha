import logging
import re
from datetime import datetime
from pathlib import Path

from homeassistant.helpers import aiohttp_client

from .const import (
    AIDE_JSON_URL,
    CONF_SCALE,
    DEFAULT_DIR,
    DEFAULT_SCALE,
    DOMAIN,
    EXPORT_API_URL,
)

_LOGGER = logging.getLogger(__name__)

REMOTE_WWW_PREFIX = "/config/www/"
DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0"}
WGET_LINE_RE = re.compile(r'-O\s+"([^"]+)"\s+"([^"]+)"')


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_file(path: str, content: bytes) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


async def async_fetch_aide_json(session) -> dict:
    async with session.get(AIDE_JSON_URL, timeout=20) as resp:
        resp.raise_for_status()
        return await resp.json()


async def async_run_export(hass, session, params: dict) -> bool:
    """Appelle /api/export, parse le script wget retourné et télécharge chaque fichier."""
    try:
        async with session.get(EXPORT_API_URL, params=params, timeout=30) as resp:
            resp.raise_for_status()
            script = await resp.text()
    except Exception as err:
        _LOGGER.warning("Échec de l'appel export Pose Explorer (%s): %s", params, err)
        return False

    pairs = WGET_LINE_RE.findall(script)
    if not pairs:
        _LOGGER.warning("Aucun fichier à télécharger dans la réponse export pour %s", params)
        return False

    www_root = hass.config.path("www")
    success = True
    for dest, url in pairs:
        if dest.startswith(REMOTE_WWW_PREFIX):
            relative = dest[len(REMOTE_WWW_PREFIX):]
        else:
            relative = dest.lstrip("/")
        local_path = str(Path(www_root) / relative)

        try:
            async with session.get(url, headers=DOWNLOAD_HEADERS, timeout=30) as file_resp:
                file_resp.raise_for_status()
                content = await file_resp.read()
            await hass.async_add_executor_job(_write_file, local_path, content)
        except Exception as err:
            _LOGGER.warning("Échec téléchargement %s -> %s: %s", url, local_path, err)
            success = False

    return success


async def async_check_for_update(hass, entry, force: bool = False) -> None:
    session = aiohttp_client.async_get_clientsession(hass)
    sync_entity = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("sync_entity")
    if sync_entity is None:
        _LOGGER.debug("Entité de synchro Avatar Explorer pas encore prête, vérification ignorée")
        return

    try:
        aide = await async_fetch_aide_json(session)
        remote_iso = aide["last_updated_iso"]
    except Exception as err:
        sync_entity.mark_checked("erreur", f"aide.json: {err}")
        return

    local_iso = sync_entity.native_value
    needs_update = force or not local_iso
    if not needs_update:
        try:
            needs_update = _parse_iso(remote_iso) > _parse_iso(local_iso)
        except ValueError:
            needs_update = True

    if not needs_update:
        sync_entity.mark_checked("a_jour")
        return

    users = entry.data.get("users", [])
    base_dir = entry.data.get("dir", DEFAULT_DIR)
    scale = entry.options.get(CONF_SCALE, DEFAULT_SCALE)
    failed = []

    for user in users:
        bitmoji_id = user.get("bitmoji_id")
        folder = user.get("user_id_folder")
        if not bitmoji_id:
            _LOGGER.debug("Pas de Bitmoji ID configuré pour %s, import solo ignoré", folder)
            continue
        ok = await async_run_export(hass, session, {
            "id1": bitmoji_id,
            "name1": folder,
            "mode": "solo",
            "dir": base_dir,
            "scale": scale,
        })
        if not ok:
            failed.append(folder)

    duo_pair = entry.data.get("duo_pair")
    if duo_pair:
        u1 = next((u for u in users if u.get("user_id_folder") == duo_pair[0]), None)
        u2 = next((u for u in users if u.get("user_id_folder") == duo_pair[1]), None)
        if u1 and u2 and u1.get("bitmoji_id") and u2.get("bitmoji_id"):
            ok = await async_run_export(hass, session, {
                "id1": u1["bitmoji_id"],
                "name1": u1["user_id_folder"],
                "id2": u2["bitmoji_id"],
                "name2": u2["user_id_folder"],
                "mode": "duo",
                "dir": base_dir,
                "scale": scale,
            })
            if not ok:
                failed.append("Duo")

    if failed:
        sync_entity.mark_checked("erreur", f"Échec pour: {', '.join(failed)}")
    else:
        sync_entity.mark_synced(remote_iso)

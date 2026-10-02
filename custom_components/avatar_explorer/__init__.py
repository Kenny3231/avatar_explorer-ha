"""Intégration Avatar Explorer : poses Bitmoji synchronisées pour Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .const import (
    CONF_BITMOJI_ID,
    CONF_LANG,
    CONF_SCALE,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_USER_FOLDER,
    CONF_USERS,
    DEFAULT_LANG,
    DEFAULT_SCALE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_UPDATE_INTERVAL_HOURS,
)
from .runtime import (
    AvatarExplorerConfigEntry,
    AvatarExplorerRuntime,
    SyncManager,
    SyncState,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TEXT, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Mise en place globale : actions et carte, une seule fois par démarrage."""
    async_setup_services(hass)
    await async_register_card(hass)
    return True


def update_interval_hours(options: dict[str, Any]) -> int:
    """Intervalle de vérification, borné.

    Une entrée existante peut contenir une valeur hors bornes (le formulaire
    ne les imposait pas) : 0 donnerait une boucle serrée.
    """
    try:
        hours = int(
            options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        )
    except (TypeError, ValueError):
        hours = DEFAULT_UPDATE_INTERVAL_HOURS
    return max(MIN_UPDATE_INTERVAL_HOURS, min(MAX_UPDATE_INTERVAL_HOURS, hours))


def _config_snapshot(entry: AvatarExplorerConfigEntry) -> dict[str, Any]:
    """Valeurs qui pilotent la synchro, pour détecter ce qui a changé."""
    return {
        "ids": {
            u.get(CONF_USER_FOLDER): u.get(CONF_BITMOJI_ID) or ""
            for u in entry.data.get(CONF_USERS, [])
        },
        "scale": str(entry.options.get(CONF_SCALE, DEFAULT_SCALE)),
        "lang": entry.options.get(CONF_LANG, DEFAULT_LANG),
        "interval": update_interval_hours(entry.options),
    }


@callback
def _async_schedule_interval(
    hass: HomeAssistant, entry: AvatarExplorerConfigEntry
) -> None:
    """(Re)programme la vérification périodique du catalogue.

    L'ancienne version passait une lambda à async_track_time_interval. Ni
    coroutine ni @callback, elle était exécutée dans un thread de l'executor,
    où hass.async_create_task lève une RuntimeError : aucune vérification
    périodique n'a jamais eu lieu, seulement celle du démarrage.
    """
    runtime = entry.runtime_data
    runtime.async_cancel_interval()
    hours = runtime.config_snapshot["interval"]

    @callback
    def _async_tick(_now: datetime) -> None:
        _LOGGER.debug("Vérification périodique du catalogue Avatar Explorer")
        runtime.sync.async_request()

    runtime.unsub_interval = async_track_time_interval(
        hass,
        _async_tick,
        timedelta(hours=hours),
        name=f"{DOMAIN} vérification périodique",
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: AvatarExplorerConfigEntry
) -> bool:
    """Charge une entrée : état de synchro, entités, timer, première vérification."""
    state = SyncState(hass, entry.entry_id)
    await state.async_load()
    runtime = AvatarExplorerRuntime(
        state=state,
        sync=SyncManager(hass, entry, state),
        config_snapshot=_config_snapshot(entry),
    )
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_schedule_interval(hass, entry)
    entry.async_on_unload(runtime.async_cancel_interval)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    # Première vérification en tâche de fond : elle ne retarde pas le
    # démarrage et sera annulée si l'entrée est déchargée entre-temps.
    runtime.sync.async_request()
    return True


async def _async_entry_updated(
    hass: HomeAssistant, entry: AvatarExplorerConfigEntry
) -> None:
    """Réagit à une modification des données ou des options de l'entrée.

    Plutôt que des drapeaux posés par le flux d'options (que l'ancienne
    version consommait parfois AVANT l'enregistrement des nouvelles options,
    et synchronisait donc avec les anciennes valeurs), on compare l'entrée
    actuelle à l'instantané du passage précédent : c'est toujours exact,
    quel que soit l'ordre des mises à jour.
    """
    runtime = entry.runtime_data
    old = runtime.config_snapshot
    new = _config_snapshot(entry)
    runtime.config_snapshot = new

    if new["interval"] != old["interval"]:
        _LOGGER.info("Intervalle de vérification modifié : %s h", new["interval"])
        _async_schedule_interval(hass, entry)

    # ID Bitmoji ou qualité modifiés : les fichiers générés portent les mêmes
    # noms mais un contenu différent, donc le différentiel les sauterait tous :
    # il faut tout réécrire.
    if new["ids"] != old["ids"] or new["scale"] != old["scale"]:
        _LOGGER.info("ID Bitmoji ou qualité modifiés : réimport complet déclenché")
        runtime.sync.async_request(force=True, refresh_all=True)
    # Langue modifiée : les titres étant traduits, les noms de fichiers
    # changent. Le différentiel suffit, mais il faut forcer un passage car
    # l'horodatage du catalogue distant, lui, n'a pas bougé.
    elif new["lang"] != old["lang"]:
        _LOGGER.info("Langue modifiée : synchronisation déclenchée")
        runtime.sync.async_request(force=True)


async def async_unload_entry(
    hass: HomeAssistant, entry: AvatarExplorerConfigEntry
) -> bool:
    """Décharge une entrée (les tâches de fond sont annulées par HA)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # Écrit l'état en attente et bloque toute sauvegarde ultérieure : sinon
        # la sauvegarde différée de cette instance pourrait recréer le fichier
        # après async_remove_entry (entrée supprimée juste après un passage).
        await entry.runtime_data.state.async_close()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: AvatarExplorerConfigEntry
) -> None:
    """Supprime l'état de synchro persistant d'une entrée supprimée.

    Les images, elles, restent dans www/ : elles appartiennent à l'utilisateur.
    """
    await SyncState(hass, entry.entry_id).async_remove()

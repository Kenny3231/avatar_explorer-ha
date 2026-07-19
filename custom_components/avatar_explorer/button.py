"""Boutons de synchronisation manuelle du catalogue Avatar Explorer."""

import logging

from homeassistant.components.button import ButtonEntity

from . import catalog
from .const import DOMAIN, SYSTEM_DEVICE_ID

_LOGGER = logging.getLogger(__name__)

SYSTEM_DEVICE_INFO = {
    "identifiers": {(DOMAIN, SYSTEM_DEVICE_ID)},
    "name": "Avatar Explorer",
    "manufacturer": "Avatar Explorer",
    "model": "Système",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        AvatarSyncButton(hass, entry),
        AvatarFullReimportButton(hass, entry),
        AvatarCleanupButton(hass, entry),
    ])


class _BaseSyncButton(ButtonEntity):
    _attr_should_poll = False

    def __init__(self, hass, entry):
        self._hass = hass
        self._entry = entry

    @property
    def device_info(self):
        return SYSTEM_DEVICE_INFO


class AvatarSyncButton(_BaseSyncButton):
    """Relance une vérification immédiate, sans attendre l'intervalle."""

    _attr_icon = "mdi:cloud-sync"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.entity_id = "button.avatar_explorer_sync"
        self._attr_name = "Avatar Explorer Synchroniser maintenant"
        self._attr_unique_id = f"{DOMAIN}_sync_button_{entry.entry_id}"

    async def async_press(self) -> None:
        _LOGGER.debug("Synchronisation manuelle demandée")
        await catalog.async_check_for_update(self._hass, self._entry, force=True)


class AvatarFullReimportButton(_BaseSyncButton):
    """Réécrit tout le catalogue, y compris les fichiers déjà présents.

    Utile si des images ont été corrompues ou modifiées localement : la synchro
    normale se fie à l'existence du fichier et ne les remplacerait pas.
    """

    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.entity_id = "button.avatar_explorer_reimport_complet"
        self._attr_name = "Avatar Explorer Réimport complet"
        self._attr_unique_id = f"{DOMAIN}_reimport_button_{entry.entry_id}"

    async def async_press(self) -> None:
        _LOGGER.info("Réimport complet demandé : tous les fichiers seront réécrits")
        await catalog.async_check_for_update(
            self._hass, self._entry, force=True, refresh_all=True
        )


class AvatarCleanupButton(_BaseSyncButton):
    """Supprime les images locales qui ne sont plus au catalogue.

    Action destructive, donc désactivée par défaut dans le registre : elle doit
    être activée sciemment. Le recensement des orphelins est refait au moment du
    clic, et les images encore utilisées comme avatar sont épargnées.
    """

    _attr_icon = "mdi:broom"
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.entity_id = "button.avatar_explorer_nettoyer_orphelins"
        self._attr_name = "Avatar Explorer Nettoyer les orphelins"
        self._attr_unique_id = f"{DOMAIN}_cleanup_button_{entry.entry_id}"

    async def async_press(self) -> None:
        _LOGGER.info("Nettoyage des orphelins demandé")
        deleted, protected, failed = await catalog.async_delete_orphans(
            self._hass, self._entry
        )
        _LOGGER.info(
            "Nettoyage : %s supprimé(s), %s protégé(s) car utilisé(s), %s échec(s)",
            deleted, protected, failed,
        )

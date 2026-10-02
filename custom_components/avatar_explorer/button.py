"""Boutons de synchronisation manuelle du catalogue Avatar Explorer.

Un appui rend la main immédiatement : la synchro (plusieurs minutes au
premier import) tourne en tâche de fond. L'ancienne version attendait la fin,
ce qui bloquait aussi les scripts et automatisations qui appuient dessus.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import SYSTEM_DEVICE_INFO
from .runtime import AvatarExplorerConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AvatarExplorerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les boutons de l'entrée."""
    async_add_entities(
        [
            AvatarSyncButton(entry),
            AvatarFullReimportButton(entry),
            AvatarCleanupButton(entry),
        ]
    )


class _BaseSyncButton(ButtonEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_info = SYSTEM_DEVICE_INFO

    def __init__(self, entry: AvatarExplorerConfigEntry) -> None:
        self._entry = entry


class AvatarSyncButton(_BaseSyncButton):
    """Relance une vérification immédiate, sans attendre l'intervalle."""

    _attr_icon = "mdi:cloud-sync"

    def __init__(self, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le bouton (identifiants historiques)."""
        super().__init__(entry)
        self.entity_id = "button.avatar_explorer_sync"
        self._attr_name = "Avatar Explorer Synchroniser maintenant"
        self._attr_unique_id = f"{DOMAIN}_sync_button_{entry.entry_id}"

    async def async_press(self) -> None:
        """Demande une synchro forcée, en tâche de fond."""
        _LOGGER.debug("Synchronisation manuelle demandée")
        self._entry.runtime_data.sync.async_request(force=True)


class AvatarFullReimportButton(_BaseSyncButton):
    """Réécrit tout le catalogue, y compris les fichiers déjà présents.

    Utile si des images ont été corrompues ou modifiées localement : la synchro
    normale se fie à l'existence du fichier et ne les remplacerait pas.
    """

    _attr_icon = "mdi:cloud-refresh"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le bouton (identifiants historiques)."""
        super().__init__(entry)
        self.entity_id = "button.avatar_explorer_reimport_complet"
        self._attr_name = "Avatar Explorer Réimport complet"
        self._attr_unique_id = f"{DOMAIN}_reimport_button_{entry.entry_id}"

    async def async_press(self) -> None:
        """Demande un réimport complet, en tâche de fond."""
        _LOGGER.info("Réimport complet demandé : tous les fichiers seront réécrits")
        self._entry.runtime_data.sync.async_request(force=True, refresh_all=True)


class AvatarCleanupButton(_BaseSyncButton):
    """Supprime les images locales qui ne sont plus au catalogue.

    Action destructive, donc désactivée par défaut dans le registre : elle doit
    être activée sciemment. Le recensement des orphelins est refait au moment du
    clic, et les images encore utilisées comme avatar sont épargnées.
    """

    _attr_icon = "mdi:broom"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le bouton (identifiants historiques)."""
        super().__init__(entry)
        self.entity_id = "button.avatar_explorer_nettoyer_orphelins"
        self._attr_name = "Avatar Explorer Nettoyer les orphelins"
        self._attr_unique_id = f"{DOMAIN}_cleanup_button_{entry.entry_id}"

    async def async_press(self) -> None:
        """Lance le nettoyage en tâche de fond."""
        _LOGGER.info("Nettoyage des orphelins demandé")
        self._entry.async_create_background_task(
            self.hass,
            self._async_cleanup(),
            f"{DOMAIN} nettoyage des orphelins",
        )

    async def _async_cleanup(self) -> None:
        (
            deleted,
            protected,
            failed,
        ) = await self._entry.runtime_data.sync.async_delete_orphans()
        _LOGGER.info(
            "Nettoyage : %s supprimé(s), %s protégé(s) car utilisé(s), %s échec(s)",
            deleted,
            protected,
            failed,
        )

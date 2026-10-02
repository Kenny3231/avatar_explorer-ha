"""Capteurs Avatar Explorer : un par utilisateur, plus ceux de la synchro.

Les unique_id et entity_id sont ceux des versions précédentes et ne doivent
pas changer : ils sont dans le registre d'entités, et la carte découvre les
utilisateurs par le suffixe « _dynamique ».
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .catalog import normalize_dir
from .const import (
    CONF_DIR,
    CONF_HA_PERSON,
    CONF_LABEL,
    CONF_USER_FOLDER,
    CONF_USERS,
    DEFAULT_DIR,
    DOMAIN,
    IMAGE_PATH_PATTERN,
    STATUS_ERROR,
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    STATUS_UP_TO_DATE,
    SYNC_STATUSES,
    sync_signal,
)
from .entity import SYSTEM_DEVICE_INFO, user_device_info
from .runtime import AvatarExplorerConfigEntry, SyncState, sync_sensor_unique_id

# Valeur affichée quand la personne liée est absente ou inconnue (historique).
UNKNOWN_PERSON_STATE = "Inconnu"

_IMAGE_PATH_RE = re.compile(IMAGE_PATH_PATTERN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AvatarExplorerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs de l'entrée."""
    web_dir = entry.data.get(CONF_DIR, DEFAULT_DIR)
    state = entry.runtime_data.state

    entities: list[SensorEntity] = [
        AvatarUserSensor(user, web_dir) for user in entry.data.get(CONF_USERS, [])
    ]
    entities.append(AvatarSyncSensor(state, entry))
    entities.append(AvatarSyncStatusSensor(state, entry))
    entities.append(AvatarLastSyncSensor(state, entry))
    async_add_entities(entities)


class AvatarUserSensor(SensorEntity):
    """Présence de l'utilisateur (personne HA liée) et avatar courant."""

    _attr_should_poll = False

    def __init__(self, user_config: dict[str, Any], web_dir: str) -> None:
        """Initialise le capteur d'un utilisateur."""
        # On garde l'ID exact pour le dossier
        self._folder_id: str = user_config.get(CONF_USER_FOLDER, "Unknown")
        self._label: str = user_config.get(CONF_LABEL, "Inconnu")
        self._ha_person: str | None = user_config.get(CONF_HA_PERSON)
        self._web_dir = web_dir

        # Identifiants système toujours en minuscules
        self._id_clean = self._folder_id.lower()
        self.entity_id = f"sensor.{self._id_clean}_dynamique"
        self._attr_name = f"{self._label} Dynamique"
        self._attr_unique_id = f"{DOMAIN}_sensor_{self._id_clean}"
        # Identique à text.py, pour regrouper les entités sur le même device.
        self._attr_device_info = user_device_info(self._id_clean, self._label)
        self._attr_extra_state_attributes = {
            # Normalisé (sans « / » de début ni de fin) : la carte construit
            # /local/<directory>/<dossier>/<pose>.png, qui doit respecter
            # IMAGE_PATH_PATTERN. Une ancienne entrée stockée en
            # « /images/avatar/ » produisait sinon « /local//images/... ».
            "directory": normalize_dir(self._web_dir) or self._web_dir,
            # On transmet l'ID avec MAJUSCULES à la carte
            "folder_id": self._folder_id,
        }

    @property
    def _avatar_entity_id(self) -> str:
        """Entité text portant l'avatar (retrouvée par unique_id si renommée)."""
        return er.async_get(self.hass).async_get_entity_id(
            "text", DOMAIN, f"{DOMAIN}_avatar_{self._id_clean}"
        ) or (f"text.avatar_{self._id_clean}")

    @property
    def native_value(self) -> str:
        """État de la personne HA liée."""
        if self._ha_person:
            person = self.hass.states.get(self._ha_person)
            return person.state if person else UNKNOWN_PERSON_STATE
        return UNKNOWN_PERSON_STATE

    @property
    def entity_picture(self) -> str | None:
        """Avatar courant, lu dans l'entité text de l'utilisateur.

        Revalidé ici aussi : entity_picture finit dans un <img src> du
        frontend, et l'entité lue peut, en repli, ne pas être la nôtre.
        """
        avatar = self.hass.states.get(self._avatar_entity_id)
        if avatar is None or not _IMAGE_PATH_RE.fullmatch(avatar.state):
            return None
        return avatar.state

    async def async_added_to_hass(self) -> None:
        """Suit la personne liée et l'avatar plutôt que de les sonder."""
        tracked = [self._avatar_entity_id]
        if self._ha_person:
            tracked.append(self._ha_person)

        @callback
        def _async_tracked_changed(_event: Event[EventStateChangedData]) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, tracked, _async_tracked_changed)
        )


class _SyncSensorBase(SensorEntity):
    """Base des capteurs qui affichent l'état de synchro.

    Ils ne font aucun appel réseau : ils lisent SyncState et se redessinent
    sur le signal de l'entrée. Désactiver l'un d'eux n'a aucun effet sur la
    synchro elle-même.
    """

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_info = SYSTEM_DEVICE_INFO

    def __init__(self, state: SyncState, entry: AvatarExplorerConfigEntry) -> None:
        self._state = state
        self._entry = entry

    async def async_added_to_hass(self) -> None:
        """Se redessine à chaque changement d'état de la synchro."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, sync_signal(self._entry.entry_id), self.async_write_ha_state
            )
        )


class AvatarSyncSensor(_SyncSensorBase):
    """Version du catalogue synchronisé et détails de la dernière synchro."""

    _attr_icon = "mdi:cloud-sync-outline"

    def __init__(self, state: SyncState, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le capteur maître (identifiants historiques)."""
        super().__init__(state, entry)
        self.entity_id = "sensor.avatar_explorer_sync"
        self._attr_name = "Avatar Explorer Synchronisation"
        self._attr_unique_id = sync_sensor_unique_id(entry.entry_id)

    @property
    def native_value(self) -> str | None:
        """Horodatage (ISO) du catalogue distant au dernier import complet."""
        return self._state.catalog_version

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributs historiques, plus catalog_dir pour la carte (mode Duo)."""
        raw_dir = self._entry.data.get(CONF_DIR, DEFAULT_DIR)
        return {
            **self._state.attrs,
            # Dossier du catalogue sous www/, sans « / » de début ni de fin :
            # la carte construit /local/<catalog_dir>/Duo/metadata_Duo.json.
            "catalog_dir": normalize_dir(raw_dir) or raw_dir,
        }


class AvatarSyncStatusSensor(_SyncSensorBase):
    """Résultat de la dernière vérification, et sa raison en cas d'échec."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = SYNC_STATUSES
    _attr_translation_key = "sync_status"

    def __init__(self, state: SyncState, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le capteur d'état (identifiants historiques)."""
        super().__init__(state, entry)
        self.entity_id = "sensor.avatar_explorer_sync_etat"
        self._attr_name = "Avatar Explorer État synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_status_{entry.entry_id}"

    @property
    def native_value(self) -> str:
        """Statut : inconnu, a_jour, partielle ou erreur."""
        status = self._state.attrs.get("status", STATUS_UNKNOWN)
        return status if status in SYNC_STATUSES else STATUS_UNKNOWN

    @property
    def icon(self) -> str:
        """Icône selon le statut."""
        status = self.native_value
        if status == STATUS_UP_TO_DATE:
            return "mdi:cloud-check-variant"
        if status == STATUS_PARTIAL:
            return "mdi:cloud-alert"
        if status == STATUS_ERROR:
            return "mdi:cloud-off-outline"
        return "mdi:cloud-question"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Détails du dernier passage."""
        attrs = self._state.attrs
        return {
            # "raison" n'est renseigné qu'en cas d'échec : c'est le message
            # d'erreur brut (aide.json injoignable, export en échec, etc.).
            "raison": attrs.get("error"),
            "telecharges": attrs.get("telecharges"),
            "deja_presents": attrs.get("deja_presents"),
            "echecs": attrs.get("echecs"),
            "total_catalogue": attrs.get("total_catalogue"),
            "orphelins": attrs.get("orphelins"),
            "orphelins_exemples": attrs.get("orphelins_exemples"),
        }


class AvatarLastSyncSensor(_SyncSensorBase):
    """Horodatage de la dernière vérification (réussie ou non)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, state: SyncState, entry: AvatarExplorerConfigEntry) -> None:
        """Initialise le capteur de date (identifiants historiques)."""
        super().__init__(state, entry)
        self.entity_id = "sensor.avatar_explorer_sync_date"
        self._attr_name = "Avatar Explorer Dernière synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_date_{entry.entry_id}"

    @property
    def native_value(self) -> datetime | None:
        """Dernière vérification ; device_class timestamp exige un datetime aware."""
        raw = self._state.attrs.get("last_checked")
        if not raw:
            return None
        return dt_util.parse_datetime(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dernière réussite et version du catalogue distant."""
        return {
            "derniere_reussite": self._state.attrs.get("last_success"),
            "catalogue_distant": self._state.catalog_version,
        }

import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN, SIGNAL_SYNC_UPDATED, SYSTEM_DEVICE_ID

_LOGGER = logging.getLogger(__name__)

# Device commun à toutes les entités de synchronisation.
SYSTEM_DEVICE_INFO = {
    "identifiers": {(DOMAIN, SYSTEM_DEVICE_ID)},
    "name": "Avatar Explorer",
    "manufacturer": "Avatar Explorer",
    "model": "Système",
}


async def async_setup_entry(hass, entry, async_add_entities):
    # Récupération sécurisée du dossier racine
    web_dir = entry.data.get("dir", "images/avatar")
    users = entry.data.get("users", [])

    entities = [AvatarUserSensor(hass, u, web_dir) for u in users]
    sync_sensor = AvatarSyncSensor(hass, entry)
    entities.append(sync_sensor)
    entities.append(AvatarSyncStatusSensor(sync_sensor, entry))
    entities.append(AvatarLastSyncSensor(sync_sensor, entry))
    async_add_entities(entities, True)

class AvatarUserSensor(SensorEntity):
    def __init__(self, hass, user_config, web_dir):
        self._hass = hass
        # On garde l'ID exact pour le dossier
        self._folder_id = user_config.get("user_id_folder", "Unknown") 
        self._label = user_config.get("label", "Inconnu")
        self._ha_person = user_config.get("ha_person")
        self._web_dir = web_dir
        
        # Identifiants système toujours en minuscules
        self._id_clean = self._folder_id.lower()
        self.entity_id = f"sensor.{self._id_clean}_dynamique"
        self._attr_name = f"{self._label} Dynamique"
        self._attr_unique_id = f"{DOMAIN}_sensor_{self._id_clean}"

    @property   
    def device_info(self):
        # CRUCIAL : Doit être identique à text.py pour grouper les entités
        return {
            "identifiers": {(DOMAIN, self._id_clean)},
            "name": self._label,
            "manufacturer": "Avatar Explorer",
            "model": "Avatar Person",
        }

    @property
    def state(self):
        if self._ha_person:
            p = self._hass.states.get(self._ha_person)
            return p.state if p else "Inconnu"
        return "Inconnu"

    @property
    def entity_picture(self):
        # On cherche l'image dans l'entité text (en minuscules)
        val = self._hass.states.get(f"text.avatar_{self._id_clean}")
        return val.state if val else None

    @property
    def extra_state_attributes(self):
        return {
            "directory": self._web_dir,
            "folder_id": self._folder_id # On transmet l'ID avec MAJUSCULES à la carte
        }


class AvatarSyncSensor(SensorEntity, RestoreEntity):
    """Suivi de la synchronisation avec le catalogue Avatar Explorer."""

    def __init__(self, hass, entry):
        self.entity_id = "sensor.avatar_explorer_sync"
        self._attr_name = "Avatar Explorer Synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_{entry.entry_id}"
        self._attr_native_value = None
        self._attrs = {
            "last_checked": None,
            "last_success": None,
            "status": "inconnu",
            "error": None,
            "telecharges": None,
            "deja_presents": None,
            "echecs": None,
            "total_catalogue": None,
        }

        hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["sync_entity"] = self

    @property
    def device_info(self):
        return SYSTEM_DEVICE_INFO

    @property
    def extra_state_attributes(self):
        return self._attrs

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state and state.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = state.state
            self._attrs.update({
                "last_checked": state.attributes.get("last_checked"),
                "last_success": state.attributes.get("last_success"),
                "status": state.attributes.get("status", "inconnu"),
                "error": state.attributes.get("error"),
            })

    def set_stats(self, downloaded, skipped, failures, total):
        """Compteurs du dernier import, pour voir d'un coup d'œil si la synchro
        différentielle fait son travail (deja_presents élevé = normal)."""
        self._attrs.update({
            "telecharges": downloaded,
            "deja_presents": skipped,
            "echecs": failures,
            "total_catalogue": total,
        })

    def mark_checked(self, status, error=None):
        self._attrs["last_checked"] = dt_util.now().isoformat()
        self._attrs["status"] = status
        self._attrs["error"] = error
        self.async_write_ha_state()
        # Réveille les entités d'affichage (état, date) qui lisent ce capteur.
        async_dispatcher_send(self.hass, SIGNAL_SYNC_UPDATED)

    def mark_synced(self, iso_value):
        self._attr_native_value = iso_value
        self._attrs["last_success"] = dt_util.now().isoformat()
        self.mark_checked("a_jour", None)


class _SyncChildSensor(SensorEntity):
    """Base des entités qui affichent l'état détenu par AvatarSyncSensor.

    Elles ne font aucun appel réseau : elles lisent le capteur maître et se
    redessinent sur SIGNAL_SYNC_UPDATED.
    """

    _attr_should_poll = False

    def __init__(self, sync_sensor, entry):
        self._sync = sync_sensor
        self._entry_id = entry.entry_id

    @property
    def device_info(self):
        return SYSTEM_DEVICE_INFO

    async def async_added_to_hass(self):
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SYNC_UPDATED, self.async_write_ha_state
            )
        )


class AvatarSyncStatusSensor(_SyncChildSensor):
    """Résultat de la dernière vérification, et sa raison en cas d'échec."""

    _attr_icon = "mdi:cloud-check-variant"

    def __init__(self, sync_sensor, entry):
        super().__init__(sync_sensor, entry)
        self.entity_id = "sensor.avatar_explorer_sync_etat"
        self._attr_name = "Avatar Explorer État synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_status_{entry.entry_id}"

    @property
    def native_value(self):
        return self._sync.extra_state_attributes.get("status", "inconnu")

    @property
    def icon(self):
        status = self.native_value
        if status == "a_jour":
            return "mdi:cloud-check-variant"
        if status == "partielle":
            return "mdi:cloud-alert"
        if status == "erreur":
            return "mdi:cloud-off-outline"
        return "mdi:cloud-question"

    @property
    def extra_state_attributes(self):
        attrs = self._sync.extra_state_attributes
        return {
            # "raison" n'est renseigné qu'en cas d'échec : c'est le message
            # d'erreur brut (aide.json injoignable, export en échec, etc.).
            "raison": attrs.get("error"),
            "telecharges": attrs.get("telecharges"),
            "deja_presents": attrs.get("deja_presents"),
            "echecs": attrs.get("echecs"),
            "total_catalogue": attrs.get("total_catalogue"),
        }


class AvatarLastSyncSensor(_SyncChildSensor):
    """Horodatage de la dernière vérification (réussie ou non)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, sync_sensor, entry):
        super().__init__(sync_sensor, entry)
        self.entity_id = "sensor.avatar_explorer_sync_date"
        self._attr_name = "Avatar Explorer Dernière synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_date_{entry.entry_id}"

    @property
    def native_value(self):
        raw = self._sync.extra_state_attributes.get("last_checked")
        if not raw:
            return None
        # device_class timestamp exige un datetime aware, pas une chaîne.
        return dt_util.parse_datetime(raw)

    @property
    def extra_state_attributes(self):
        attrs = self._sync.extra_state_attributes
        return {
            "derniere_reussite": attrs.get("last_success"),
            "catalogue_distant": self._sync.native_value,
        }
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    # Récupération sécurisée du dossier racine
    web_dir = entry.data.get("dir", "images/avatar")
    users = entry.data.get("users", [])

    entities = [AvatarUserSensor(hass, u, web_dir) for u in users]
    entities.append(AvatarSyncSensor(hass, entry))
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
    """Suivi de la synchronisation avec le catalogue Pose Explorer."""

    def __init__(self, hass, entry):
        self.entity_id = "sensor.avatar_explorer_sync"
        self._attr_name = "Avatar Explorer Synchronisation"
        self._attr_unique_id = f"{DOMAIN}_sync_{entry.entry_id}"
        self._attr_native_value = None
        self._attrs = {"last_checked": None, "status": "inconnu", "error": None}

        hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["sync_entity"] = self

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "system")},
            "name": "Avatar Explorer",
            "manufacturer": "Avatar Explorer",
            "model": "Système",
        }

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
                "status": state.attributes.get("status", "inconnu"),
                "error": state.attributes.get("error"),
            })

    def mark_checked(self, status, error=None):
        self._attrs["last_checked"] = dt_util.now().isoformat()
        self._attrs["status"] = status
        self._attrs["error"] = error
        self.async_write_ha_state()

    def mark_synced(self, iso_value):
        self._attr_native_value = iso_value
        self.mark_checked("a_jour", None)
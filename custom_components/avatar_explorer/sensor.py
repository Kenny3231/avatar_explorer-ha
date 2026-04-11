import logging
from homeassistant.components.sensor import SensorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    # Récupération sécurisée du dossier racine
    web_dir = entry.data.get("dir", "images/avatar")
    users = entry.data.get("users", [])
    
    entities = [AvatarUserSensor(hass, u, web_dir) for u in users]
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
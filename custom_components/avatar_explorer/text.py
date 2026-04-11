from homeassistant.components.text import TextEntity
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    users = entry.data.get("users", [])
    entities = []
    for u in users:
        entities.append(AvatarTextEntity(u, "avatar"))
        entities.append(AvatarTextEntity(u, "emoji_recu"))
    async_add_entities(entities, True)

class AvatarTextEntity(TextEntity, RestoreEntity):
    def __init__(self, user_config, type_text):
        self._folder_id = user_config.get("user_id_folder", "Unknown")
        self._id_clean = self._folder_id.lower()
        self._label = user_config.get("label", "Inconnu")
        self._type = type_text
        
        self.entity_id = f"text.{self._type}_{self._id_clean}"
        self._attr_name = f"{self._type.replace('_', ' ').title()}"
        self._attr_unique_id = f"{DOMAIN}_{self._type}_{self._id_clean}"
        self._attr_native_value = ""

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._id_clean)},
            "name": self._label,
            "manufacturer": "Avatar Explorer",
            "model": "Avatar Person",
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state: self._attr_native_value = state.state

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
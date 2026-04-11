import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    
    async def handle_set_avatar(call: ServiceCall):
        user_id = call.data.get("user_id").lower()
        image_path = call.data.get("image_path")
        await hass.services.async_call("text", "set_value", {
            "entity_id": f"text.avatar_{user_id}",
            "value": image_path
        })

    async def handle_send_emoji(call: ServiceCall):
        from_label = call.data.get("from_label", "Duo")
        to_id = call.data.get("to_user").lower()
        image_path = call.data.get("image_path")
        notify_service = call.data.get("notify_service") # Ex: mobile_app_iphone_de_kenny

        # 1. Mise à jour de la tablette
        await hass.services.async_call("text", "set_value", {
            "entity_id": f"text.emoji_recu_{to_id}",
            "value": image_path
        })

        # 2. Envoi direct à l'équipement (si configuré dans la carte)
        if notify_service:
            # On enlève "notify." si l'utilisateur l'a laissé
            service_name = notify_service.replace("notify.", "")
            
            await hass.services.async_call("notify", service_name, {
                #"title": f"Message de {from_label}",                
                "title": f"Nouveau message",
                "message": "Tu as reçu un nouveau Emoji !",
                "data": {
                    "image": image_path
                    #"clickAction": "/lovelace-tablette/0"
                }
            })

    hass.services.async_register(DOMAIN, "set_avatar", handle_set_avatar)
    hass.services.async_register(DOMAIN, "send_emoji", handle_send_emoji)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "text"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "text"])
import logging
import os
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.components.http import StaticPathConfig
from .const import DOMAIN




_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    
    # 1. ENREGISTREMENT DE LA CARTE (Syntaxe calquée sur ton exemple)
    # L'URL sera : /avatar_explorer/avatar-card.js
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            "/local/avatar-card.js",
            hass.config.path("custom_components", DOMAIN, "avatar-card.js"),
            False
        )
    ])
    _LOGGER.debug("Registered static path for avatar-card.js")

    # 2. ENREGISTREMENT AUTOMATIQUE DANS LOVELACE
    if "lovelace" in hass.data:
        try:
            resources = hass.data["lovelace"].resources
            url = "/local/avatar-card.js"
            if resources and not any(res.get("url") == url for res in resources.async_items()):
                await resources.async_create_item({"res_type": "module", "url": url})
                _LOGGER.debug("Registered Lovelace resource for avatar-card.js")
        except Exception as e:
            _LOGGER.warning("Could not auto-register Lovelace resource: %s", e)

    # 3. DÉFINITION DES SERVICES (ACTIONS)
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
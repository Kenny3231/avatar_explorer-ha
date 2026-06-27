import logging
import os
from datetime import timedelta
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.http import StaticPathConfig
from . import pose_explorer
from .const import CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN




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

    async def handle_force_reimport(call: ServiceCall):
        for e in hass.config_entries.async_entries(DOMAIN):
            hass.async_create_task(pose_explorer.async_check_for_update(hass, e, force=True))

    hass.services.async_register(DOMAIN, "set_avatar", handle_set_avatar)
    hass.services.async_register(DOMAIN, "send_emoji", handle_send_emoji)
    hass.services.async_register(DOMAIN, "force_reimport", handle_force_reimport)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "text"])

    # 4. VÉRIFICATION PÉRIODIQUE DU CATALOGUE POSE EXPLORER
    def _schedule_interval():
        hours = entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        return async_track_time_interval(
            hass,
            lambda now: hass.async_create_task(pose_explorer.async_check_for_update(hass, entry)),
            timedelta(hours=hours),
        )

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["unsub_interval"] = _schedule_interval()
    hass.async_create_task(pose_explorer.async_check_for_update(hass, entry))

    async def _async_options_updated(hass, entry):
        data = hass.data[DOMAIN][entry.entry_id]
        if data.get("unsub_interval"):
            data["unsub_interval"]()
        data["unsub_interval"] = _schedule_interval()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and data.get("unsub_interval"):
        data["unsub_interval"]()
    return await hass.config_entries.async_unload_platforms(entry, ["sensor", "text"])

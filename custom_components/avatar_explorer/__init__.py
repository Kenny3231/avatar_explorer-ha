import logging
import os
from datetime import timedelta
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.http import StaticPathConfig
from . import catalog
from .const import CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN




_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "text", "button"]

CARD_URL = "/local/avatar-card.js"
# Clé volontairement hors de hass.data[DOMAIN] : ce dernier est vidé par entrée
# dans async_unload_entry, alors que le chemin statique, lui, reste enregistré
# jusqu'au redémarrage de Home Assistant.
CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:

    # 1. ENREGISTREMENT DE LA CARTE (Syntaxe calquée sur ton exemple)
    # L'URL sera : /avatar_explorer/avatar-card.js
    #
    # Le garde-fou CARD_REGISTERED_KEY est indispensable : async_register_static_paths
    # lève "Path already registered" si le même chemin est enregistré deux fois. Ça
    # arrive dès qu'on recharge l'intégration depuis l'UI, ou qu'on ajoute une
    # seconde entrée -- et l'exception ferait échouer tout async_setup_entry, donc
    # la carte ET les entités. Le drapeau est posé sur hass.data (portée globale,
    # pas par entrée) car le chemin statique l'est aussi.
    if not hass.data.get(CARD_REGISTERED_KEY):
        hass.data[CARD_REGISTERED_KEY] = True
        await hass.http.async_register_static_paths([
            StaticPathConfig(
                CARD_URL,
                hass.config.path("custom_components", DOMAIN, "avatar-card.js"),
                False
            )
        ])
        _LOGGER.debug("Registered static path for avatar-card.js")

        # 2. ENREGISTREMENT AUTOMATIQUE DANS LOVELACE
        if "lovelace" in hass.data:
            try:
                resources = hass.data["lovelace"].resources
                if resources and not any(res.get("url") == CARD_URL for res in resources.async_items()):
                    await resources.async_create_item({"res_type": "module", "url": CARD_URL})
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
            hass.async_create_task(catalog.async_check_for_update(hass, e, force=True))

    hass.services.async_register(DOMAIN, "set_avatar", handle_set_avatar)
    hass.services.async_register(DOMAIN, "send_emoji", handle_send_emoji)
    hass.services.async_register(DOMAIN, "force_reimport", handle_force_reimport)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 4. VÉRIFICATION PÉRIODIQUE DU CATALOGUE AVATAR EXPLORER
    def _schedule_interval():
        hours = entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        return async_track_time_interval(
            hass,
            lambda now: hass.async_create_task(catalog.async_check_for_update(hass, entry)),
            timedelta(hours=hours),
        )

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["unsub_interval"] = _schedule_interval()
    hass.async_create_task(catalog.async_check_for_update(hass, entry))

    async def _async_options_updated(hass, entry):
        data = hass.data[DOMAIN][entry.entry_id]
        if data.get("unsub_interval"):
            data["unsub_interval"]()
        data["unsub_interval"] = _schedule_interval()

        # Drapeaux posés par le flux d'options.
        #
        # pending_refresh_all : ID Bitmoji ou qualité modifiés. Les fichiers
        # générés portent les mêmes noms mais un contenu différent, donc le
        # différentiel les sauterait tous : il faut tout réécrire.
        if data.pop("pending_refresh_all", False):
            _LOGGER.info("ID Bitmoji ou qualité modifiés : réimport complet déclenché")
            hass.async_create_task(
                catalog.async_check_for_update(hass, entry, force=True, refresh_all=True)
            )
        # pending_resync : langue modifiée. Les titres étant traduits, les noms
        # de fichiers changent : le différentiel suffit, mais il faut forcer un
        # passage car l'horodatage du catalogue distant, lui, n'a pas bougé.
        elif data.pop("pending_resync", False):
            _LOGGER.info("Langue modifiée : synchronisation déclenchée")
            hass.async_create_task(
                catalog.async_check_for_update(hass, entry, force=True)
            )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and data.get("unsub_interval"):
            data["unsub_interval"]()
    return unloaded

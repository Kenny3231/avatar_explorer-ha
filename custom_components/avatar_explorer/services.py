"""Actions (services) de l'intégration Avatar Explorer.

Enregistrées une seule fois dans async_setup, et non plus à chaque entrée :
elles survivent ainsi au rechargement de l'entrée, et leurs schémas valident
les appels avant toute action. Les noms d'actions et de champs sont ceux
qu'appelle la carte (avatar-card.js) : ne pas les renommer.
"""

from __future__ import annotations

import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, IMAGE_PATH_PATTERN

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_AVATAR = "set_avatar"
SERVICE_SEND_EMOJI = "send_emoji"
SERVICE_FORCE_REIMPORT = "force_reimport"

ATTR_USER_ID = "user_id"
ATTR_IMAGE_PATH = "image_path"
ATTR_FROM_LABEL = "from_label"
ATTR_TO_USER = "to_user"
ATTR_NOTIFY_SERVICE = "notify_service"

# Longueur maximale des entités text (native_max).
MAX_IMAGE_PATH_LENGTH = 255
# /local/<dossier>/<utilisateur>/<fichier>.png, alphabet strict (voir
# IMAGE_PATH_PATTERN) : les noms de poses peuvent contenir des espaces
# (« Kenny__bonne nuit.png »), mais ni « . », ni « % », ni « ? », ni « # ».
# L'ancienne regex acceptait « /local/%2e%2e/%2e%2e/api/...?x=.png ».
IMAGE_PATH_RE = re.compile(IMAGE_PATH_PATTERN)

TEXT_KIND_AVATAR = "avatar"
TEXT_KIND_EMOJI = "emoji_recu"


def image_path(value: object) -> str:
    """Valide un chemin d'image servi par Home Assistant (/local/...png)."""
    path = cv.string(value).strip()
    if len(path) > MAX_IMAGE_PATH_LENGTH:
        raise vol.Invalid(f"image_path dépasse {MAX_IMAGE_PATH_LENGTH} caractères")
    if not IMAGE_PATH_RE.fullmatch(path):
        raise vol.Invalid(
            "image_path doit être de la forme /local/<dossier>/<utilisateur>/<pose>.png"
        )
    return path


def _optional_string(value: object) -> str | None:
    """La carte envoie null ou "" quand aucun service de notification n'est choisi."""
    if value is None:
        return None
    text = cv.string(value).strip()
    return text or None


SET_AVATAR_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_USER_ID): cv.string,
        vol.Required(ATTR_IMAGE_PATH): image_path,
    }
)

SEND_EMOJI_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_FROM_LABEL): _optional_string,
        vol.Required(ATTR_TO_USER): cv.string,
        vol.Required(ATTR_IMAGE_PATH): image_path,
        vol.Optional(ATTR_NOTIFY_SERVICE): _optional_string,
    }
)

FORCE_REIMPORT_SCHEMA = vol.Schema({})


def _text_entity_id(hass: HomeAssistant, kind: str, user_id: str) -> str:
    """entity_id de l'entité text d'un utilisateur.

    Recherché par unique_id dans le registre : si l'utilisateur a renommé
    l'entité, l'action continue de la trouver. L'entity_id historique sert de
    repli, mais seulement s'il appartient à cette intégration : sans ce
    contrôle, set_avatar(user_id="salon") écrivait dans text.avatar_salon
    d'une autre intégration.
    """
    clean = user_id.strip().lower()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("text", DOMAIN, f"{DOMAIN}_{kind}_{clean}")
    if entity_id is None:
        fallback = f"text.{kind}_{clean}"
        registry_entry = registry.async_get(fallback)
        if registry_entry is not None and registry_entry.platform == DOMAIN:
            entity_id = fallback
    if entity_id is None or hass.states.get(entity_id) is None:
        raise ServiceValidationError(
            f"Utilisateur Avatar Explorer inconnu : {user_id}",
            translation_domain=DOMAIN,
            translation_key="unknown_user",
            translation_placeholders={"user": user_id},
        )
    return entity_id


async def _async_set_avatar(call: ServiceCall) -> None:
    hass = call.hass
    entity_id = _text_entity_id(hass, TEXT_KIND_AVATAR, call.data[ATTR_USER_ID])
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": entity_id, "value": call.data[ATTR_IMAGE_PATH]},
        blocking=True,
    )


async def _async_send_emoji(call: ServiceCall) -> None:
    hass = call.hass
    image = call.data[ATTR_IMAGE_PATH]
    entity_id = _text_entity_id(hass, TEXT_KIND_EMOJI, call.data[ATTR_TO_USER])

    # Validation complète AVANT d'agir : pas de mise à jour à moitié faite.
    notify_service: str | None = call.data.get(ATTR_NOTIFY_SERVICE)
    service_name: str | None = None
    if notify_service:
        # On enlève « notify. » si l'utilisateur l'a laissé (en tête
        # seulement : replace() le retirait n'importe où dans le nom).
        service_name = notify_service.removeprefix("notify.")
        if not hass.services.has_service("notify", service_name):
            raise ServiceValidationError(
                f"Service de notification introuvable : notify.{service_name}",
                translation_domain=DOMAIN,
                translation_key="unknown_notify_service",
                translation_placeholders={"service": f"notify.{service_name}"},
            )

    # 1. Mise à jour de la tablette
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity_id, "value": image}, blocking=True
    )

    # 2. Envoi direct à l'équipement (si configuré dans la carte)
    if service_name:
        _LOGGER.debug(
            "Emoji de %s envoyé via notify.%s",
            call.data.get(ATTR_FROM_LABEL),
            service_name,
        )
        await hass.services.async_call(
            "notify",
            service_name,
            {
                "title": "Nouveau message",
                "message": "Tu as reçu un nouveau Emoji !",
                "data": {"image": image},
            },
        )


async def _async_force_reimport(call: ServiceCall) -> None:
    entries = [
        entry
        for entry in call.hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError(
            "Aucune entrée Avatar Explorer chargée",
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    for entry in entries:
        entry.runtime_data.sync.async_request(force=True)


def async_setup_services(hass: HomeAssistant) -> None:
    """Enregistre les actions de l'intégration (une seule fois)."""
    hass.services.async_register(
        DOMAIN, SERVICE_SET_AVATAR, _async_set_avatar, schema=SET_AVATAR_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_EMOJI, _async_send_emoji, schema=SEND_EMOJI_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCE_REIMPORT,
        _async_force_reimport,
        schema=FORCE_REIMPORT_SCHEMA,
    )

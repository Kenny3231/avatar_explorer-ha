"""Mise à disposition de la carte Lovelace avatar-card.js.

La carte était autrefois servie sur /local/avatar-card.js. Ce chemin appartient
au dossier www/ de l'utilisateur : notre route le masquait, et l'URL ne
changeait jamais d'une version à l'autre, si bien que les navigateurs
gardaient l'ancienne carte en cache. Elle est désormais servie sous un préfixe
propre à l'intégration, avec la version du manifest en paramètre.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration
from yarl import URL

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "avatar-card.js"
CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"
# Ancienne URL, à migrer dans les ressources Lovelace existantes.
LEGACY_CARD_URL_PATH = f"/local/{CARD_FILENAME}"
_OUR_PATHS = frozenset({CARD_URL_PATH, LEGACY_CARD_URL_PATH})

# Clé volontairement hors de toute entrée : la route statique reste
# enregistrée jusqu'au redémarrage de Home Assistant, même si l'entrée est
# rechargée ou supprimée. aiohttp lève une erreur si on l'enregistre deux fois.
CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"

# Issue de réparation affichée en mode YAML tant que la ressource n'est pas à
# jour dans configuration.yaml.
ISSUE_YAML_RESOURCE = "lovelace_yaml_resource"


def _is_our_card(url: str) -> bool:
    """Vrai pour une ressource qui pointe vers NOTRE carte (URL relative).

    Une URL absolue (« https://cdn.example.com/local/avatar-card.js ») est une
    autre carte, hébergée ailleurs : la migrer ou la supprimer comme doublon
    toucherait une ressource que l'utilisateur a ajoutée lui-même.
    """
    try:
        parsed = URL(url)
    except (ValueError, TypeError):
        return False
    return not parsed.is_absolute() and parsed.path in _OUR_PATHS


async def async_register_card(hass: HomeAssistant) -> None:
    """Sert la carte et l'inscrit (ou la migre) dans les ressources Lovelace."""
    integration = await async_get_integration(hass, DOMAIN)
    card_url = f"{CARD_URL_PATH}?v={integration.version}"

    if not hass.data.get(CARD_REGISTERED_KEY):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    CARD_URL_PATH,
                    str(Path(__file__).parent / CARD_FILENAME),
                    cache_headers=False,
                )
            ]
        )
        hass.data[CARD_REGISTERED_KEY] = True
        _LOGGER.debug("Carte Avatar Explorer servie sur %s", CARD_URL_PATH)

    await _async_register_resource(hass, card_url)


async def _async_register_resource(hass: HomeAssistant, card_url: str) -> None:
    lovelace: Any = hass.data.get("lovelace")
    if lovelace is None:
        _LOGGER.debug("Lovelace indisponible : ressource de la carte non enregistrée")
        return

    # LovelaceData.resource_mode depuis 2025 ; « mode » sur les versions antérieures.
    mode = getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None))
    if mode == "yaml":
        _async_check_yaml_resource(hass, lovelace, card_url)
        return
    # Repassé en mode stockage : la ressource est gérée ici, l'issue n'a plus
    # lieu d'être.
    ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML_RESOURCE)

    resources = getattr(lovelace, "resources", None)
    if resources is None:
        return

    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True

        ours = [
            item
            for item in resources.async_items()
            if _is_our_card(item.get("url", ""))
        ]
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": card_url})
            _LOGGER.info(
                "Ressource Lovelace de la carte Avatar Explorer créée : %s", card_url
            )
            return

        # Migration : l'ancienne ressource /local/avatar-card.js est mise à jour
        # sur place (même id, donc aucun tableau de bord à retoucher).
        first, *duplicates = ours
        if first.get("url") != card_url:
            await resources.async_update_item(
                first["id"], {"res_type": "module", "url": card_url}
            )
            _LOGGER.info(
                "Ressource Lovelace de la carte Avatar Explorer migrée : %s -> %s",
                first.get("url"),
                card_url,
            )
        # Deux ressources pour la même carte la chargeraient deux fois, et le
        # second customElements.define planterait.
        for item in duplicates:
            await resources.async_delete_item(item["id"])
            _LOGGER.info("Ressource Lovelace en double supprimée : %s", item.get("url"))
    except (HomeAssistantError, KeyError, ValueError, vol.Invalid) as err:
        _LOGGER.warning(
            "Impossible d'enregistrer la ressource Lovelace de la carte (%s). "
            "Ajoutez-la à la main : %s (module).",
            err,
            card_url,
        )


def _async_check_yaml_resource(
    hass: HomeAssistant, lovelace: Any, card_url: str
) -> None:
    """Mode YAML : on ne peut pas modifier les ressources, on le signale.

    Une simple ligne de journal passait inaperçue : après la mise à jour,
    l'ancienne URL /local/avatar-card.js renvoie 404 et la carte disparaît des
    tableaux de bord. Une issue de réparation indique la nouvelle URL ; elle
    est retirée dès que configuration.yaml contient l'URL de cette version.
    """
    resources = getattr(lovelace, "resources", None)
    try:
        urls = [item.get("url", "") for item in resources.async_items() or []]
    except AttributeError:
        urls = []
    if card_url in urls:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML_RESOURCE)
        return
    _LOGGER.warning(
        "Lovelace est en mode YAML : remplacez la ressource de la carte Avatar "
        "Explorer par %s (type: module) dans configuration.yaml",
        card_url,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_YAML_RESOURCE,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_YAML_RESOURCE,
        translation_placeholders={
            "url": card_url,
            "legacy_url": LEGACY_CARD_URL_PATH,
        },
    )

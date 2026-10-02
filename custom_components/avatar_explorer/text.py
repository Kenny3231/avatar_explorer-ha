"""Entités text : avatar affiché et dernier emoji reçu, par utilisateur.

Les entity_id (text.avatar_<user>, text.emoji_recu_<user>) et les unique_id
sont ceux des versions précédentes : la carte et les actions s'en servent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_LABEL, CONF_USER_FOLDER, CONF_USERS, DOMAIN, IMAGE_PATH_PATTERN
from .entity import user_device_info
from .runtime import AvatarExplorerConfigEntry

_LOGGER = logging.getLogger(__name__)

# Un chemin duo (/local/images/avatar/Duo/Kenny__Lea__bonne nuit_2.png)
# dépassait l'ancienne limite de 100 caractères.
MAX_VALUE_LENGTH = 255
# Les deux entités (avatar et emoji reçu) portent le même format : le chemin
# /local/... d'une pose, envoyé par set_avatar ou send_emoji.
TEXT_KINDS = ("avatar", "emoji_recu")

# IMAGE_PATH_PATTERN, plus la chaîne vide : c'est la valeur initiale d'une
# entité neuve (« aucun avatar choisi »), et l'état serait sinon refusé par
# TextEntity.state. Sert d'_attr_pattern : text.set_value appelé directement
# est validé par Home Assistant avant d'arriver ici.
TEXT_VALUE_PATTERN = rf"^(?:{IMAGE_PATH_PATTERN[1:-1]})?$"
_IMAGE_PATH_RE = re.compile(IMAGE_PATH_PATTERN)


def is_valid_value(value: str) -> bool:
    """Vide, ou chemin de pose conforme (fullmatch, contrairement à HA).

    Home Assistant valide _attr_pattern avec re.match : « $ » y accepte un
    retour à la ligne final. fullmatch le refuse.
    """
    return value == "" or _IMAGE_PATH_RE.fullmatch(value) is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AvatarExplorerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée deux entités text par utilisateur."""
    async_add_entities(
        AvatarTextEntity(user, kind)
        for user in entry.data.get(CONF_USERS, [])
        for kind in TEXT_KINDS
    )


class AvatarTextEntity(TextEntity, RestoreEntity):
    """Chemin /local/... d'une image choisie dans la carte."""

    _attr_should_poll = False
    _attr_native_max = MAX_VALUE_LENGTH
    _attr_pattern = TEXT_VALUE_PATTERN

    def __init__(self, user_config: dict[str, Any], kind: str) -> None:
        """Initialise l'entité d'un utilisateur."""
        folder_id: str = user_config.get(CONF_USER_FOLDER, "Unknown")
        id_clean = folder_id.lower()
        label: str = user_config.get(CONF_LABEL, "Inconnu")

        self.entity_id = f"text.{kind}_{id_clean}"
        self._attr_name = kind.replace("_", " ").title()
        self._attr_unique_id = f"{DOMAIN}_{kind}_{id_clean}"
        self._attr_native_value = ""
        self._attr_device_info = user_device_info(id_clean, label)

    async def async_added_to_hass(self) -> None:
        """Restaure la dernière valeur, si elle est encore valide."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        # Une valeur trop longue ou hors format ferait échouer chaque écriture
        # d'état ; elle a pu être enregistrée par une version plus permissive.
        if len(last.state) <= MAX_VALUE_LENGTH and is_valid_value(last.state):
            self._attr_native_value = last.state
        else:
            _LOGGER.warning(
                "Valeur restaurée ignorée pour %s (format invalide) : %r",
                self.entity_id,
                last.state[:80],
            )

    async def async_set_value(self, value: str) -> None:
        """Nouvelle image choisie."""
        if not is_valid_value(value):
            raise ServiceValidationError(
                f"Chemin d'image invalide : {value!r}",
                translation_domain=DOMAIN,
                translation_key="invalid_image_path",
                translation_placeholders={"value": repr(value[:80])},
            )
        self._attr_native_value = value
        self.async_write_ha_state()

"""Éléments communs aux entités Avatar Explorer."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, SYSTEM_DEVICE_ID, SYSTEM_DEVICE_NAME

# Device commun à toutes les entités de synchronisation (capteurs et boutons).
SYSTEM_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, SYSTEM_DEVICE_ID)},
    name=SYSTEM_DEVICE_NAME,
    manufacturer=MANUFACTURER,
    model="Système",
)


def user_device_info(id_clean: str, label: str) -> DeviceInfo:
    """Device d'un utilisateur, partagé par son capteur et ses entités text.

    Les identifiants doivent rester identiques d'une plateforme à l'autre,
    sinon les entités d'un même utilisateur se retrouvent sur deux devices.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, id_clean)},
        name=label,
        manufacturer=MANUFACTURER,
        model="Avatar Person",
    )

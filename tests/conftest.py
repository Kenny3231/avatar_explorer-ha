"""Fixtures communes aux tests Avatar Explorer."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.avatar_explorer.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

# Données identiques à celles d'une entrée de production (créée avant
# l'option duo_pair) : 24 h, scale entier, deux utilisateurs.
PROD_DATA: dict[str, Any] = {
    "dir": "images/avatar",
    "users": [
        {"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5", "label": "Kenny"},
        {
            "user_id_folder": "Lea",
            "bitmoji_id": "222_2-s5",
            "label": "Lea",
            "ha_person": "person.lea",
        },
    ],
}
PROD_OPTIONS: dict[str, Any] = {"update_interval_hours": 24, "scale": 1}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Active le chargement de custom_components/ dans tous les tests."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Entrée telle qu'elle existe chez l'utilisateur."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Avatar Explorer (images/avatar)",
        data=PROD_DATA,
        options=PROD_OPTIONS,
        entry_id="prod_entry",
    )


@pytest.fixture
def mock_run_sync() -> Generator[AsyncMock]:
    """Remplace le passage de synchro réseau par un mock."""
    with patch(
        "custom_components.avatar_explorer.catalog.async_run_sync",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock:
        yield mock

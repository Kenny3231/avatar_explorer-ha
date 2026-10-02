"""Tests du flux de configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.avatar_explorer.const import DOMAIN


async def test_full_flow_with_validation(
    hass: HomeAssistant, mock_run_sync: AsyncMock
) -> None:
    """Création complète, avec chaque validation déclenchée une fois."""
    hass.config.language = "en"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"dir": "../www"}
    )
    assert result["errors"] == {"dir": "invalid_dir"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"dir": "/images/avatar/"}
    )
    assert result["step_id"] == "add_user"

    for folder, bitmoji, errors in (
        ("Duo", "111_1-s5", {"user_id_folder": "reserved_folder"}),
        ("Ke nny", "111_1-s5", {"user_id_folder": "invalid_folder"}),
        ("Kenny", "111 1", {"bitmoji_id": "invalid_bitmoji_id"}),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"user_id_folder": folder, "bitmoji_id": bitmoji}
        )
        assert result["errors"] == errors

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"user_id_folder": "kenny", "bitmoji_id": "222_2-s5"}
    )
    assert result["errors"] == {"user_id_folder": "duplicate_folder"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"user_id_folder": "Lea", "bitmoji_id": "222_2-s5"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result["step_id"] == "duo_pair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"duo_user1": "Kenny", "duo_user2": "Lea"}
    )
    assert result["step_id"] == "settings"
    # Langue proposée : celle de Home Assistant, puisque le catalogue l'a.
    schema = result["data_schema"].schema
    lang_key = next(k for k in schema if k == "lang")
    assert lang_key.default() == "en"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"update_interval_hours": 12.0, "scale": "1", "lang": "en"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["dir"] == "images/avatar"
    assert result["data"]["duo_pair"] == ["Kenny", "Lea"]
    assert result["options"] == {
        "update_interval_hours": 12,
        "scale": "1",
        "lang": "en",
    }


async def test_unsupported_language_falls_back_to_french(hass: HomeAssistant) -> None:
    """Une langue absente du catalogue donne le français."""
    hass.config.language = "nl"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"dir": "images/avatar"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    lang_key = next(k for k in result["data_schema"].schema if k == "lang")
    assert lang_key.default() == "fr"


async def test_single_instance(hass: HomeAssistant) -> None:
    """single_config_entry : une seconde entrée est refusée."""
    MockConfigEntry(
        domain=DOMAIN, data={"dir": "images/avatar", "users": []}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

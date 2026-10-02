"""Tests du cycle de vie de l'intégration, du timer, des actions et des migrations."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.avatar_explorer import card
from custom_components.avatar_explorer.card import CARD_URL_PATH
from custom_components.avatar_explorer.const import DOMAIN

# Version lue dans le manifest : la coder en dur faisait échouer les tests de
# ressource Lovelace à chaque montée de version.
_MANIFEST = (
    Path(__file__).parent.parent / "custom_components" / DOMAIN / "manifest.json"
)
CARD_VERSION = json.loads(_MANIFEST.read_text(encoding="utf-8"))["version"]
CARD_URL = f"{CARD_URL_PATH}?v={CARD_VERSION}"


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, *, wait_background: bool = True
) -> None:
    """Charge l'entrée et attend la synchro de démarrage (tâche de fond).

    wait_background=False pour les tests dont la synchro reste bloquée exprès.
    """
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=wait_background)


# ---------------------------------------------------------------------------
# Setup / unload et compatibilité des identifiants
# ---------------------------------------------------------------------------


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """L'entrée de production se charge sans reconfiguration et se décharge."""
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    # entity_id historiques, dont dépend la carte.
    for entity_id in (
        "sensor.kenny_dynamique",
        "sensor.lea_dynamique",
        "text.avatar_kenny",
        "text.emoji_recu_lea",
        "sensor.avatar_explorer_sync",
        "sensor.avatar_explorer_sync_etat",
        "sensor.avatar_explorer_sync_date",
        "button.avatar_explorer_sync",
    ):
        assert hass.states.get(entity_id) is not None, entity_id

    # unique_id historiques.
    registry = er.async_get(hass)
    assert (
        registry.async_get("sensor.kenny_dynamique").unique_id
        == "avatar_explorer_sensor_kenny"
    )
    assert (
        registry.async_get("text.avatar_kenny").unique_id
        == "avatar_explorer_avatar_kenny"
    )
    assert (
        registry.async_get("sensor.avatar_explorer_sync").unique_id
        == "avatar_explorer_sync_prod_entry"
    )
    assert (
        registry.async_get("sensor.avatar_explorer_sync").entity_category
        == "diagnostic"
    )
    assert registry.async_get("button.avatar_explorer_sync").entity_category == "config"

    sync = hass.states.get("sensor.avatar_explorer_sync")
    assert sync.attributes["catalog_dir"] == "images/avatar"
    assert hass.states.get("sensor.kenny_dynamique").attributes["folder_id"] == "Kenny"

    # Première vérification lancée en tâche de fond au démarrage.
    mock_run_sync.assert_awaited_once()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_user_sensor_follows_person_without_polling(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Le capteur utilisateur suit la personne liée et l'avatar par événement."""
    hass.states.async_set("person.lea", "home")
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.lea_dynamique").state == "home"

    hass.states.async_set("person.lea", "not_home")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lea_dynamique").state == "not_home"

    await hass.services.async_call(
        DOMAIN,
        "set_avatar",
        {"user_id": "Lea", "image_path": "/local/images/avatar/Lea/Lea__coucou.png"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.lea_dynamique").attributes["entity_picture"]
        == "/local/images/avatar/Lea/Lea__coucou.png"
    )


# ---------------------------------------------------------------------------
# Timer périodique (alerte 4)
# ---------------------------------------------------------------------------


async def test_periodic_check_fires(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Après 24 h, une vérification part (elle ne partait jamais avant)."""
    await _setup(hass, config_entry)
    mock_run_sync.reset_mock()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=24, seconds=1))
    await hass.async_block_till_done()
    mock_run_sync.assert_awaited_once()
    assert mock_run_sync.await_args.kwargs == {"force": False, "refresh_all": False}

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=48, seconds=2))
    await hass.async_block_till_done()
    assert mock_run_sync.await_count == 2


async def test_out_of_range_interval_is_clamped(
    hass: HomeAssistant, mock_run_sync: AsyncMock
) -> None:
    """Une entrée existante avec un intervalle à 0 ne crée pas de boucle serrée."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"dir": "images/avatar", "users": []},
        options={"update_interval_hours": 0},
    )
    await _setup(hass, entry)
    mock_run_sync.reset_mock()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=30))
    await hass.async_block_till_done()
    mock_run_sync.assert_not_awaited()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, seconds=1))
    await hass.async_block_till_done()
    mock_run_sync.assert_awaited_once()


# ---------------------------------------------------------------------------
# File de synchro (N2) et options (N4)
# ---------------------------------------------------------------------------


async def test_concurrent_requests_are_not_lost(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Une demande de réimport pendant une synchro est rejouée ensuite."""
    release = asyncio.Event()
    calls: list[dict[str, Any]] = []

    async def _slow_sync(*_args: Any, **kwargs: Any) -> bool:
        calls.append(kwargs)
        if len(calls) == 1:
            await release.wait()
        return True

    mock_run_sync.side_effect = _slow_sync
    await _setup(hass, config_entry, wait_background=False)
    sync = config_entry.runtime_data.sync
    assert sync.busy

    # Pendant le passage de démarrage : deux demandes, cumulées.
    sync.async_request(refresh_all=True)
    task = sync.async_request(force=True)
    release.set()
    await task

    assert calls == [
        {"force": False, "refresh_all": False},
        {"force": True, "refresh_all": True},
    ]
    assert not config_entry.runtime_data.state.refresh_all_pending


async def test_failed_full_reimport_stays_pending(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Réimport complet arrêté AVANT les téléchargements : il reste dû.

    C'est le cas d'un catalogue ou d'une API export injoignables : rien n'a été
    réécrit, le réimport doit être refait en entier au passage suivant.
    """
    await _setup(hass, config_entry)
    runtime = config_entry.runtime_data

    mock_run_sync.return_value = False
    await runtime.sync.async_request(force=True, refresh_all=True)
    assert runtime.state.refresh_all_pending

    mock_run_sync.return_value = True
    await runtime.sync.async_request()
    assert mock_run_sync.await_args.kwargs["refresh_all"] is True
    assert not runtime.state.refresh_all_pending


async def test_partial_full_reimport_not_relaunched(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Réimport complet mené à terme mais partiel : il n'est PAS relancé en entier.

    Avant, un seul fichier en échec relançait les ~400 Mo à chaque passage.
    Seuls les fichiers en échec restent dus (retry_paths), et survivent à un
    redémarrage.
    """
    await _setup(hass, config_entry)
    runtime = config_entry.runtime_data
    failed = "images/avatar/Kenny/Kenny__recalcitrant.png"

    async def _partial(_hass: HomeAssistant, _entry: Any, state: Any, **_kw: Any):
        # Ce que fait catalog.async_run_sync à la fin d'un réimport partiel.
        state.async_finish_full_refresh([failed])
        return False

    mock_run_sync.side_effect = _partial
    await runtime.sync.async_request(force=True, refresh_all=True)
    assert not runtime.state.refresh_all_pending
    assert runtime.state.retry_paths == [failed]

    mock_run_sync.side_effect = None
    mock_run_sync.return_value = True
    await runtime.sync.async_request()
    assert mock_run_sync.await_args.kwargs == {"force": False, "refresh_all": False}

    # Persisté : un rechargement retrouve la liste, sans réimport complet.
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.runtime_data.state.retry_paths == [failed]
    assert not config_entry.runtime_data.state.refresh_all_pending
    assert mock_run_sync.await_args.kwargs == {"force": False, "refresh_all": False}


async def test_options_change_uses_new_values(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Changer l'ID et la qualité déclenche UN réimport, avec les nouvelles options."""
    await _setup(hass, config_entry)
    mock_run_sync.reset_mock()
    seen: list[tuple[Any, str]] = []

    async def _capture(
        _hass: HomeAssistant, entry: Any, _state: Any, **kwargs: Any
    ) -> bool:
        seen.append((entry.options["scale"], entry.data["users"][0]["bitmoji_id"]))
        return True

    mock_run_sync.side_effect = _capture

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval_hours": 24,
            "scale": "2",
            "lang": "fr",
            "bitmoji_Kenny": "333_3-s5",
            "bitmoji_Lea": "222_2-s5",
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert seen == [("2", "333_3-s5")]
    assert mock_run_sync.await_args.kwargs == {"force": True, "refresh_all": True}


async def test_options_invalid_bitmoji_id(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Un ID Bitmoji invalide est refusé dans le formulaire d'options."""
    await _setup(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "update_interval_hours": 24,
            "scale": "1",
            "lang": "fr",
            "bitmoji_Kenny": "111 1",
            "bitmoji_Lea": "222_2-s5",
        },
    )
    assert result["type"] == "form"
    assert result["errors"] == {"bitmoji_Kenny": "invalid_bitmoji_id"}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


async def test_service_schemas(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Schémas : user_id requis, image_path validé, utilisateur inconnu refusé."""
    await _setup(hass, config_entry)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_avatar", {"image_path": "/local/a/b/c.png"}, blocking=True
        )
    for bad in (
        "/config/secrets.yaml",
        "/local/../secrets.png",
        "/local/x.jpg",
        "https://evil/x.png",
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN,
                "set_avatar",
                {"user_id": "Kenny", "image_path": bad},
                blocking=True,
            )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_avatar",
            {
                "user_id": "Inconnu",
                "image_path": "/local/images/avatar/Kenny/Kenny__a.png",
            },
            blocking=True,
        )

    # Appel tel que l'envoie la carte (casse du dossier, espaces dans le nom).
    await hass.services.async_call(
        DOMAIN,
        "set_avatar",
        {
            "user_id": "Kenny",
            "image_path": "/local/images/avatar/Kenny/Kenny__bonne nuit.png",
        },
        blocking=True,
    )
    assert (
        hass.states.get("text.avatar_kenny").state
        == "/local/images/avatar/Kenny/Kenny__bonne nuit.png"
    )


async def test_send_emoji(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """send_emoji : notify_service null accepté, préfixe retiré en tête seulement."""
    await _setup(hass, config_entry)
    notify_calls = async_mock_service(hass, "notify", "mobile_app_notify_lea")
    image = "/local/images/avatar/Duo/Kenny__Lea__calin.png"

    # La carte envoie notify_service: null quand rien n'est configuré.
    await hass.services.async_call(
        DOMAIN,
        "send_emoji",
        {
            "from_label": "Kenny",
            "to_user": "Lea",
            "image_path": image,
            "notify_service": None,
        },
        blocking=True,
    )
    assert hass.states.get("text.emoji_recu_lea").state == image
    assert not notify_calls

    await hass.services.async_call(
        DOMAIN,
        "send_emoji",
        {
            "to_user": "Lea",
            "image_path": image,
            "notify_service": "notify.mobile_app_notify_lea",
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(notify_calls) == 1
    assert notify_calls[0].data["data"] == {"image": image}

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "send_emoji",
            {"to_user": "Lea", "image_path": image, "notify_service": "absent"},
            blocking=True,
        )
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "send_emoji", {"image_path": image}, blocking=True
        )


async def test_force_reimport_service(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """force_reimport rend la main et lance une synchro forcée en tâche de fond."""
    await _setup(hass, config_entry)
    mock_run_sync.reset_mock()
    await hass.services.async_call(DOMAIN, "force_reimport", {}, blocking=True)
    await hass.async_block_till_done()
    assert mock_run_sync.await_args.kwargs == {"force": True, "refresh_all": False}


async def test_buttons_return_immediately(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Le bouton rend la main pendant que la synchro tourne (N3)."""
    release = asyncio.Event()

    async def _slow(*_args: Any, **_kwargs: Any) -> bool:
        await release.wait()
        return True

    await _setup(hass, config_entry)
    mock_run_sync.side_effect = _slow
    await asyncio.wait_for(
        hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.avatar_explorer_sync"},
            blocking=True,
        ),
        timeout=5,
    )
    assert config_entry.runtime_data.sync.busy
    release.set()
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


async def test_lovelace_resource_migrated(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    config_entry: MockConfigEntry,
    mock_run_sync: AsyncMock,
) -> None:
    """L'ancienne ressource /local/avatar-card.js est mise à jour sur place."""
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": "res_card", "type": "module", "url": "/local/avatar-card.js"},
                {"id": "res_autre", "type": "module", "url": "/local/autre-carte.js"},
            ]
        },
    }
    await _setup(hass, config_entry)

    resources = hass.data["lovelace"].resources
    items = {item["id"]: item["url"] for item in resources.async_items()}
    assert items == {"res_card": CARD_URL, "res_autre": "/local/autre-carte.js"}


async def test_lovelace_resource_created_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Sans ressource existante, une seule est créée, même après rechargement."""
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    urls = [item["url"] for item in hass.data["lovelace"].resources.async_items()]
    assert urls == [CARD_URL]


async def test_sync_state_migrated_from_restore_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    config_entry: MockConfigEntry,
    mock_run_sync: AsyncMock,
) -> None:
    """Premier démarrage : l'état de l'ancien capteur est repris, pas de retéléchargement."""
    mock_restore_cache(
        hass,
        [
            State(
                "sensor.avatar_explorer_sync",
                "2026-07-19T12:53:10Z",
                {
                    "last_checked": "2026-09-29T18:52:00+02:00",
                    "last_success": "2026-07-19T15:00:00+02:00",
                    "status": "a_jour",
                    "error": None,
                },
            )
        ],
    )
    await _setup(hass, config_entry)

    state = config_entry.runtime_data.state
    assert state.catalog_version == "2026-07-19T12:53:10Z"
    assert state.attrs["last_success"] == "2026-07-19T15:00:00+02:00"
    assert (
        hass_storage[f"{DOMAIN}.prod_entry"]["data"]["catalog_version"]
        == "2026-07-19T12:53:10Z"
    )
    assert (
        hass.states.get("sensor.avatar_explorer_sync").state == "2026-07-19T12:53:10Z"
    )
    # La vérification de démarrage n'est pas forcée : elle comparera les dates.
    assert mock_run_sync.await_args.kwargs == {"force": False, "refresh_all": False}


async def test_sync_works_with_sync_sensor_disabled(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Le capteur maître désactivé n'empêche plus la synchro."""
    config_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "avatar_explorer_sync_prod_entry",
        suggested_object_id="avatar_explorer_sync",
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.avatar_explorer_sync") is None
    mock_run_sync.assert_awaited_once()


# ---------------------------------------------------------------------------
# Relectures sécurité et conformité HA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "https://tracker.example/pixel.png",
        "javascript:alert(1)",
        "data:image/svg+xml,<svg onload=alert(1)>",
        "/local/%2e%2e/%2e%2e/api/camera_proxy/camera.porte?x=.png",
        "/local/x.png#.png",
        # Passe re.match de Home Assistant (« $ » avant un \n final), pas fullmatch.
        "/local/images/avatar/Kenny/Kenny__a.png\n",
    ],
)
async def test_text_set_value_validated(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_run_sync: AsyncMock,
    value: str,
) -> None:
    """text.set_value appelé directement est soumis à la même regex que les actions."""
    await _setup(hass, config_entry)
    for entity_id in ("text.avatar_kenny", "text.emoji_recu_kenny"):
        with pytest.raises((ValueError, ServiceValidationError)):
            await hass.services.async_call(
                "text",
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
            )
        assert hass.states.get(entity_id).state == ""
    assert hass.states.get("sensor.kenny_dynamique").attributes.get(
        "entity_picture"
    ) in (None, "")


async def test_text_pattern_exposed(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Le motif est publié (validation côté interface) et accepte les vrais noms."""
    await _setup(hass, config_entry)
    pattern = hass.states.get("text.avatar_kenny").attributes["pattern"]
    assert pattern.startswith("^(?:/local/")
    image = "/local/images/avatar/Duo/Kenny__Lea__bonne nuit_2.png"
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.emoji_recu_kenny", "value": image},
        blocking=True,
    )
    assert hass.states.get("text.emoji_recu_kenny").state == image


async def test_restore_invalid_value_ignored(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Une valeur restaurée hors format (ancienne version permissive) est ignorée."""
    mock_restore_cache(
        hass,
        [
            State("text.avatar_kenny", "https://tracker.example/pixel.png"),
            State("text.avatar_lea", "/local/images/avatar/Lea/Lea__coucou.png"),
        ],
    )
    await _setup(hass, config_entry)
    assert hass.states.get("text.avatar_kenny").state == ""
    assert hass.states.get("sensor.kenny_dynamique").attributes.get(
        "entity_picture"
    ) in (None, "")
    assert (
        hass.states.get("sensor.lea_dynamique").attributes["entity_picture"]
        == "/local/images/avatar/Lea/Lea__coucou.png"
    )


async def test_entity_picture_revalidated(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """entity_picture vaut None si l'état lu ne respecte pas le format."""
    await _setup(hass, config_entry)
    # Contourne l'entité (état forcé) : le capteur ne doit pas le relayer.
    hass.states.async_set("text.avatar_kenny", "javascript:alert(1)")
    await hass.async_block_till_done()
    assert (
        hass.states.get("sensor.kenny_dynamique").attributes.get("entity_picture")
        is None
    )


async def test_service_does_not_target_foreign_text_entity(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Le repli par entity_id n'atteint pas l'entité text d'une autre intégration."""
    await _setup(hass, config_entry)
    er.async_get(hass).async_get_or_create(
        "text", "autre_integration", "salon", suggested_object_id="avatar_salon"
    )
    hass.states.async_set("text.avatar_salon", "valeur_autre_integration")
    calls = async_mock_service(hass, "text", "set_value")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_avatar",
            {"user_id": "salon", "image_path": "/local/images/avatar/a/b.png"},
            blocking=True,
        )
    assert not calls
    assert hass.states.get("text.avatar_salon").state == "valeur_autre_integration"


@pytest.mark.parametrize(
    ("url", "ours"),
    [
        ("/local/avatar-card.js", True),
        ("/local/avatar-card.js?v=3", True),
        ("/avatar_explorer/avatar-card.js?v=1.2.0", True),
        ("https://cdn.example.com/local/avatar-card.js", False),
        ("https://other.example/avatar_explorer/avatar-card.js", False),
        ("//evil.example/local/avatar-card.js", False),
        ("/hacsfiles/avatar-card/avatar-card.js", False),
    ],
)
def test_is_our_card_relative_only(url: str, ours: bool) -> None:
    """Seules les URL relatives vers notre carte sont migrées ou dédoublonnées."""
    assert card._is_our_card(url) is ours


async def test_lovelace_yaml_mode_repair_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_run_sync: AsyncMock
) -> None:
    """Mode YAML : une issue de réparation indique la nouvelle URL de la carte."""
    assert await async_setup_component(
        hass,
        "lovelace",
        {
            "lovelace": {
                "resource_mode": "yaml",
                "resources": [{"url": "/local/avatar-card.js", "type": "module"}],
            }
        },
    )
    await _setup(hass, config_entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, card.ISSUE_YAML_RESOURCE)
    assert issue is not None
    assert issue.translation_key == "lovelace_yaml_resource"
    assert issue.translation_placeholders == {
        "url": CARD_URL,
        "legacy_url": "/local/avatar-card.js",
    }
    assert issue.severity is ir.IssueSeverity.WARNING
    # La ressource YAML n'est pas modifiée.
    urls = [i["url"] for i in hass.data["lovelace"].resources.async_items()]
    assert urls == ["/local/avatar-card.js"]

    # Ressource mise à jour dans configuration.yaml : l'issue disparaît.
    hass.data["lovelace"].resources.data[0]["url"] = CARD_URL
    await card.async_register_card(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, card.ISSUE_YAML_RESOURCE) is None


async def test_remove_entry_store_not_resurrected(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    config_entry: MockConfigEntry,
    mock_run_sync: AsyncMock,
) -> None:
    """Une sauvegarde différée ne recrée pas le fichier d'une entrée supprimée."""
    await _setup(hass, config_entry)
    config_entry.runtime_data.state.async_mark_checked("erreur", "test")
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert f"{DOMAIN}.prod_entry" not in hass_storage


async def test_unload_flushes_pending_state(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    config_entry: MockConfigEntry,
    mock_run_sync: AsyncMock,
) -> None:
    """Au déchargement (sans suppression), l'état en attente est écrit tout de suite."""
    await _setup(hass, config_entry)
    config_entry.runtime_data.state.async_mark_checked("erreur", "juste avant")
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass_storage[f"{DOMAIN}.prod_entry"]["data"]["error"] == "juste avant"

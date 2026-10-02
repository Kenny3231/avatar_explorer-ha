"""Tests de sécurité et de robustesse de catalog.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.avatar_explorer import catalog

BASE = "images/avatar"
# Dossiers autorisés d'une entrée Kenny + Lea (voir catalog.allowed_folders).
ALLOWED = frozenset({"Kenny", "Lea", "Duo"})
PNG = catalog.PNG_SIGNATURE + b"\x00" * 32
IMG_URL = "https://sdk.bitmoji.com/render/panel/10228764-111_1-s5-v1.png?transparent=1&palette=1&scale=1"


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dest",
    [
        # Contournement historique : relatif absolu après le préfixe.
        "/config/www//config/x",
        "/config/www//config/configuration.yaml",
        "/config/www/../x",
        "../x",
        "/config/www/images/avatar/Kenny/../../../../secrets.yaml",
        "/config/www/images/avatar/../secrets.yaml",
        "/config/www/images/avatar/./Kenny/x.png",
        "/config/www/images//avatar/Kenny/x.png",
        "/config/secrets.yaml",
        "/config/www/autre/Kenny/Kenny__x.png",  # hors du dossier configuré
        "/config/www/images/avatar/Kenny__x.png",  # pas de dossier utilisateur
        "/config/www/images/avatar/Kenny/sous/Kenny__x.png",  # trop profond
        "/config/www/images/avatar/Kenny/x.sh",  # extension
        "/config/www/images/avatar/Kenny/.htaccess",
        "/config/www/images/avatar/Ke nny/x.png",  # espace dans le dossier
        # Dossier frère non configuré : jamais touché, même sous www/<dir>/.
        "/config/www/images/avatar/backgrounds/mon_fond.png",
        "/config/www/images/avatar/kenny/Kenny__x.png",  # casse différente
        "/config/www/images/avatar/Kenny/x\\..\\y.png",
    ],
)
def test_safe_relative_path_refuses(dest: str) -> None:
    """Toute destination hors de www/<dir>/<dossier>/<fichier sûr> est refusée."""
    assert catalog.safe_relative_path(dest, BASE, ALLOWED) is None


@pytest.mark.parametrize(
    ("dest", "expected"),
    [
        (
            "/config/www/images/avatar/Kenny/Kenny__mignon.png",
            "images/avatar/Kenny/Kenny__mignon.png",
        ),
        # Les tags contiennent des espaces : ils doivent passer.
        (
            "/config/www/images/avatar/Kenny/Kenny__bonne nuit_2.png",
            "images/avatar/Kenny/Kenny__bonne nuit_2.png",
        ),
        (
            "/config/www/images/avatar/Duo/Kenny__Lea-2__calin.png",
            "images/avatar/Duo/Kenny__Lea-2__calin.png",
        ),
        (
            "/config/www/images/avatar/Duo/metadata_Duo.json",
            "images/avatar/Duo/metadata_Duo.json",
        ),
    ],
)
def test_safe_relative_path_accepts_api_names(dest: str, expected: str) -> None:
    """Les noms réellement produits par l'API sont acceptés."""
    assert catalog.safe_relative_path(dest, BASE, ALLOWED) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("images/avatar", "images/avatar"),
        ("/images/avatar/", "images/avatar"),
        ("bitmojis", "bitmojis"),
        ("images/../x", None),
        ("images//avatar", None),
        ("", None),
        ("images avatar", None),
        (None, None),
    ],
)
def test_normalize_dir(raw: object, expected: str | None) -> None:
    """Même règle que DIR_SAFE_PATTERN côté API."""
    assert catalog.normalize_dir(raw) == expected


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://sdk.bitmoji.com/render/panel/x.png",
        "https://evil.example/x.png",
        "https://sdk.bitmoji.com.evil.example/x.png",
        "https://user:pass@sdk.bitmoji.com/x.png",
        "https://sdk.bitmoji.com:8443/x.png",
        "https://192.168.1.1/x.png",
        "file:///config/secrets.yaml",
        "/relative.png",
    ],
)
def test_url_refused(url: str) -> None:
    """Liste blanche : HTTPS et hôtes connus uniquement."""
    assert not catalog.is_allowed_url(url)


@pytest.mark.parametrize(
    "url",
    [
        IMG_URL,
        "https://avatar-explorer.pages.dev/api/export?id1=a&type=json&targetUser=1",
    ],
)
def test_url_allowed(url: str) -> None:
    """Les deux hôtes du catalogue sont acceptés."""
    assert catalog.is_allowed_url(url)


# ---------------------------------------------------------------------------
# Script d'export
# ---------------------------------------------------------------------------


def test_parse_export_script_ignores_header_and_hostile_lines() -> None:
    """set -euo pipefail, commentaires et lignes hostiles sont ignorés sans erreur."""
    script = (
        "#!/bin/bash\r\n"
        "set -euo pipefail\n"
        "# Généré par Avatar Explorer\n"
        "echo '--- DEBUT DU TELECHARGEMENT ---'\n"
        f'wget -q -U "Mozilla/5.0" -O "/config/www/images/avatar/Kenny/Kenny__bonne nuit.png" "{IMG_URL}"\r\n'
        'wget -q -O "/config/www/images/avatar/Kenny/metadata_Kenny.json" '
        '"https://avatar-explorer.pages.dev/api/export?id1=111&type=json&targetUser=1"\n'
        # Hostiles : écriture hors de www/, hôte non autorisé, http.
        'wget -q -U "Mozilla/5.0" -O "/config/www//config/configuration.yaml" "https://sdk.bitmoji.com/x.png"\n'
        'wget -q -U "Mozilla/5.0" -O "/config/www/images/avatar/Kenny/Kenny__a.png" "https://evil.example/a.png"\n'
        'wget -q -U "Mozilla/5.0" -O "/config/www/images/avatar/Kenny/Kenny__b.png" "http://sdk.bitmoji.com/b.png"\n'
        "echo '--- TERMINE ---'\n"
    )
    pairs = catalog.parse_export_script(script, BASE, ALLOWED)
    assert pairs == [
        ("images/avatar/Kenny/Kenny__bonne nuit.png", IMG_URL),
        (
            "images/avatar/Kenny/metadata_Kenny.json",
            "https://avatar-explorer.pages.dev/api/export?id1=111&type=json&targetUser=1",
        ),
    ]


# ---------------------------------------------------------------------------
# Disque : écriture, recensement, suppression
# ---------------------------------------------------------------------------


@pytest.fixture
def www(tmp_path: Path) -> Path:
    """Arborescence config/www avec un catalogue et un fichier sensible."""
    config = tmp_path / "config"
    (config / "www" / BASE / "Kenny").mkdir(parents=True)
    (config / "configuration.yaml").write_text("secret: oui")
    (config / "www" / BASE / "Kenny" / "Kenny__vieux.png").write_bytes(PNG)
    (config / "www" / BASE / "Kenny" / "Kenny__actuel.png").write_bytes(PNG)
    (config / "www" / BASE / "Kenny" / "notes.txt").write_text("à garder")
    return config / "www"


def test_write_file_refuses_escape(www: Path) -> None:
    """La garde resolve() refuse l'écriture hors de www/<dir>."""
    with pytest.raises(catalog.UnsafePathError):
        catalog._write_file(www, BASE, "../configuration.yaml", b"x")
    assert (www.parent / "configuration.yaml").read_text() == "secret: oui"


def test_write_file_writes_inside(www: Path) -> None:
    """Écriture atomique dans le dossier du catalogue, sans temporaire restant."""
    catalog._write_file(www, BASE, f"{BASE}/Lea/Lea__salut.png", PNG)
    assert (www / BASE / "Lea" / "Lea__salut.png").read_bytes() == PNG
    assert not list((www / BASE / "Lea").glob("*.part"))


def test_write_file_refuses_symlinked_folder(www: Path, tmp_path: Path) -> None:
    """Un dossier utilisateur remplacé par un lien vers l'extérieur est refusé."""
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    try:
        (www / BASE / "Piege").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Création de liens symboliques non autorisée sur ce système")
    with pytest.raises(catalog.UnsafePathError):
        catalog._write_file(www, BASE, f"{BASE}/Piege/Piege__x.png", PNG)
    assert not list(outside.iterdir())


def test_scan_orphans_refuses_roots_outside(www: Path) -> None:
    """Une racine hors de www/<dir>/<dossier> n'est jamais listée."""
    expected = {
        f"{BASE}/Kenny/Kenny__actuel.png",
        # Racines hostiles : www/ lui-même, la config, un absolu.
        "x.png",
        "../configuration.yaml",
        "/config/configuration.yaml",
        f"{BASE}/../../x.png",
    }
    orphans = catalog._scan_orphans(www, BASE, expected, ALLOWED)
    # notes.txt n'est pas un nom que l'API peut produire : jamais candidat.
    assert orphans == [f"{BASE}/Kenny/Kenny__vieux.png"]


def test_delete_files_refuses_outside(www: Path) -> None:
    """La suppression revalide chaque chemin, indépendamment du scan."""
    deleted, failed = catalog._delete_files(
        www,
        BASE,
        [
            "../configuration.yaml",
            "/config/configuration.yaml",
            f"{BASE}/Kenny/../../../configuration.yaml",
            f"{BASE}/Kenny/notes.txt",
            f"{BASE}/Kenny/Kenny__vieux.png",
        ],
        ALLOWED,
    )
    assert deleted == 1
    assert len(failed) == 4
    assert (www.parent / "configuration.yaml").exists()
    assert (www / BASE / "Kenny" / "notes.txt").exists()
    assert not (www / BASE / "Kenny" / "Kenny__vieux.png").exists()


# ---------------------------------------------------------------------------
# Réseau : liste blanche, type, taille, retry
# ---------------------------------------------------------------------------


async def _fetch_png(hass: HomeAssistant, url: str) -> bytes:
    return await catalog.async_fetch(
        async_get_clientsession(hass),
        url,
        timeout=catalog.DOWNLOAD_TIMEOUT,
        max_bytes=catalog.MAX_PNG_BYTES,
        content_types=catalog.PNG_CONTENT_TYPES,
    )


async def test_fetch_refuses_host_without_request(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Un hôte non autorisé n'est même pas contacté."""
    with pytest.raises(catalog.UnsafeUrlError):
        await _fetch_png(hass, "https://evil.example/x.png")
    assert aioclient_mock.call_count == 0


async def test_fetch_refuses_redirect_to_other_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Une redirection vers un hôte non autorisé est refusée."""
    aioclient_mock.get(
        IMG_URL, status=302, headers={"Location": "http://192.168.1.1/admin"}
    )
    with pytest.raises(catalog.UnsafeUrlError):
        await _fetch_png(hass, IMG_URL)
    assert aioclient_mock.call_count == 1


async def test_fetch_checks_content_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Le repli SPA de Cloudflare (HTML en 200) est refusé."""
    aioclient_mock.get(
        IMG_URL, text="<html></html>", headers={"Content-Type": "text/html"}
    )
    with pytest.raises(catalog.ResponseRejectedError, match="Content-Type"):
        await _fetch_png(hass, IMG_URL)


async def test_fetch_bounded_read(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """La lecture s'arrête au-delà de la taille maximale."""
    aioclient_mock.get(
        IMG_URL,
        content=PNG + b"\x00" * (catalog.MAX_PNG_BYTES + 1),
        headers={"Content-Type": "image/png"},
    )
    with pytest.raises(catalog.ResponseRejectedError, match="volumineuse"):
        await _fetch_png(hass, IMG_URL)


async def test_fetch_retries_on_429(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """429 puis 503 puis 200 : deux nouvelles tentatives, Retry-After respecté."""
    responses = iter(
        [
            {"status": 429, "headers": {"Retry-After": "7"}},
            {"status": 503, "headers": {}},
            {"status": 200, "headers": {"Content-Type": "image/png"}, "content": PNG},
        ]
    )

    async def _side_effect(method, url, data):
        spec = next(responses)
        return aioclient_mock.request(
            method,
            url,
            status=spec["status"],
            headers=spec["headers"],
            content=spec.get("content"),
        )

    aioclient_mock.get(IMG_URL, side_effect=_side_effect)
    with patch.object(catalog.asyncio, "sleep") as mock_sleep:
        assert await _fetch_png(hass, IMG_URL) == PNG
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [7.0, catalog.RETRY_BASE_DELAY * 2]


async def test_fetch_gives_up_after_max_attempts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Au-delà de MAX_ATTEMPTS, l'erreur HTTP remonte."""
    aioclient_mock.get(IMG_URL, status=500)
    with (
        patch.object(catalog.asyncio, "sleep"),
        pytest.raises(catalog.HttpStatusError) as err,
    ):
        await _fetch_png(hass, IMG_URL)
    assert err.value.status == 500
    assert aioclient_mock.call_count == catalog.MAX_ATTEMPTS


async def test_fetch_404_not_retried(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Un 404 est définitif : pas de nouvel essai."""
    aioclient_mock.get(IMG_URL, status=404)
    with pytest.raises(catalog.HttpStatusError):
        await _fetch_png(hass, IMG_URL)
    assert aioclient_mock.call_count == 1


def test_parse_retry_after() -> None:
    """Secondes ou date HTTP, plafonné, None si illisible."""
    assert catalog._parse_retry_after("5") == 5.0
    assert catalog._parse_retry_after("9999") == catalog.MAX_RETRY_DELAY
    assert catalog._parse_retry_after("n'importe quoi") is None
    assert catalog._parse_retry_after(None) is None
    assert catalog._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


# ---------------------------------------------------------------------------
# Bout en bout : synchro puis nettoyage
# ---------------------------------------------------------------------------

META_URL = (
    "https://avatar-explorer.pages.dev/api/export?id1=111_1-s5&type=json&targetUser=1"
)
IMG2_URL = "https://sdk.bitmoji.com/render/panel/10229609-111_1-s5-v1.png?transparent=1&palette=1&scale=1"


async def test_run_sync_and_cleanup_end_to_end(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, tmp_path: Path
) -> None:
    """Synchro réelle (HTTP simulé) : fichiers écrits, ligne hostile ignorée, orphelins."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.avatar_explorer.const import (
        AIDE_JSON_URL,
        DOMAIN,
        EXPORT_API_URL,
    )
    from custom_components.avatar_explorer.runtime import SyncState

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("secret: oui")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "dir": "images/avatar",
            "users": [{"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5"}],
        },
        options={"scale": 1},
    )
    state = SyncState(hass, entry.entry_id)

    aioclient_mock.get(
        AIDE_JSON_URL,
        json={"last_updated_iso": "2026-09-28T10:00:00Z"},
        headers={"Content-Type": "application/json"},
    )
    script = (
        "#!/bin/bash\nset -euo pipefail\n# commentaire\necho '--- DEBUT ---'\n"
        f'wget -q -U "Mozilla/5.0" -O "/config/www/images/avatar/Kenny/Kenny__bonne nuit.png" "{IMG_URL}"\n'
        f'wget -q -U "Mozilla/5.0" -O "/config/www/images/avatar/Kenny/Kenny__absent.png" "{IMG2_URL}"\n'
        f'wget -q -U "Mozilla/5.0" -O "/config/www//config/configuration.yaml" "{IMG_URL}"\n'
        f'wget -q -O "/config/www/images/avatar/Kenny/metadata_Kenny.json" "{META_URL}"\n'
    )
    # Metadata enregistrées AVANT le script : le mock retient la première URL
    # qui correspond, et /api/export sans requête correspond à tout.
    aioclient_mock.get(
        "https://avatar-explorer.pages.dev/api/export?type=json",
        json=[{"fichier": "Kenny__bonne nuit.png"}],
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    aioclient_mock.get(
        EXPORT_API_URL,
        text=script,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    aioclient_mock.get(IMG_URL, content=PNG, headers={"Content-Type": "image/png"})
    aioclient_mock.get(IMG2_URL, status=404)

    assert await catalog.async_run_sync(hass, entry, state) is True
    kenny = tmp_path / "www" / "images" / "avatar" / "Kenny"
    assert (kenny / "Kenny__bonne nuit.png").read_bytes() == PNG
    assert (kenny / "metadata_Kenny.json").exists()
    assert not (kenny / "Kenny__absent.png").exists()
    assert (tmp_path / "configuration.yaml").read_text() == "secret: oui"
    assert state.catalog_version == "2026-09-28T10:00:00Z"
    assert state.attrs["status"] == "a_jour"
    assert state.attrs["telecharges"] == 2
    assert state.attrs["total_catalogue"] == 3

    # Second passage : catalogue inchangé, rien n'est retéléchargé.
    calls_before = aioclient_mock.call_count
    assert await catalog.async_run_sync(hass, entry, state) is True
    assert aioclient_mock.call_count == calls_before + 1  # aide.json seulement

    # Nettoyage : un orphelin supprimé, celui affiché comme avatar protégé.
    (kenny / "Kenny__vieux.png").write_bytes(PNG)
    (kenny / "Kenny__garde.png").write_bytes(PNG)
    hass.states.async_set(
        "text.avatar_kenny", "/local/images/avatar/Kenny/Kenny__garde.png"
    )
    assert await catalog.async_delete_orphans(hass, entry, state) == (1, 1, 0)
    assert not (kenny / "Kenny__vieux.png").exists()
    assert (kenny / "Kenny__garde.png").exists()
    assert (kenny / "Kenny__bonne nuit.png").exists()
    assert state.attrs["orphelins"] == 1


# ---------------------------------------------------------------------------
# Dossiers autorisés (relecture sécurité, point 1)
# ---------------------------------------------------------------------------


def test_allowed_folders_from_entry() -> None:
    """Dossiers des utilisateurs configurés, plus Duo ; rien d'autre."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain="avatar_explorer",
        data={
            "dir": BASE,
            "users": [
                {"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5"},
                {"user_id_folder": "Lea"},
                {"bitmoji_id": "sans_dossier"},
            ],
        },
    )
    assert catalog.allowed_folders(entry) == ALLOWED


def test_sibling_folder_never_touched(www: Path) -> None:
    """Un dossier frère (www/<dir>/backgrounds) n'est ni écrit, ni recensé, ni vidé."""
    sibling = www / BASE / "backgrounds"
    sibling.mkdir()
    (sibling / "mon_fond.png").write_bytes(b"USER")
    script = (
        'wget -q -O "/config/www/images/avatar/backgrounds/mon_fond.png" '
        '"https://sdk.bitmoji.com/x"\n'
        f'wget -q -O "/config/www/images/avatar/Kenny/Kenny__actuel.png" "{IMG_URL}"\n'
    )
    pairs = catalog.parse_export_script(script, BASE, ALLOWED)
    assert pairs == [(f"{BASE}/Kenny/Kenny__actuel.png", IMG_URL)]

    # Même si la liste attendue désignait ce dossier, il n'est pas recensé...
    expected = {f"{BASE}/backgrounds/autre.png", f"{BASE}/Kenny/Kenny__actuel.png"}
    assert catalog._scan_orphans(www, BASE, expected, ALLOWED) == [
        f"{BASE}/Kenny/Kenny__vieux.png"
    ]
    # ... ni vidé.
    deleted, failed = catalog._delete_files(
        www, BASE, [f"{BASE}/backgrounds/mon_fond.png"], ALLOWED
    )
    assert (deleted, failed) == (0, [f"{BASE}/backgrounds/mon_fond.png"])
    assert (sibling / "mon_fond.png").read_bytes() == b"USER"


async def test_full_refresh_never_overwrites_sibling(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Un réimport complet ne réécrit rien hors des dossiers autorisés."""
    hass.config.config_dir = str(tmp_path)
    sibling = tmp_path / "www" / BASE / "backgrounds"
    sibling.mkdir(parents=True)
    (sibling / "mon_fond.png").write_bytes(b"USER")

    async def _fake_fetch(*_args, **_kwargs) -> bytes:
        return PNG

    with patch.object(catalog, "async_fetch", _fake_fetch):
        report = await catalog.async_download_files(
            hass,
            None,
            BASE,
            {
                f"{BASE}/backgrounds/mon_fond.png": IMG_URL,
                f"{BASE}/Kenny/Kenny__a.png": IMG_URL,
            },
            allowed=ALLOWED,
            refresh_all=True,
        )
    assert report.downloaded == 1
    assert (sibling / "mon_fond.png").read_bytes() == b"USER"


# ---------------------------------------------------------------------------
# Exceptions non gérées (point 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["²", "١٢", "①", "1.5", "-1"])
def test_parse_retry_after_never_raises(value: str) -> None:
    """« ² » passait isdigit() puis faisait lever float() en ValueError."""
    assert catalog._parse_retry_after(value) is None


async def test_fetch_invalid_redirect_location(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Une Location illisible par yarl devient une réponse refusée, pas une ValueError."""
    aioclient_mock.get(IMG_URL, status=302, headers={"Location": "http://[::1"})
    with pytest.raises(catalog.ResponseRejectedError, match="invalide"):
        await _fetch_png(hass, IMG_URL)


def _files(n: int) -> dict[str, str]:
    return {
        f"{BASE}/Kenny/Kenny__p{i}.png": f"https://sdk.bitmoji.com/render/{i}"
        for i in range(n)
    }


async def test_download_no_task_survives_unexpected_error(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Une exception imprévue dans un téléchargement n'en laisse aucun tourner après."""
    hass.config.config_dir = str(tmp_path)

    async def _fake_fetch(_session, url, **_kwargs) -> bytes:
        if url.endswith("/0"):
            raise ValueError("bug imprévu")
        await asyncio.sleep(0.3)
        return PNG

    with (
        patch.object(catalog, "async_fetch", _fake_fetch),
        pytest.raises(ExceptionGroup),
    ):
        await catalog.async_download_files(
            hass, None, BASE, _files(12), allowed=ALLOWED
        )
    kenny = tmp_path / "www" / BASE / "Kenny"
    written = len(list(kenny.glob("*.png"))) if kenny.exists() else 0
    await asyncio.sleep(0.6)
    after = len(list(kenny.glob("*.png"))) if kenny.exists() else 0
    assert written == after == 0


async def test_download_circuit_breaker(hass: HomeAssistant, tmp_path: Path) -> None:
    """Après N fichiers consécutifs en 429/5xx, le passage est abandonné."""
    hass.config.config_dir = str(tmp_path)
    calls = 0

    async def _fake_fetch(*_args, **_kwargs) -> bytes:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        raise catalog.HttpStatusError(503)

    with patch.object(catalog, "async_fetch", _fake_fetch):
        report = await catalog.async_download_files(
            hass, None, BASE, _files(200), allowed=ALLOWED
        )
    assert report.aborted is not None
    assert "429/5xx" in report.aborted
    # Le disjoncteur coupe avant d'avoir tout tenté ; tout reste à reprendre.
    assert catalog.MAX_CONSECUTIVE_SERVER_ERRORS <= calls < 200
    assert report.failures == 200
    assert report.downloaded == 0


async def test_download_global_budget(hass: HomeAssistant, tmp_path: Path) -> None:
    """La phase de téléchargement est bornée dans le temps ; le bilan est partiel."""
    hass.config.config_dir = str(tmp_path)

    async def _fake_fetch(_session, url, **_kwargs) -> bytes:
        if url.endswith("/0"):
            return PNG
        await asyncio.sleep(3600)
        return PNG

    with (
        patch.object(catalog, "async_fetch", _fake_fetch),
        patch.object(catalog, "DOWNLOAD_PHASE_TIMEOUT", 0.2),
    ):
        report = await catalog.async_download_files(
            hass, None, BASE, _files(10), allowed=ALLOWED
        )
    assert report.aborted is not None
    assert "durée maximale" in report.aborted
    assert report.downloaded == 1
    assert report.failures == 9


# ---------------------------------------------------------------------------
# Réimport complet partiel (relecture conformité, point 9)
# ---------------------------------------------------------------------------


async def test_full_refresh_partial_then_retry_only_failures(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, tmp_path: Path
) -> None:
    """Réimport complet partiel : terminé quand même, seuls les échecs sont repris."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.avatar_explorer.const import (
        AIDE_JSON_URL,
        DOMAIN,
        EXPORT_API_URL,
    )
    from custom_components.avatar_explorer.runtime import SyncState

    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "dir": BASE,
            "users": [{"user_id_folder": "Kenny", "bitmoji_id": "111_1-s5"}],
        },
        options={"scale": 1},
    )
    state = SyncState(hass, entry.entry_id)
    state.refresh_all_pending = True
    kenny = tmp_path / "www" / BASE / "Kenny"
    kenny.mkdir(parents=True)
    (kenny / "Kenny__a.png").write_bytes(b"ANCIEN")
    (kenny / "Kenny__b.png").write_bytes(b"ANCIEN")

    script = (
        f'wget -q -O "/config/www/images/avatar/Kenny/Kenny__a.png" "{IMG_URL}"\n'
        f'wget -q -O "/config/www/images/avatar/Kenny/Kenny__b.png" "{IMG2_URL}"\n'
    )

    def _mock(img2_status: int) -> None:
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            AIDE_JSON_URL,
            json={"last_updated_iso": "2026-09-28T10:00:00Z"},
            headers={"Content-Type": "application/json"},
        )
        aioclient_mock.get(
            EXPORT_API_URL, text=script, headers={"Content-Type": "text/plain"}
        )
        aioclient_mock.get(IMG_URL, content=PNG, headers={"Content-Type": "image/png"})
        if img2_status == 200:
            aioclient_mock.get(
                IMG2_URL, content=PNG, headers={"Content-Type": "image/png"}
            )
        else:
            aioclient_mock.get(IMG2_URL, status=img2_status)

    # 1. Réimport complet : b échoue durablement (500 après les essais).
    _mock(500)
    with patch.object(catalog.asyncio, "sleep"):
        ok = await catalog.async_run_sync(hass, entry, state, refresh_all=True)
    assert ok is False
    assert (kenny / "Kenny__a.png").read_bytes() == PNG
    assert (kenny / "Kenny__b.png").read_bytes() == b"ANCIEN"
    assert state.attrs["status"] == "partielle"
    # Le réimport complet n'est plus dû : seul b reste à reprendre, et c'est
    # persisté.
    assert state.refresh_all_pending is False
    assert state.retry_paths == [f"{BASE}/Kenny/Kenny__b.png"]
    assert state._as_dict()["retry_paths"] == [f"{BASE}/Kenny/Kenny__b.png"]

    # 2. Passage différentiel : b est traité comme manquant, a n'est pas repris.
    _mock(200)
    assert await catalog.async_run_sync(hass, entry, state) is True
    fetched = [str(call[1]) for call in aioclient_mock.mock_calls]
    assert not any(url.startswith(IMG_URL.split("?")[0]) for url in fetched)
    assert any(url.startswith(IMG2_URL.split("?")[0]) for url in fetched)
    assert (kenny / "Kenny__b.png").read_bytes() == PNG
    assert state.retry_paths == []
    assert state.attrs["status"] == "a_jour"


async def test_full_refresh_too_many_failures_stays_pending(
    hass: HomeAssistant,
) -> None:
    """Au-delà de MAX_RETRY_PATHS échecs, le réimport complet reste dû en entier."""
    from custom_components.avatar_explorer.runtime import SyncState

    state = SyncState(hass, "e")
    state.refresh_all_pending = True
    with patch("custom_components.avatar_explorer.runtime.MAX_RETRY_PATHS", 2):
        state.async_finish_full_refresh(["a", "b", "c"])
    assert state.refresh_all_pending is True
    assert state.retry_paths == []

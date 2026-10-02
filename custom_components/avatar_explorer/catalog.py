"""Synchronisation du catalogue de poses depuis avatar-explorer.pages.dev.

Le principe : /api/export renvoie un script bash déterministe listant tous les
fichiers à récupérer. On le **lit** au lieu de l'exécuter -- ça évite de lancer
du code distant sans supervision à chaque vérification, et ça permet de
comparer au disque pour ne télécharger que le delta. En régime normal, le
catalogue ne bouge qu'une fois par semaine, donc la quasi-totalité des passages
se solde par zéro téléchargement.

Tout ce qui vient du serveur (chemins, URLs, contenus) est traité comme non
fiable : une seule compromission en amont (GitHub, Cloudflare, API Bitmoji)
toucherait toutes les instances d'un coup. D'où, à chaque étape :
- chemins normalisés et confinés à www/<dossier configuré>/<utilisateur>/ ;
- URLs en liste blanche (HTTPS, hôtes connus), redirections comprises ;
- réponses bornées en taille et contrôlées en type ;
- seconde vérification par resolve() au moment d'écrire ou de supprimer.

Le site s'appelait « Pose Explorer » jusqu'en juillet 2026 ; ce module se
nommait alors pose_explorer.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import posixpath
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

import aiohttp
from aiohttp import hdrs
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads
from yarl import URL

from .const import (
    AIDE_JSON_URL,
    ALLOWED_DOWNLOAD_HOSTS,
    CONF_BITMOJI_ID,
    CONF_DIR,
    CONF_DUO_PAIR,
    CONF_LANG,
    CONF_SCALE,
    CONF_USER_FOLDER,
    CONF_USERS,
    DEFAULT_DIR,
    DEFAULT_LANG,
    DEFAULT_SCALE,
    DIR_PATTERN,
    DOWNLOAD_PHASE_TIMEOUT,
    EXPORT_API_URL,
    MAX_CONSECUTIVE_SERVER_ERRORS,
    RESERVED_FOLDER,
    STATUS_ERROR,
    STATUS_PARTIAL,
    STATUS_UP_TO_DATE,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .runtime import SyncState

_LOGGER = logging.getLogger(__name__)

REMOTE_WWW_PREFIX = "/config/www/"
DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Ancré sur "wget" en début de ligne : une regex libre matcherait n'importe
# quelle ligne contenant le motif, y compris un jour où l'API générerait
# autre chose que des téléchargements. Les autres lignes du script (shebang,
# echo, set -euo pipefail, commentaires) sont ignorées sans erreur.
#
# Ce format est le contrat avec functions/api/export.js : ne pas le modifier
# sans faire évoluer l'API en même temps.
WGET_LINE_RE = re.compile(
    r'^wget\s+-q\s+(?:-U\s+"[^"]*"\s+)?-O\s+"([^"]+)"\s+"([^"]+)"\s*$',
    re.MULTILINE,
)

# Noms produits par l'API : « <dossier>__<tag>[_N].png », « <a>__<b>__<tag>.png »
# et « metadata_<dossier>.json ». Le tag sort de cleanPoseName
# (public/shared/poseNameUtils.js) : [a-z0-9 _] uniquement, espaces compris
# (« Kenny__bonne nuit.png »). Vérifié sur les 24 716 noms des 14 langues.
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9_\- ]+\.(?:png|json)$")
# Sous-dossier par utilisateur (ou « Duo ») : même alphabet que name1/name2.
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_DIR_RE = re.compile(DIR_PATTERN)

# Bornes de lecture. Une pose PNG pèse quelques dizaines de Ko en scale 1 et
# rarement plus d'1 Mo en scale 4 ; les metadata atteignent ~1 Mo en duo.
MAX_PNG_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_AIDE_BYTES = 1024 * 1024
MAX_SCRIPT_BYTES = 10 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CONTENT_TYPES = frozenset({"image/png"})
JSON_CONTENT_TYPES = frozenset({"application/json"})
SCRIPT_CONTENT_TYPES = frozenset(
    {"text/plain", "text/x-shellscript", "application/x-sh"}
)

AIDE_TIMEOUT = aiohttp.ClientTimeout(total=20)
EXPORT_TIMEOUT = aiohttp.ClientTimeout(total=60)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60, sock_connect=15)

# Retry : 2 nouvelles tentatives (3 essais au total) sur 429, 5xx, timeout et
# coupure réseau. Le délai double à chaque fois, sauf si le serveur impose le
# sien via Retry-After (plafonné pour ne pas geler la synchro).
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0
MAX_RETRY_DELAY = 60.0
MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Le catalogue fait ~3750 fichiers : assez de parallélisme pour que le premier
# import ne dure pas des heures, assez peu pour ne pas saturer la connexion.
DOWNLOAD_CONCURRENCY = 6

# Nombre d'échecs (ou de lignes refusées) détaillés dans le journal avant
# bascule en debug.
MAX_REPORTED_FAILURES = 10


class CatalogError(Exception):
    """Erreur de synchronisation du catalogue."""


class UnsafeUrlError(CatalogError):
    """URL hors liste blanche (schéma, hôte, port ou identifiants)."""


class UnsafePathError(CatalogError):
    """Chemin qui sortirait du dossier du catalogue."""


class ResponseRejectedError(CatalogError):
    """Réponse refusée : type, taille ou contenu inattendus."""


class HttpStatusError(CatalogError):
    """Statut HTTP non exploitable."""

    def __init__(self, status: int, body: str = "") -> None:
        """Conserve le statut et le début du corps (message d'erreur de l'API)."""
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class _CircuitOpenError(CatalogError):
    """Trop de réponses 429/5xx consécutives : le passage est abandonné."""


class _RetryableError(CatalogError):
    """Échec transitoire : 429, 5xx, timeout ou coupure réseau."""

    def __init__(self, cause: BaseException, retry_after: float | None = None) -> None:
        super().__init__(str(cause) or type(cause).__name__)
        self.cause = cause
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Validation des chemins et des URLs (fonctions pures)
# ---------------------------------------------------------------------------


def normalize_dir(raw: object) -> str | None:
    """Dossier du catalogue sous www/, sans « / » de début ni de fin.

    Même règle que l'API web (DIR_SAFE_PATTERN de export.js) : lettres,
    chiffres, « _ », « - » et « / » entre segments. Retourne None si invalide.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip().strip("/")
    if not _DIR_RE.fullmatch(value):
        return None
    return value


def is_allowed_url(url: str | URL) -> bool:
    """Vrai si l'URL est en HTTPS vers un hôte de la liste blanche."""
    try:
        parsed = url if isinstance(url, URL) else URL(url)
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.host in ALLOWED_DOWNLOAD_HOSTS
        and parsed.port == 443
        and parsed.user is None
        and parsed.password is None
    )


def allowed_folders(entry: ConfigEntry) -> frozenset[str]:
    """Dossiers que la synchro a le droit de toucher sous www/<dir>/.

    Ceux des utilisateurs configurés, plus « Duo ». Sans cette liste, un
    serveur compromis pouvait viser n'importe quel dossier frère
    (www/<dir>/backgrounds/...) : y écrire, et le faire recenser puis vider
    par le nettoyage des orphelins.
    """
    folders = {
        folder
        for user in entry.data.get(CONF_USERS, [])
        if isinstance(folder := user.get(CONF_USER_FOLDER), str) and folder
    }
    return frozenset(folders | {RESERVED_FOLDER})


def safe_relative_path(
    dest: str, base_dir: str, allowed: Collection[str]
) -> str | None:
    """Chemin relatif à www/ d'une destination du script, ou None si refusée.

    Seule forme acceptée : /config/www/<base_dir>/<dossier>/<fichier>, où
    <dossier> est dans `allowed` (voir allowed_folders). Le contrôle
    historique (préfixe + absence de « .. ») laissait passer
    « /config/www//config/configuration.yaml » : le relatif « /config/... »
    est absolu, et Path(www) / "/config/..." pointe hors de www/.
    """
    if not dest.startswith(REMOTE_WWW_PREFIX):
        return None
    relative = dest[len(REMOTE_WWW_PREFIX) :]
    if not relative or "\\" in relative or "\x00" in relative:
        return None
    if posixpath.isabs(relative):
        return None
    parts = relative.split("/")
    # Refus explicite plutôt que normalisation silencieuse : un chemin qui a
    # besoin d'être normalisé n'a pas été produit par l'API.
    if any(part in ("", ".", "..") for part in parts):
        return None
    if posixpath.normpath(relative) != relative:
        return None
    base_parts = base_dir.split("/")
    if parts[: len(base_parts)] != base_parts:
        return None
    rest = parts[len(base_parts) :]
    if len(rest) != 2:
        return None
    folder, name = rest
    if not SAFE_SEGMENT_RE.fullmatch(folder) or not SAFE_FILENAME_RE.fullmatch(name):
        return None
    if folder not in allowed:
        return None
    return relative


def _is_catalog_folder(
    relative_folder: str, base_dir: str, allowed: Collection[str]
) -> bool:
    """Vrai pour « <base_dir>/<dossier> » avec <dossier> autorisé.

    C'est la seule forme de dossier que la synchro écrit, recense ou vide.
    """
    prefix = f"{base_dir}/"
    if not relative_folder.startswith(prefix):
        return False
    folder = relative_folder[len(prefix) :]
    return bool(SAFE_SEGMENT_RE.fullmatch(folder)) and folder in allowed


def _resolve_inside(www_root: Path, base_dir: str, relative: str) -> Path:
    """Seconde garde, au moment d'agir sur le disque.

    resolve() suit les liens symboliques : un dossier utilisateur remplacé par
    un lien vers /config ferait sinon écrire ou supprimer hors du catalogue.
    """
    root = (www_root / base_dir).resolve()
    target = (www_root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise UnsafePathError(f"chemin hors de www/{base_dir} : {relative}")
    return target


def _parse_retry_after(value: str | None) -> float | None:
    """Délai demandé par le serveur (secondes ou date HTTP), plafonné."""
    if not value:
        return None
    value = value.strip()
    # isdigit() seul accepte « ² » ou des chiffres arabes, que float() refuse
    # en ValueError : l'exception sortait du téléchargement sans être gérée.
    if value.isascii() and value.isdigit():
        return min(float(value), MAX_RETRY_DELAY)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, min((when - dt_util.utcnow()).total_seconds(), MAX_RETRY_DELAY))


def _content_type(resp: aiohttp.ClientResponse) -> str:
    raw = resp.headers.get(hdrs.CONTENT_TYPE, "")
    return raw.split(";", 1)[0].strip().lower()


def _parse_iso(value: str) -> datetime:
    # Python >= 3.11 accepte le suffixe « Z » directement.
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Accès disque (appelés en executor)
# ---------------------------------------------------------------------------


def _write_file(www_root: Path, base_dir: str, relative: str, content: bytes) -> None:
    """Écriture atomique et confinée : fichier temporaire puis rename.

    Sans écriture atomique, une coupure en cours d'écriture laisse un PNG
    tronqué que la carte afficherait comme une image cassée, sans moyen de le
    détecter ensuite.

    Le suffixe aléatoire est indispensable : avec un nom fixe (« .part »), deux
    écritures simultanées vers la même destination partagent le fichier
    temporaire, et le second os.replace échoue en FileNotFoundError parce que
    le premier vient de le consommer.
    """
    # Le dossier parent est créé AVANT la garde : resolve() d'un dossier
    # inexistant ne suit aucun lien, la vérification serait donc incomplète.
    (www_root / relative).parent.mkdir(parents=True, exist_ok=True)
    target = _resolve_inside(www_root, base_dir, relative)
    # Risque résiduel accepté (TOCTOU) : entre resolve() ci-dessus et
    # write_bytes/os.replace ci-dessous, un processus local qui a déjà le droit
    # d'écrire dans www/<dir>/ peut remplacer le dossier par un lien et faire
    # écrire hors du catalogue. Le fermer exigerait des opérations relatives à
    # un descripteur de dossier (openat/O_NOFOLLOW), indisponibles de façon
    # portable en Python. Cet attaquant a de toute façon déjà la main sur
    # /config : la garde vise un serveur distant compromis, pas lui.
    tmp = target.with_name(f"{target.name}.{uuid4().hex[:8]}.part")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, target)
    except OSError:
        # Ne pas laisser traîner un temporaire orphelin si le rename échoue.
        tmp.unlink(missing_ok=True)
        raise


def _select_missing(
    www_root: Path,
    files: Mapping[str, str],
    *,
    refresh_all: bool,
    retry: Collection[str] = (),
) -> list[tuple[str, str]]:
    """Ne garde que les fichiers absents du disque.

    Les metadata_*.json sont toujours reprises : on n'arrive ici que si le
    catalogue distant a changé, donc leur contenu a changé aussi.

    `retry` liste les fichiers en échec lors d'un réimport complet précédent :
    ils existent sur le disque, mais avec l'ancien contenu, et sont donc
    traités comme manquants.

    refresh_all court-circuite la comparaison. C'est indispensable quand un ID
    Bitmoji change : les noms de fichiers générés sont identiques (ils dérivent
    du nom de dossier, pas de l'ID), seul le contenu diffère. Sans ce drapeau,
    le différentiel sauterait tout et l'ancien avatar resterait affiché.
    """
    if refresh_all:
        return list(files.items())

    return [
        (relative, url)
        for relative, url in files.items()
        if posixpath.basename(relative).startswith("metadata_")
        or relative in retry
        or not (www_root / relative).exists()
    ]


def _scan_orphans(
    www_root: Path,
    base_dir: str,
    expected: Collection[str],
    allowed: Collection[str],
) -> list[str]:
    """Fichiers présents en local mais absents du catalogue.

    Le périmètre est volontairement étroit : on ne regarde QUE les dossiers que
    le catalogue alimente lui-même (images/avatar/Kenny, .../Duo...), et sans
    descendre dans d'éventuels sous-dossiers. Élargir ce scan ferait passer pour
    orphelin tout le reste de www/ -- une première version de ce code balayait
    images/ en entier et considérait 3359 fichiers sans rapport comme à jeter.

    Toute racine hors de www/<base_dir>/<dossier autorisé> est refusée (voir
    allowed_folders), et seuls les noms que l'API aurait pu produire
    (.png / .json) sont candidats.
    """
    expected_set = set(expected)
    roots = {posixpath.dirname(r) for r in expected_set}
    try:
        base = (www_root / base_dir).resolve()
    except OSError:
        return []

    orphans: list[str] = []
    for root in sorted(roots):
        if not _is_catalog_folder(root, base_dir, allowed):
            _LOGGER.warning(
                "Dossier hors du catalogue ignoré pour le recensement : %r", root
            )
            continue
        folder = (www_root / root).resolve()
        if not folder.is_relative_to(base) or folder == base or not folder.is_dir():
            continue
        for path in folder.iterdir():
            name = path.name
            # Les .part sont des temporaires d'une écriture en cours, pas des
            # orphelins : les compter reviendrait à courir après la synchro.
            # Le filtre sur le nom les écarte, comme tout fichier que l'API
            # n'a pas pu produire.
            if not SAFE_FILENAME_RE.fullmatch(name):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            relative = f"{root}/{name}"
            if relative not in expected_set:
                orphans.append(relative)
    return sorted(orphans)


def _delete_files(
    www_root: Path,
    base_dir: str,
    relatives: Iterable[str],
    allowed: Collection[str],
) -> tuple[int, list[str]]:
    """Supprime la liste donnée. Retourne (supprimés, échecs).

    Chaque chemin est revalidé ici, juste avant l'unlink : cette fonction ne
    fait confiance à personne, pas même à _scan_orphans.
    """
    ok = 0
    failed: list[str] = []
    for relative in relatives:
        folder = posixpath.dirname(relative)
        name = posixpath.basename(relative)
        if not _is_catalog_folder(
            folder, base_dir, allowed
        ) or not SAFE_FILENAME_RE.fullmatch(name):
            _LOGGER.warning(
                "Suppression refusée (chemin hors catalogue) : %r", relative
            )
            failed.append(relative)
            continue
        try:
            target = _resolve_inside(www_root, base_dir, relative)
            target.unlink()
            ok += 1
        except (OSError, UnsafePathError) as err:
            _LOGGER.warning("Suppression impossible de %s : %s", relative, err)
            failed.append(relative)
    return ok, failed


def _files_in_use(hass: HomeAssistant) -> set[str]:
    """Images actuellement référencées par les entités text.

    Supprimer l'avatar affiché d'un utilisateur casserait son affichage sans
    qu'aucune erreur ne le signale : ces fichiers sont exclus du nettoyage même
    s'ils ne sont plus au catalogue.
    """
    in_use: set[str] = set()
    for state in hass.states.async_all("text"):
        value = state.state or ""
        if value.startswith("/local/"):
            in_use.add(posixpath.normpath(value[len("/local/") :].lstrip("/")))
    return in_use


# ---------------------------------------------------------------------------
# Réseau
# ---------------------------------------------------------------------------


async def _async_fetch_once(
    session: aiohttp.ClientSession,
    url: URL,
    *,
    timeout: aiohttp.ClientTimeout,
    max_bytes: int,
    content_types: frozenset[str],
) -> bytes:
    """Un essai : redirections suivies à la main pour les revalider."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not is_allowed_url(current):
            # Sans la requête : elle peut porter les ID Bitmoji (id1, id2).
            raise UnsafeUrlError(f"URL refusée : {current.with_query(None)}")
        try:
            async with session.get(
                current,
                headers=DOWNLOAD_HEADERS,
                timeout=timeout,
                allow_redirects=False,
            ) as resp:
                if resp.status in REDIRECT_STATUSES:
                    location = resp.headers.get(hdrs.LOCATION)
                    if not location:
                        raise ResponseRejectedError(
                            f"redirection HTTP {resp.status} sans Location"
                        )
                    try:
                        current = current.join(URL(location))
                    except (ValueError, TypeError) as err:
                        # « http://[::1 » et consorts : yarl lève ValueError,
                        # qui sortait sinon du téléchargement sans être gérée.
                        raise ResponseRejectedError(
                            f"redirection HTTP {resp.status} vers une URL invalide"
                        ) from err
                    continue
                if resp.status == 429 or resp.status >= 500:
                    raise _RetryableError(
                        HttpStatusError(resp.status),
                        _parse_retry_after(resp.headers.get(hdrs.RETRY_AFTER)),
                    )
                if resp.status != 200:
                    body = await resp.content.read(2048)
                    raise HttpStatusError(resp.status, body.decode("utf-8", "replace"))

                ctype = _content_type(resp)
                if ctype not in content_types:
                    raise ResponseRejectedError(
                        f"Content-Type inattendu : {ctype or 'absent'}"
                    )
                declared = resp.headers.get(hdrs.CONTENT_LENGTH)
                if (
                    declared
                    and declared.isascii()
                    and declared.isdigit()
                    and int(declared) > max_bytes
                ):
                    raise ResponseRejectedError(
                        f"réponse trop volumineuse ({declared} octets)"
                    )

                # Lecture bornée : on s'arrête dès que la limite est dépassée,
                # même si le serveur a menti sur Content-Length (ou l'a omis).
                buffer = bytearray()
                async for chunk in resp.content.iter_chunked(READ_CHUNK_BYTES):
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise ResponseRejectedError(
                            f"réponse trop volumineuse (> {max_bytes} octets)"
                        )
                return bytes(buffer)
        except (
            TimeoutError,
            aiohttp.ClientConnectionError,
            aiohttp.ClientPayloadError,
        ) as err:
            raise _RetryableError(err) from err
    raise ResponseRejectedError(f"plus de {MAX_REDIRECTS} redirections")


async def async_fetch(
    session: aiohttp.ClientSession,
    url: str | URL,
    *,
    params: Mapping[str, str] | None = None,
    timeout: aiohttp.ClientTimeout,
    max_bytes: int,
    content_types: frozenset[str],
) -> bytes:
    """GET borné, typé, en liste blanche, avec retry et backoff."""
    target = URL(url) if isinstance(url, str) else url
    if params:
        target = target.with_query(params)

    attempt = 0
    while True:
        attempt += 1
        try:
            return await _async_fetch_once(
                session,
                target,
                timeout=timeout,
                max_bytes=max_bytes,
                content_types=content_types,
            )
        except _RetryableError as err:
            if attempt >= MAX_ATTEMPTS:
                if isinstance(err.cause, CatalogError):
                    raise err.cause from None
                raise CatalogError(
                    f"{type(err.cause).__name__} : {err.cause}"
                ) from err.cause
            delay = err.retry_after
            if delay is None:
                delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
            _LOGGER.debug(
                "Échec transitoire sur %s (%s), nouvel essai dans %.1f s",
                target.with_query(None),
                err,
                delay,
            )
            await asyncio.sleep(delay)


async def async_fetch_aide_json(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Lit aide.json (horodatage du catalogue distant)."""
    # Même User-Agent que pour les images : Cloudflare filtre certains agents
    # de bibliothèques (Python-urllib est déjà rejeté en 403). Envoyer un UA
    # de navigateur évite de dépendre de celui qu'aiohttp choisit.
    raw = await async_fetch(
        session,
        AIDE_JSON_URL,
        timeout=AIDE_TIMEOUT,
        max_bytes=MAX_AIDE_BYTES,
        content_types=JSON_CONTENT_TYPES,
    )
    try:
        data = json_loads(raw)
    except JSON_DECODE_EXCEPTIONS as err:
        raise ResponseRejectedError(f"aide.json illisible : {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("last_updated_iso"), str):
        raise ResponseRejectedError("aide.json sans champ last_updated_iso")
    return data


def parse_export_script(
    script: str, base_dir: str, allowed: Collection[str]
) -> list[tuple[str, str]]:
    """Extrait les couples (chemin relatif à www/, URL) sûrs du script d'export.

    Une ligne dont le chemin ou l'URL est refusé est ignorée et journalisée :
    elle ne peut provenir que d'un serveur compromis ou d'un changement de
    contrat côté API. `allowed` restreint les dossiers acceptés (voir
    allowed_folders).
    """
    result: list[tuple[str, str]] = []
    refused = 0
    for dest, url in WGET_LINE_RE.findall(script):
        relative = safe_relative_path(dest, base_dir, allowed)
        reason = None
        if relative is None:
            reason = "destination hors du dossier du catalogue"
        elif not is_allowed_url(url):
            reason = "URL hors liste blanche"
        if reason is not None:
            refused += 1
            if refused <= MAX_REPORTED_FAILURES:
                # %r : contenu fourni par le serveur, potentiellement hostile
                # (retours à la ligne pour forger de fausses lignes de journal).
                _LOGGER.warning(
                    "Ligne d'export refusée (%s) : %r -> %r", reason, dest, url
                )
            continue
        result.append((relative, url))
    if refused > MAX_REPORTED_FAILURES:
        _LOGGER.warning("%s ligne(s) d'export refusée(s) au total", refused)
    return result


def _describe_call(params: Mapping[str, str]) -> str:
    """Résumé d'un appel export pour le journal.

    Jamais id1 ni id2 : l'ID Bitmoji identifie le compte de l'utilisateur et
    n'a rien à faire dans un journal que l'on partage pour demander de l'aide.
    """
    parts = [f"mode={params.get('mode', '?')}", f"name1={params.get('name1', '?')}"]
    if "name2" in params:
        parts.append(f"name2={params['name2']}")
    return ", ".join(parts)


async def async_fetch_file_list(
    session: aiohttp.ClientSession,
    params: Mapping[str, str],
    base_dir: str,
    allowed: Collection[str],
) -> list[tuple[str, str]] | None:
    """Récupère le script d'export et en extrait les couples (chemin relatif, URL).

    Le script n'est jamais exécuté : on le lit. Ça évite de lancer du code
    distant sans supervision à chaque vérification automatique, et ça permet de
    comparer au disque avant de télécharger quoi que ce soit.
    """
    try:
        raw = await async_fetch(
            session,
            EXPORT_API_URL,
            params=params,
            timeout=EXPORT_TIMEOUT,
            max_bytes=MAX_SCRIPT_BYTES,
            content_types=SCRIPT_CONTENT_TYPES,
        )
    except HttpStatusError as err:
        # L'API renvoie un message explicite en texte brut sur les 400
        # (« Paramètre id1 invalide », etc.) : on le remonte tel quel, c'est le
        # plus utile.
        # %r : le corps vient du serveur, il ne doit pas pouvoir forger de
        # fausses lignes dans le journal.
        _LOGGER.error(
            "Export Avatar Explorer refusé (HTTP %s) pour %s : %r",
            err.status,
            _describe_call(params),
            err.body.strip()[:300],
        )
        return None
    except (CatalogError, aiohttp.ClientError) as err:
        _LOGGER.error(
            "Appel export Avatar Explorer impossible (%s) : %s",
            _describe_call(params),
            err,
        )
        return None

    script = raw.decode("utf-8", "replace")
    pairs = parse_export_script(script, base_dir, allowed)
    if not pairs:
        _LOGGER.error(
            "Réponse export sans aucun téléchargement exploitable pour %s (%s octets reçus) : %r",
            _describe_call(params),
            len(raw),
            script[:200],
        )
        return None
    return pairs


@dataclass
class DownloadReport:
    """Bilan de la phase de téléchargement d'un passage."""

    downloaded: int = 0
    # Déjà présents sur le disque, ou absents chez Bitmoji (404 définitif).
    skipped: int = 0
    # Chemins en échec, y compris ceux que l'abandon du passage n'a pas
    # laissé tenter : ils sont à reprendre au passage suivant.
    failed_paths: list[str] = field(default_factory=list)
    # Raison de l'abandon du passage (budget dépassé, disjoncteur), sinon None.
    aborted: str | None = None

    @property
    def failures(self) -> int:
        """Nombre de fichiers en échec."""
        return len(self.failed_paths)


async def _async_write_to_completion(
    hass: HomeAssistant, www_root: Path, base_dir: str, relative: str, content: bytes
) -> None:
    """Écrit le fichier dans l'executor et attend la fin, même en cas d'annulation.

    Annuler l'attente n'arrête pas le thread : sans cette attente, une écriture
    lancée juste avant l'annulation du passage aboutirait APRÈS la libération
    du verrou de synchro, en concurrence avec le passage ou le nettoyage
    suivant.
    """
    write = asyncio.ensure_future(
        hass.async_add_executor_job(_write_file, www_root, base_dir, relative, content)
    )
    try:
        await asyncio.shield(write)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.wait({write})
        raise


async def async_download_files(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    base_dir: str,
    files: Mapping[str, str],
    *,
    allowed: Collection[str],
    refresh_all: bool = False,
    retry: Collection[str] = (),
) -> DownloadReport:
    """Télécharge en parallèle uniquement ce qui manque.

    Les téléchargements tournent dans un asyncio.TaskGroup : quelle que soit
    l'issue (exception imprévue, budget dépassé, disjoncteur, annulation à
    l'unload), aucune tâche ne survit à cette fonction, donc aucune écriture
    n'a lieu après la libération du verrou de synchro. Avec gather(), une
    exception dans une tâche laissait les autres continuer en arrière-plan.

    La phase entière est bornée par DOWNLOAD_PHASE_TIMEOUT, et abandonnée
    après MAX_CONSECUTIVE_SERVER_ERRORS fichiers consécutifs en échec sur
    429/5xx. Dans les deux cas le bilan est partiel : les fichiers non tentés
    figurent dans failed_paths.
    """
    www_root = Path(hass.config.path("www"))
    # Défense en profondeur : `files` vient de parse_export_script, qui filtre
    # déjà les dossiers ; on ne s'appuie pas sur l'appelant pour autant.
    unsafe = {
        relative
        for relative in files
        if not _is_catalog_folder(posixpath.dirname(relative), base_dir, allowed)
        or not SAFE_FILENAME_RE.fullmatch(posixpath.basename(relative))
    }
    if unsafe:
        _LOGGER.warning(
            "%s fichier(s) hors des dossiers autorisés ignoré(s), par exemple %r",
            len(unsafe),
            min(unsafe),
        )
        files = {r: u for r, u in files.items() if r not in unsafe}

    missing = await hass.async_add_executor_job(
        partial(_select_missing, www_root, files, refresh_all=refresh_all, retry=retry)
    )
    report = DownloadReport(skipped=len(files) - len(missing))

    if not missing:
        return report

    _LOGGER.info(
        "Avatar Explorer : %s fichier(s) à récupérer, %s déjà présent(s)",
        len(missing),
        report.skipped,
    )

    semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    # Issue de chaque fichier, renseignée au fil de l'eau : en cas d'abandon,
    # ce qui manque ici n'a pas été tenté.
    outcome: dict[str, bool | Literal["absent"]] = {}
    # Un échec massif (réseau coupé en plein import) produirait 3750 lignes et
    # déclencherait le garde-fou « logging too frequently » de Home Assistant,
    # qui tronque le journal. On détaille les premiers, on compte les autres.
    reported = 0
    consecutive_server_errors = 0

    async def _fetch(relative: str, url: str) -> None:
        """Renseigne outcome : True, "absent" (404 définitif) ou False (échec)."""
        nonlocal reported, consecutive_server_errors
        is_json = relative.endswith(".json")
        async with semaphore:
            try:
                content = await async_fetch(
                    session,
                    url,
                    timeout=DOWNLOAD_TIMEOUT,
                    max_bytes=MAX_JSON_BYTES if is_json else MAX_PNG_BYTES,
                    content_types=JSON_CONTENT_TYPES if is_json else PNG_CONTENT_TYPES,
                )
                if not content:
                    raise ResponseRejectedError("réponse vide")
                if is_json:
                    # Le repli SPA de Cloudflare renvoie index.html en 200 :
                    # on s'assure que c'est bien du JSON avant de l'écrire.
                    try:
                        json_loads(content)
                    except JSON_DECODE_EXCEPTIONS as err:
                        raise ResponseRejectedError("JSON invalide") from err
                elif not content.startswith(PNG_SIGNATURE):
                    raise ResponseRejectedError("contenu qui n'est pas un PNG")
                await _async_write_to_completion(
                    hass, www_root, base_dir, relative, content
                )
            except HttpStatusError as err:
                # Un 404 signifie que cette pose n'existe pas pour cet avatar :
                # réessayer ne servira jamais à rien. On le distingue d'une
                # panne réseau, qui elle mérite un retry.
                if err.status == 404:
                    _LOGGER.debug("Pose absente chez Bitmoji (404) : %s", relative)
                    outcome[relative] = "absent"
                    consecutive_server_errors = 0
                    return
                failure: Exception = err
                if err.status == 429 or err.status >= 500:
                    consecutive_server_errors += 1
                else:
                    consecutive_server_errors = 0
            except (CatalogError, aiohttp.ClientError, OSError) as err:
                failure = err
            else:
                outcome[relative] = True
                consecutive_server_errors = 0
                return

        outcome[relative] = False
        reported += 1
        # L'URL n'est pas journalisée : celles de Bitmoji contiennent l'ID.
        if reported <= MAX_REPORTED_FAILURES:
            _LOGGER.warning("Échec téléchargement de %s : %s", relative, failure)
        elif reported == MAX_REPORTED_FAILURES + 1:
            _LOGGER.warning(
                "Plus de %s échecs de téléchargement : les suivants ne sont "
                "journalisés qu'en niveau debug.",
                MAX_REPORTED_FAILURES,
            )
        else:
            _LOGGER.debug("Échec téléchargement %s : %s", relative, failure)

        if consecutive_server_errors >= MAX_CONSECUTIVE_SERVER_ERRORS:
            # Lever ici fait annuler toutes les autres tâches par le TaskGroup.
            raise _CircuitOpenError(
                f"{consecutive_server_errors} réponses 429/5xx consécutives"
            )

    try:
        async with asyncio.timeout(DOWNLOAD_PHASE_TIMEOUT):
            try:
                async with asyncio.TaskGroup() as group:
                    for relative, url in missing:
                        group.create_task(_fetch(relative, url))
            except* _CircuitOpenError as group_err:
                report.aborted = (
                    f"téléchargements interrompus : {group_err.exceptions[0]}"
                )
    except TimeoutError:
        report.aborted = (
            "téléchargements interrompus : durée maximale de "
            f"{DOWNLOAD_PHASE_TIMEOUT // 60} min dépassée"
        )

    absent = 0
    for relative, _url in missing:
        result = outcome.get(relative, False)
        if result is True:
            report.downloaded += 1
        elif result == "absent":
            absent += 1
        else:
            report.failed_paths.append(relative)
    report.skipped += absent

    if report.aborted:
        _LOGGER.warning(
            "Avatar Explorer : %s ; %s fichier(s) non récupéré(s), repris au "
            "passage suivant",
            report.aborted,
            report.failures,
        )
    if absent:
        _LOGGER.info(
            "%s pose(s) inexistante(s) chez Bitmoji (404) : ignorées, elles ne "
            "bloquent pas la synchronisation.",
            absent,
        )
    return report


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_export_calls(
    entry: ConfigEntry, scale: int | str, lang: str
) -> list[dict[str, str]]:
    """Construit les appels /api/export à effectuer.

    Un appel mode=duo génère déjà les DEUX dossiers solo en plus du dossier Duo
    (cf. buildSoloCmds appelé deux fois côté API). Demander en plus un mode=solo
    pour ces mêmes utilisateurs ferait télécharger leurs images deux fois : on ne
    lance donc un solo que pour les utilisateurs hors de la paire Duo.
    """
    users: list[dict[str, Any]] = entry.data.get(CONF_USERS, [])
    base_dir = normalize_dir(entry.data.get(CONF_DIR, DEFAULT_DIR)) or DEFAULT_DIR
    duo_pair = entry.data.get(CONF_DUO_PAIR)
    # scale est stocké en entier dans les options, mais aiohttp exige des
    # valeurs de chaîne dans params.
    common = {"dir": base_dir, "scale": str(scale), "lang": lang}

    # Les entrées créées avant l'ajout du mode Duo n'ont pas de duo_pair. Avec
    # exactement deux utilisateurs exploitables, le duo est sans ambiguïté :
    # sans ce repli, le dossier Duo ne serait jamais synchronisé.
    if not duo_pair:
        usable = [u[CONF_USER_FOLDER] for u in users if u.get(CONF_BITMOJI_ID)]
        if len(usable) == 2:
            duo_pair = usable
            _LOGGER.debug(
                "Aucune paire Duo configurée : déduite automatiquement (%s + %s)",
                usable[0],
                usable[1],
            )

    calls: list[dict[str, str]] = []
    covered: set[str] = set()

    if duo_pair:
        u1 = next((u for u in users if u.get(CONF_USER_FOLDER) == duo_pair[0]), None)
        u2 = next((u for u in users if u.get(CONF_USER_FOLDER) == duo_pair[1]), None)
        if u1 and u2 and u1.get(CONF_BITMOJI_ID) and u2.get(CONF_BITMOJI_ID):
            calls.append(
                {
                    **common,
                    "id1": u1[CONF_BITMOJI_ID],
                    "name1": u1[CONF_USER_FOLDER],
                    "id2": u2[CONF_BITMOJI_ID],
                    "name2": u2[CONF_USER_FOLDER],
                    "mode": "duo",
                }
            )
            covered = {u1[CONF_USER_FOLDER], u2[CONF_USER_FOLDER]}

    for user in users:
        folder = user.get(CONF_USER_FOLDER)
        if folder in covered:
            continue
        if not user.get(CONF_BITMOJI_ID):
            _LOGGER.debug(
                "Pas de Bitmoji ID configuré pour %s, import solo ignoré", folder
            )
            continue
        calls.append(
            {
                **common,
                "id1": user[CONF_BITMOJI_ID],
                "name1": folder,
                "mode": "solo",
            }
        )

    return calls


def _fail(state: SyncState, reason: str) -> None:
    """Marque la synchro en erreur ET l'écrit dans le journal.

    Historiquement certains chemins d'échec ne faisaient que renseigner
    l'attribut du capteur : l'erreur était donc invisible dans les logs, et
    introuvable pour qui ne connaissait pas l'attribut « raison ».
    """
    _LOGGER.error("Synchronisation Avatar Explorer en échec : %s", reason)
    state.async_mark_checked(STATUS_ERROR, reason)


async def _async_collect_files(
    session: aiohttp.ClientSession,
    calls: list[dict[str, str]],
    base_dir: str,
    allowed: Collection[str],
) -> tuple[dict[str, str], list[str]]:
    """Fusionne les exports dans un seul dictionnaire.

    Si deux exports désignent le même fichier, il n'est récupéré qu'une fois.
    Retourne (fichiers, noms des appels en échec).
    """
    files: dict[str, str] = {}
    failed_calls: list[str] = []
    for params in calls:
        pairs = await async_fetch_file_list(session, params, base_dir, allowed)
        if pairs is None:
            failed_calls.append(params.get("name1", "?"))
            continue
        files.update(pairs)
    return files, failed_calls


async def async_run_sync(
    hass: HomeAssistant,
    entry: ConfigEntry,
    state: SyncState,
    *,
    force: bool = False,
    refresh_all: bool = False,
) -> bool:
    """Un passage de synchronisation. Retourne True s'il s'est terminé sans échec.

    Ne pas appeler directement : passer par SyncManager, qui sérialise les
    passages et n'en perd aucun.
    """
    session = aiohttp_client.async_get_clientsession(hass)

    base_dir = normalize_dir(entry.data.get(CONF_DIR, DEFAULT_DIR))
    if base_dir is None:
        _fail(
            state,
            f"Dossier configuré invalide : {entry.data.get(CONF_DIR)!r} (lettres, "
            "chiffres, _, - et / uniquement).",
        )
        return False

    try:
        aide = await async_fetch_aide_json(session)
    except (CatalogError, aiohttp.ClientError) as err:
        _fail(state, f"Catalogue injoignable ({AIDE_JSON_URL}) : {err}")
        return False
    remote_iso: str = aide["last_updated_iso"]

    local_iso = state.catalog_version
    # refresh_all implique une réécriture : inutile de comparer les horodatages.
    # Des fichiers en échec lors d'un réimport complet restent aussi à reprendre,
    # même si le catalogue distant n'a pas bougé.
    needs_update = force or refresh_all or not local_iso or bool(state.retry_paths)
    if not needs_update:
        try:
            needs_update = _parse_iso(remote_iso) > _parse_iso(local_iso)
        except ValueError:
            needs_update = True

    if not needs_update:
        state.async_mark_checked(STATUS_UP_TO_DATE)
        return True

    scale = entry.options.get(CONF_SCALE, DEFAULT_SCALE)
    lang = entry.options.get(CONF_LANG, DEFAULT_LANG)
    calls = build_export_calls(entry, scale, lang)
    if not calls:
        configured = [
            u.get(CONF_USER_FOLDER, "?") for u in entry.data.get(CONF_USERS, [])
        ]
        _fail(
            state,
            "Aucun ID Bitmoji configuré (utilisateurs : "
            + (", ".join(configured) or "aucun")
            + "). Renseignez-les dans Paramètres > Appareils et services > "
            "Avatar Explorer > Configurer.",
        )
        return False

    _LOGGER.debug(
        "Appels export prévus : %s",
        [(c["mode"], c["name1"], c.get("name2", "-")) for c in calls],
    )

    allowed = allowed_folders(entry)
    files, failed_calls = await _async_collect_files(session, calls, base_dir, allowed)
    if failed_calls:
        _fail(
            state,
            f"L'API export a échoué pour : {', '.join(failed_calls)}. "
            "Vérifiez l'ID Bitmoji de ces utilisateurs et le détail ci-dessus dans le journal.",
        )
        return False

    if refresh_all:
        _LOGGER.info(
            "Avatar Explorer : réimport complet demandé (ID Bitmoji ou qualité "
            "modifiés), les %s fichiers vont être réécrits",
            len(files),
        )

    retry = frozenset(state.retry_paths)
    report = await async_download_files(
        hass,
        session,
        base_dir,
        files,
        allowed=allowed,
        refresh_all=refresh_all,
        retry=retry,
    )
    downloaded, skipped, failures = report.downloaded, report.skipped, report.failures
    state.async_set_stats(downloaded, skipped, failures, len(files))

    if refresh_all:
        # Le passage complet a eu lieu, même partiel : on ne le relance pas en
        # boucle (414 Mo à chaque passage pour un seul fichier récalcitrant).
        # Seuls les fichiers en échec sont mémorisés et repris ensuite.
        state.async_finish_full_refresh(report.failed_paths)
    elif retry:
        # Fichiers repris de ce passage : ceux qui échouent encore restent dus ;
        # ceux qui ont disparu du catalogue (changement de langue) sont oubliés.
        failed = set(report.failed_paths)
        state.async_set_retry_paths([p for p in retry if p in failed])

    # Recensement des orphelins, après téléchargement pour ne pas compter comme
    # orphelins des fichiers que la synchro venait justement de récupérer.
    orphans = await hass.async_add_executor_job(
        _scan_orphans, Path(hass.config.path("www")), base_dir, set(files), allowed
    )
    state.async_set_orphans(orphans)
    if orphans:
        _LOGGER.info(
            "%s fichier(s) local(aux) ne sont plus au catalogue (aucune suppression "
            "automatique) : %s%s",
            len(orphans),
            ", ".join(orphans[:5]),
            "..." if len(orphans) > 5 else "",
        )

    if failures:
        # On ne mémorise pas l'horodatage distant : la prochaine vérification
        # doit retenter les fichiers manquants plutôt que se croire à jour.
        reason = f"{failures} fichier(s) en échec"
        if report.aborted:
            reason = f"{reason} ({report.aborted})"
        state.async_mark_checked(STATUS_PARTIAL, reason)
        _LOGGER.warning(
            "Avatar Explorer : %s téléchargés, %s échecs (nouvelle tentative à la prochaine vérification)",
            downloaded,
            failures,
        )
        return False

    state.async_mark_synced(remote_iso)
    _LOGGER.info(
        "Avatar Explorer : synchronisation terminée (%s nouveau(x) fichier(s), %s déjà présent(s))",
        downloaded,
        skipped,
    )
    return True


async def async_delete_orphans(
    hass: HomeAssistant, entry: ConfigEntry, state: SyncState
) -> tuple[int, int, int]:
    """Supprime les fichiers du catalogue local qui n'y figurent plus.

    Le recensement est TOUJOURS refait à cet instant plutôt que de réutiliser
    celui de la dernière synchro : agir sur une liste vieille de plusieurs
    heures reviendrait à supprimer sur la foi d'un état périmé.

    Ne pas appeler directement : passer par SyncManager, qui l'exécute sous le
    même verrou que les synchros.

    Retourne (supprimés, protégés, échecs).
    """
    session = aiohttp_client.async_get_clientsession(hass)
    base_dir = normalize_dir(entry.data.get(CONF_DIR, DEFAULT_DIR))
    if base_dir is None:
        _LOGGER.error("Nettoyage annulé : dossier configuré invalide")
        return 0, 0, 0

    scale = entry.options.get(CONF_SCALE, DEFAULT_SCALE)
    lang = entry.options.get(CONF_LANG, DEFAULT_LANG)
    calls = build_export_calls(entry, scale, lang)
    if not calls:
        _LOGGER.error("Nettoyage annulé : aucun ID Bitmoji configuré")
        return 0, 0, 0

    # Sans la liste complète attendue, tout serait considéré comme orphelin :
    # au moindre échec de l'API, on s'arrête plutôt que de supprimer à l'aveugle.
    allowed = allowed_folders(entry)
    files, failed_calls = await _async_collect_files(session, calls, base_dir, allowed)
    if failed_calls:
        _LOGGER.error(
            "Nettoyage annulé : le catalogue n'a pas pu être récupéré, "
            "impossible de distinguer les orphelins"
        )
        return 0, 0, 0

    www_root = Path(hass.config.path("www"))
    orphans = await hass.async_add_executor_job(
        _scan_orphans, www_root, base_dir, set(files), allowed
    )
    if not orphans:
        _LOGGER.info("Nettoyage : aucun orphelin à supprimer")
        state.async_set_orphans([])
        return 0, 0, 0

    in_use = _files_in_use(hass)
    protected = [o for o in orphans if o in in_use]
    to_delete = [o for o in orphans if o not in in_use]

    if protected:
        _LOGGER.warning(
            "%s fichier(s) conservé(s) car encore utilisé(s) comme avatar : %s",
            len(protected),
            ", ".join(protected),
        )

    _LOGGER.info("Nettoyage : suppression de %s fichier(s) orphelin(s)", len(to_delete))
    deleted, failed = await hass.async_add_executor_job(
        _delete_files, www_root, base_dir, to_delete, allowed
    )
    state.async_set_orphans(protected + failed)

    _LOGGER.info(
        "Nettoyage terminé : %s supprimé(s), %s protégé(s), %s échec(s)",
        deleted,
        len(protected),
        len(failed),
    )
    return deleted, len(protected), len(failed)

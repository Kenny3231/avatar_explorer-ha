"""Synchronisation du catalogue de poses depuis avatar-explorer.pages.dev.

Le principe : /api/export renvoie un script bash déterministe listant tous les
fichiers à récupérer. On le **lit** au lieu de l'exécuter -- ça évite de lancer
du code distant sans supervision à chaque vérification, et ça permet de
comparer au disque pour ne télécharger que le delta. En régime normal, le
catalogue ne bouge qu'une fois par semaine, donc la quasi-totalité des passages
se solde par zéro téléchargement.

Le site s'appelait « Pose Explorer » jusqu'en juillet 2026 ; ce module se
nommait alors pose_explorer.py.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from homeassistant.helpers import aiohttp_client

from .const import (
    AIDE_JSON_URL,
    CONF_LANG,
    CONF_SCALE,
    DEFAULT_DIR,
    DEFAULT_LANG,
    DEFAULT_SCALE,
    DOMAIN,
    EXPORT_API_URL,
)

_LOGGER = logging.getLogger(__name__)

REMOTE_WWW_PREFIX = "/config/www/"
DOWNLOAD_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Ancré sur "wget" en début de ligne : une regex libre matcherait n'importe
# quelle ligne contenant le motif, y compris un jour où l'API générerait
# autre chose que des téléchargements.
WGET_LINE_RE = re.compile(
    r'^wget\s+-q\s+(?:-U\s+"[^"]*"\s+)?-O\s+"([^"]+)"\s+"([^"]+)"\s*$',
    re.MULTILINE,
)

# Le catalogue fait ~3750 fichiers : assez de parallélisme pour que le premier
# import ne dure pas des heures, assez peu pour ne pas saturer la connexion.
DOWNLOAD_CONCURRENCY = 6

# Nombre d'échecs détaillés dans le journal avant bascule en debug.
MAX_REPORTED_FAILURES = 10


def _fail(sync_entity, reason: str, exc_info=False) -> None:
    """Marque la synchro en erreur ET l'écrit dans le journal.

    Historiquement certains chemins d'échec ne faisaient que renseigner
    l'attribut du capteur : l'erreur était donc invisible dans les logs, et
    introuvable pour qui ne connaissait pas l'attribut « raison ».
    """
    _LOGGER.error("Synchronisation Avatar Explorer en échec : %s", reason, exc_info=exc_info)
    sync_entity.mark_checked("erreur", reason)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_file(path: str, content: bytes) -> None:
    """Écriture atomique : fichier temporaire puis rename.

    Sans ça, une coupure en cours d'écriture laisse un PNG tronqué que la carte
    afficherait comme une image cassée, sans moyen de le détecter ensuite.

    Le suffixe aléatoire est indispensable : avec un nom fixe (« .part »), deux
    écritures simultanées vers la même destination partagent le fichier
    temporaire, et le second os.replace échoue en FileNotFoundError parce que
    le premier vient de le consommer.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{uuid4().hex[:8]}.part")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, p)
    except Exception:
        # Ne pas laisser traîner un temporaire orphelin si le rename échoue.
        tmp.unlink(missing_ok=True)
        raise


async def async_fetch_aide_json(session) -> dict:
    # Même User-Agent que pour les images : Cloudflare filtre certains agents
    # de bibliothèques (Python-urllib est déjà rejeté en 403). Envoyer un UA
    # de navigateur évite de dépendre de celui qu'aiohttp choisit.
    async with session.get(AIDE_JSON_URL, headers=DOWNLOAD_HEADERS, timeout=20) as resp:
        resp.raise_for_status()
        return await resp.json()


async def async_fetch_file_list(session, params: dict) -> list[tuple[str, str]] | None:
    """Récupère le script d'export et en extrait les couples (chemin relatif, URL).

    Le script n'est jamais exécuté : on le lit. Ça évite de lancer du code
    distant sans supervision à chaque vérification automatique, et ça permet de
    comparer au disque avant de télécharger quoi que ce soit.
    """
    try:
        async with session.get(
            EXPORT_API_URL, params=params, headers=DOWNLOAD_HEADERS, timeout=60
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                # L'API renvoie un message explicite en texte brut sur les 400
                # (« Paramètre id1 invalide », etc.). raise_for_status() le
                # jetterait : on le remonte tel quel, c'est le plus utile.
                _LOGGER.error(
                    "Export Avatar Explorer refusé (HTTP %s) pour %s : %s",
                    resp.status,
                    params,
                    body.strip()[:300],
                )
                return None
            script = body
    except Exception as err:
        _LOGGER.error(
            "Appel export Avatar Explorer impossible (%s) : %r", params, err, exc_info=True
        )
        return None

    pairs = WGET_LINE_RE.findall(script)
    if not pairs:
        _LOGGER.error(
            "Réponse export sans aucun téléchargement pour %s (%s octets reçus) : %s",
            params,
            len(script),
            script[:200],
        )
        return None

    result = []
    for dest, url in pairs:
        # Le script code en dur /config/www/ ; on ne garde que le relatif et on
        # refuse tout ce qui sortirait de www/.
        if not dest.startswith(REMOTE_WWW_PREFIX):
            _LOGGER.warning("Destination hors de www/ ignorée : %s", dest)
            continue
        relative = dest[len(REMOTE_WWW_PREFIX):]
        if ".." in Path(relative).parts:
            _LOGGER.warning("Destination suspecte ignorée : %s", dest)
            continue
        result.append((relative, url))

    return result


def _select_missing(www_root: str, files: dict, refresh_all: bool) -> list:
    """Ne garde que les fichiers absents du disque (appelé en executor).

    Les metadata_*.json sont toujours reprises : on n'arrive ici que si le
    catalogue distant a changé, donc leur contenu a changé aussi.

    refresh_all court-circuite la comparaison. C'est indispensable quand un ID
    Bitmoji change : les noms de fichiers générés sont identiques (ils dérivent
    du nom de dossier, pas de l'ID), seul le contenu diffère. Sans ce drapeau,
    le différentiel sauterait tout et l'ancien avatar resterait affiché.
    """
    if refresh_all:
        return list(files.items())

    missing = []
    for relative, url in files.items():
        name = Path(relative).name
        if name.startswith("metadata_") or not os.path.exists(os.path.join(www_root, relative)):
            missing.append((relative, url))
    return missing


def _scan_orphans(www_root: str, expected) -> list:
    """Fichiers présents en local mais absents du catalogue (appelé en executor).

    Le périmètre est volontairement étroit : on ne regarde QUE les dossiers que
    le catalogue alimente lui-même (images/avatar/Kenny, .../Duo...), et sans
    descendre dans d'éventuels sous-dossiers. Élargir ce scan ferait passer pour
    orphelin tout le reste de www/ -- une première version de ce code balayait
    images/ en entier et considérait 3359 fichiers sans rapport comme à jeter.
    """
    expected = set(expected)
    roots = {os.path.dirname(r) for r in expected if os.path.dirname(r)}

    orphans = []
    for root in sorted(roots):
        base = os.path.join(www_root, root)
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if not os.path.isfile(full):
                continue
            relative = f"{root}/{name}"
            # Les .part sont des temporaires d'une écriture en cours, pas des
            # orphelins : les compter reviendrait à courir après la synchro.
            if relative not in expected and not relative.endswith(".part"):
                orphans.append(relative)
    return sorted(orphans)


def _delete_files(www_root: str, relatives) -> tuple:
    """Supprime la liste donnée (appelé en executor). Retourne (supprimés, échecs)."""
    ok = 0
    failed = []
    for relative in relatives:
        try:
            os.remove(os.path.join(www_root, relative))
            ok += 1
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Suppression impossible de %s : %s", relative, err)
            failed.append(relative)
    return ok, failed


def _files_in_use(hass) -> set:
    """Images actuellement référencées par les entités text.

    Supprimer l'avatar affiché d'un utilisateur casserait son affichage sans
    qu'aucune erreur ne le signale : ces fichiers sont exclus du nettoyage même
    s'ils ne sont plus au catalogue.
    """
    in_use = set()
    for state in hass.states.async_all("text"):
        value = state.state or ""
        if value.startswith("/local/"):
            in_use.add(value[len("/local/"):])
    return in_use


async def async_download_files(hass, session, files: dict, refresh_all: bool = False):
    """Télécharge en parallèle uniquement ce qui manque.

    Retourne (téléchargés, ignorés car déjà présents, échecs).
    """
    www_root = hass.config.path("www")
    missing = await hass.async_add_executor_job(
        _select_missing, www_root, files, refresh_all
    )
    skipped = len(files) - len(missing)

    if not missing:
        return 0, skipped, 0

    _LOGGER.info(
        "Avatar Explorer : %s fichier(s) à récupérer, %s déjà présent(s)",
        len(missing),
        skipped,
    )

    semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    # Un échec massif (réseau coupé en plein import) produirait 3750 lignes et
    # déclencherait le garde-fou « logging too frequently » de Home Assistant,
    # qui tronque le journal. On détaille les premiers, on compte les autres.
    reported = 0

    async def _fetch(relative: str, url: str):
        """Retourne True, "absent" (404 définitif) ou False (échec temporaire)."""
        nonlocal reported
        local_path = str(Path(www_root) / relative)
        async with semaphore:
            try:
                async with session.get(url, headers=DOWNLOAD_HEADERS, timeout=60) as resp:
                    # Un 404 signifie que cette pose n'existe pas pour cet
                    # avatar : réessayer ne servira jamais à rien. On le
                    # distingue d'une panne réseau, qui elle mérite un retry.
                    if resp.status == 404:
                        _LOGGER.debug("Pose absente chez Bitmoji (404) : %s", relative)
                        return "absent"
                    if resp.status != 200:
                        raise ValueError(f"HTTP {resp.status}")
                    content = await resp.read()
                if not content:
                    raise ValueError("réponse vide")
                await hass.async_add_executor_job(_write_file, local_path, content)
                return True
            except Exception as err:
                reported += 1
                if reported <= MAX_REPORTED_FAILURES:
                    _LOGGER.warning("Échec téléchargement %s -> %s : %s", url, local_path, err)
                elif reported == MAX_REPORTED_FAILURES + 1:
                    _LOGGER.warning(
                        "Plus de %s échecs de téléchargement : les suivants ne sont "
                        "journalisés qu'en niveau debug.",
                        MAX_REPORTED_FAILURES,
                    )
                else:
                    _LOGGER.debug("Échec téléchargement %s : %s", relative, err)
                return False

    results = await asyncio.gather(*(_fetch(r, u) for r, u in missing))
    downloaded = sum(1 for r in results if r is True)
    absent = sum(1 for r in results if r == "absent")
    failures = sum(1 for r in results if r is False)

    if absent:
        _LOGGER.info(
            "%s pose(s) inexistante(s) chez Bitmoji (404) : ignorées, elles ne "
            "bloquent pas la synchronisation.",
            absent,
        )
    return downloaded, skipped + absent, failures


def _build_export_calls(entry, scale, lang) -> list:
    """Construit les appels /api/export à effectuer.

    Un appel mode=duo génère déjà les DEUX dossiers solo en plus du dossier Duo
    (cf. buildSoloCmds appelé deux fois côté API). Demander en plus un mode=solo
    pour ces mêmes utilisateurs ferait télécharger leurs images deux fois : on ne
    lance donc un solo que pour les utilisateurs hors de la paire Duo.
    """
    users = entry.data.get("users", [])
    base_dir = entry.data.get("dir", DEFAULT_DIR)
    duo_pair = entry.data.get("duo_pair")
    # scale est stocké en entier dans les options, mais aiohttp exige des
    # valeurs de chaîne dans params.
    common = {"dir": base_dir, "scale": str(scale), "lang": lang}

    # Les entrées créées avant l'ajout du mode Duo n'ont pas de duo_pair. Avec
    # exactement deux utilisateurs exploitables, le duo est sans ambiguïté :
    # sans ce repli, le dossier Duo ne serait jamais synchronisé.
    if not duo_pair:
        usable = [u["user_id_folder"] for u in users if u.get("bitmoji_id")]
        if len(usable) == 2:
            duo_pair = usable
            _LOGGER.info(
                "Aucune paire Duo configurée : déduite automatiquement (%s + %s)",
                usable[0],
                usable[1],
            )

    calls = []
    covered = set()

    if duo_pair:
        u1 = next((u for u in users if u.get("user_id_folder") == duo_pair[0]), None)
        u2 = next((u for u in users if u.get("user_id_folder") == duo_pair[1]), None)
        if u1 and u2 and u1.get("bitmoji_id") and u2.get("bitmoji_id"):
            calls.append({
                **common,
                "id1": u1["bitmoji_id"],
                "name1": u1["user_id_folder"],
                "id2": u2["bitmoji_id"],
                "name2": u2["user_id_folder"],
                "mode": "duo",
            })
            covered = {u1["user_id_folder"], u2["user_id_folder"]}

    for user in users:
        folder = user.get("user_id_folder")
        if folder in covered:
            continue
        if not user.get("bitmoji_id"):
            _LOGGER.debug("Pas de Bitmoji ID configuré pour %s, import solo ignoré", folder)
            continue
        calls.append({
            **common,
            "id1": user["bitmoji_id"],
            "name1": folder,
            "mode": "solo",
        })

    return calls


def _get_lock(hass, entry) -> asyncio.Lock:
    """Verrou par entrée, créé à la demande.

    Six chemins peuvent déclencher une synchro (démarrage, intervalle, service,
    deux boutons, changement d'options). Sans sérialisation, deux passages
    téléchargent les mêmes fichiers en parallèle : travail doublé et collisions
    à l'écriture.
    """
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    lock = store.get("sync_lock")
    if lock is None:
        lock = store["sync_lock"] = asyncio.Lock()
    return lock


async def async_check_for_update(hass, entry, force: bool = False, refresh_all: bool = False) -> None:
    lock = _get_lock(hass, entry)
    if lock.locked():
        # On ignore plutôt que d'attendre : les déclencheurs se ressemblent
        # tous, empiler les passages ne ferait que refaire le même travail.
        _LOGGER.info("Synchronisation déjà en cours, ce déclenchement est ignoré")
        return

    async with lock:
        await _async_check_for_update(hass, entry, force, refresh_all)


async def _async_check_for_update(hass, entry, force: bool, refresh_all: bool) -> None:
    session = aiohttp_client.async_get_clientsession(hass)
    sync_entity = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("sync_entity")
    if sync_entity is None:
        _LOGGER.debug("Entité de synchro Avatar Explorer pas encore prête, vérification ignorée")
        return

    try:
        aide = await async_fetch_aide_json(session)
        remote_iso = aide["last_updated_iso"]
    except Exception as err:
        # exc_info : sans la trace, une erreur réseau aiohttp se résume souvent
        # à un message vide, impossible à diagnostiquer.
        _fail(sync_entity, f"Catalogue injoignable ({AIDE_JSON_URL}) : {err!r}", exc_info=True)
        return

    local_iso = sync_entity.native_value
    # refresh_all implique une réécriture : inutile de comparer les horodatages.
    needs_update = force or refresh_all or not local_iso
    if not needs_update:
        try:
            needs_update = _parse_iso(remote_iso) > _parse_iso(local_iso)
        except ValueError:
            needs_update = True

    if not needs_update:
        sync_entity.mark_checked("a_jour")
        return

    scale = entry.options.get(CONF_SCALE, DEFAULT_SCALE)
    lang = entry.options.get(CONF_LANG, DEFAULT_LANG)
    calls = _build_export_calls(entry, scale, lang)
    if not calls:
        configured = [u.get("user_id_folder", "?") for u in entry.data.get("users", [])]
        _fail(
            sync_entity,
            "Aucun ID Bitmoji configuré (utilisateurs : "
            + (", ".join(configured) or "aucun")
            + "). Renseignez-les dans Paramètres > Appareils et services > "
            "Avatar Explorer > Configurer.",
        )
        return

    _LOGGER.debug(
        "Appels export prévus : %s",
        [(c["mode"], c["name1"], c.get("name2", "-")) for c in calls],
    )

    # Fusion de tous les appels dans un seul dictionnaire : si deux exports
    # désignent le même fichier, il n'est récupéré qu'une fois.
    files = {}
    failed_calls = []
    for params in calls:
        pairs = await async_fetch_file_list(session, params)
        if pairs is None:
            failed_calls.append(params.get("name1", "?"))
            continue
        files.update(pairs)

    if failed_calls:
        _fail(
            sync_entity,
            f"L'API export a échoué pour : {', '.join(failed_calls)}. "
            "Vérifiez l'ID Bitmoji de ces utilisateurs et le détail ci-dessus dans le journal.",
        )
        return

    if refresh_all:
        _LOGGER.info(
            "Avatar Explorer : réimport complet demandé (ID Bitmoji modifié), "
            "les %s fichiers vont être réécrits",
            len(files),
        )

    downloaded, skipped, failures = await async_download_files(
        hass, session, files, refresh_all
    )
    sync_entity.set_stats(downloaded, skipped, failures, len(files))

    # Recensement des orphelins, après téléchargement pour ne pas compter comme
    # orphelins des fichiers que la synchro venait justement de récupérer.
    orphans = await hass.async_add_executor_job(
        _scan_orphans, hass.config.path("www"), set(files)
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["orphans"] = orphans
    sync_entity.set_orphans(orphans)
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
        sync_entity.mark_checked("partielle", f"{failures} fichier(s) en échec")
        _LOGGER.warning(
            "Avatar Explorer : %s téléchargés, %s échecs (nouvelle tentative à la prochaine vérification)",
            downloaded,
            failures,
        )
    else:
        sync_entity.mark_synced(remote_iso)
        _LOGGER.info(
            "Avatar Explorer : synchronisation terminée (%s nouveau(x) fichier(s), %s déjà présent(s))",
            downloaded,
            skipped,
        )


async def async_delete_orphans(hass, entry) -> tuple:
    """Supprime les fichiers du catalogue local qui n'y figurent plus.

    Le recensement est TOUJOURS refait à cet instant plutôt que de réutiliser
    celui de la dernière synchro : agir sur une liste vieille de plusieurs
    heures reviendrait à supprimer sur la foi d'un état périmé.

    Retourne (supprimés, protégés, échecs).
    """
    session = aiohttp_client.async_get_clientsession(hass)
    scale = entry.options.get(CONF_SCALE, DEFAULT_SCALE)
    lang = entry.options.get(CONF_LANG, DEFAULT_LANG)

    calls = _build_export_calls(entry, scale, lang)
    if not calls:
        _LOGGER.error("Nettoyage annulé : aucun ID Bitmoji configuré")
        return 0, 0, 0

    # Sans la liste complète attendue, tout serait considéré comme orphelin :
    # au moindre échec de l'API, on s'arrête plutôt que de supprimer à l'aveugle.
    files = {}
    for params in calls:
        pairs = await async_fetch_file_list(session, params)
        if pairs is None:
            _LOGGER.error(
                "Nettoyage annulé : le catalogue n'a pas pu être récupéré, "
                "impossible de distinguer les orphelins"
            )
            return 0, 0, 0
        files.update(pairs)

    www_root = hass.config.path("www")
    orphans = await hass.async_add_executor_job(_scan_orphans, www_root, set(files))
    if not orphans:
        _LOGGER.info("Nettoyage : aucun orphelin à supprimer")
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
        _delete_files, www_root, to_delete
    )

    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store["orphans"] = protected
    sync_entity = store.get("sync_entity")
    if sync_entity is not None:
        sync_entity.set_orphans(protected)

    _LOGGER.info(
        "Nettoyage terminé : %s supprimé(s), %s protégé(s), %s échec(s)",
        deleted, len(protected), len(failed),
    )
    return deleted, len(protected), len(failed)

"""État d'exécution d'une entrée : état de synchro persistant et file de synchro.

L'état de synchro (version du catalogue, dernière vérification, compteurs...)
vivait auparavant dans le capteur sensor.avatar_explorer_sync, qui
s'enregistrait dans hass.data depuis son constructeur. Si l'entité était
désactivée, plus aucune synchro ne pouvait avoir lieu. Il est désormais tenu
ici, dans un helpers.storage.Store indépendant des entités, qui ne font plus
que l'afficher.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.restore_state import async_get as async_get_restore_state
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import catalog
from .const import (
    DOMAIN,
    MAX_RETRY_PATHS,
    STATUS_ERROR,
    STATUS_UNKNOWN,
    STATUS_UP_TO_DATE,
    SYNC_STATUSES,
    sync_signal,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Les écritures sont regroupées : une synchro enchaîne plusieurs mises à jour
# (compteurs, orphelins, statut) en quelques millisecondes.
SAVE_DELAY = 5

# entity_id historique du capteur maître, utilisé en repli pour la migration
# si le registre ne le connaît pas.
LEGACY_SYNC_ENTITY_ID = "sensor.avatar_explorer_sync"

# Attributs historiques du capteur, conservés à l'identique : automatisations
# et cartes peuvent les lire.
_DEFAULT_ATTRS: dict[str, Any] = {
    "last_checked": None,
    "last_success": None,
    "status": STATUS_UNKNOWN,
    "error": None,
    "telecharges": None,
    "deja_presents": None,
    "echecs": None,
    "total_catalogue": None,
    "orphelins": None,
    "orphelins_exemples": [],
}
# Attributs que l'ancienne version restaurait au redémarrage.
_LEGACY_RESTORED_ATTRS = ("last_checked", "last_success", "status", "error")


def sync_sensor_unique_id(entry_id: str) -> str:
    """unique_id historique du capteur maître de synchro (à ne pas changer)."""
    return f"{DOMAIN}_sync_{entry_id}"


class SyncState:
    """État de synchronisation d'une entrée, persisté sur disque."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Prépare l'état ; async_load doit être appelé avant usage."""
        self._hass = hass
        self._entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.catalog_version: str | None = None
        # Réimport complet demandé mais pas encore abouti (voir SyncManager).
        self.refresh_all_pending = False
        # Fichiers en échec lors du dernier réimport complet : présents sur le
        # disque avec l'ancien contenu, ils sont repris aux passages suivants
        # (voir catalog._select_missing). Bornée à MAX_RETRY_PATHS.
        self.retry_paths: list[str] = []
        self.attrs: dict[str, Any] = dict(_DEFAULT_ATTRS)
        # Vrai entre une modification et son écriture sur disque.
        self._dirty = False
        # Après async_close (déchargement de l'entrée), plus aucune écriture :
        # une sauvegarde différée qui aboutirait après async_remove_entry
        # recréerait le fichier de l'entrée supprimée.
        self._closed = False

    async def async_load(self) -> None:
        """Charge l'état, en migrant depuis l'état restauré du capteur si besoin."""
        data = await self._store.async_load()
        if data is None:
            data = self._legacy_state()
            if data is not None:
                _LOGGER.info(
                    "État de synchro Avatar Explorer repris de l'ancien capteur "
                    "(catalogue %s) : pas de retéléchargement",
                    data.get("catalog_version"),
                )
                await self._store.async_save(data)
        if data:
            self._apply(data)

    def _apply(self, data: dict[str, Any]) -> None:
        self.catalog_version = data.get("catalog_version")
        self.refresh_all_pending = bool(data.get("refresh_all_pending", False))
        retry = data.get("retry_paths")
        if isinstance(retry, list):
            self.retry_paths = [p for p in retry if isinstance(p, str)][
                :MAX_RETRY_PATHS
            ]
        for key in _DEFAULT_ATTRS:
            if key in data:
                self.attrs[key] = data[key]
        if self.attrs.get("status") not in SYNC_STATUSES:
            self.attrs["status"] = STATUS_UNKNOWN

    @callback
    def _legacy_state(self) -> dict[str, Any] | None:
        """Dernier état connu de l'ancien capteur (RestoreEntity), s'il existe.

        Lu dans les données de restauration chargées au démarrage : l'entité
        n'est pas encore ajoutée à ce stade, l'état courant serait inutile.
        """
        entity_id = (
            er.async_get(self._hass).async_get_entity_id(
                "sensor", DOMAIN, sync_sensor_unique_id(self._entry_id)
            )
            or LEGACY_SYNC_ENTITY_ID
        )
        stored = async_get_restore_state(self._hass).last_states.get(entity_id)
        if stored is None:
            return None
        state = stored.state
        data: dict[str, Any] = {
            key: state.attributes.get(key)
            for key in _LEGACY_RESTORED_ATTRS
            if state.attributes.get(key) is not None
        }
        if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            data["catalog_version"] = state.state
        return data or None

    def _as_dict(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "refresh_all_pending": self.refresh_all_pending,
            "retry_paths": self.retry_paths,
            **self.attrs,
        }

    def _data_to_save(self) -> dict[str, Any]:
        self._dirty = False
        return self._as_dict()

    @callback
    def _async_schedule_save(self) -> None:
        """Sauvegarde différée, sauf si l'entrée est déchargée."""
        if self._closed:
            return
        self._dirty = True
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    @callback
    def _async_changed(self) -> None:
        """Persiste (en différé) et réveille les entités d'affichage."""
        self._async_schedule_save()
        async_dispatcher_send(self._hass, sync_signal(self._entry_id))

    @callback
    def async_set_refresh_all_pending(self, *, pending: bool) -> None:
        """Mémorise qu'un réimport complet reste à faire (survit au redémarrage)."""
        if self.refresh_all_pending != pending:
            self.refresh_all_pending = pending
            self._async_schedule_save()

    @callback
    def async_finish_full_refresh(self, failed_paths: list[str]) -> None:
        """Réimport complet mené à son terme, même partiellement.

        Il n'est plus dû : seuls les fichiers en échec seront repris, aux
        passages suivants. Relancer tout le réimport pour un seul fichier
        récalcitrant retéléchargeait ~400 Mo à chaque vérification.

        Au-delà de MAX_RETRY_PATHS échecs, le réimport n'a pas vraiment eu lieu
        (réseau coupé, passage interrompu) : il reste dû, en entier.
        """
        if len(failed_paths) > MAX_RETRY_PATHS:
            _LOGGER.warning(
                "Réimport complet : %s fichier(s) en échec, il sera relancé en "
                "entier au prochain passage",
                len(failed_paths),
            )
            self.retry_paths = []
            self.refresh_all_pending = True
        else:
            self.retry_paths = sorted(failed_paths)
            self.refresh_all_pending = False
        self._async_schedule_save()

    @callback
    def async_set_retry_paths(self, paths: list[str]) -> None:
        """Fichiers d'un réimport complet encore à reprendre."""
        paths = sorted(paths)[:MAX_RETRY_PATHS]
        if paths != self.retry_paths:
            self.retry_paths = paths
            self._async_schedule_save()

    @callback
    def async_set_orphans(self, orphans: list[str]) -> None:
        """Fichiers locaux absents du catalogue.

        Jamais supprimés automatiquement : le bouton de nettoyage est le seul à
        le faire.
        """
        self.attrs["orphelins"] = len(orphans)
        # Liste tronquée : l'état d'une entité HA n'est pas fait pour stocker
        # des milliers d'entrées (un changement de langue en produit ~1000).
        self.attrs["orphelins_exemples"] = orphans[:20]
        self._async_changed()

    @callback
    def async_set_stats(
        self, downloaded: int, skipped: int, failures: int, total: int
    ) -> None:
        """Compteurs du dernier import.

        Ils permettent de voir d'un coup d'œil si la synchro différentielle
        fait son travail (deja_presents élevé = normal).
        """
        self.attrs.update(
            {
                "telecharges": downloaded,
                "deja_presents": skipped,
                "echecs": failures,
                "total_catalogue": total,
            }
        )
        self._async_changed()

    @callback
    def async_mark_checked(self, status: str, error: str | None = None) -> None:
        """Résultat d'une vérification (réussie ou non)."""
        self.attrs["last_checked"] = dt_util.now().isoformat()
        self.attrs["status"] = status if status in SYNC_STATUSES else STATUS_UNKNOWN
        self.attrs["error"] = error
        self._async_changed()

    @callback
    def async_mark_synced(self, iso_value: str) -> None:
        """Synchro complète : on mémorise la version du catalogue distant."""
        self.catalog_version = iso_value
        self.attrs["last_success"] = dt_util.now().isoformat()
        self.async_mark_checked(STATUS_UP_TO_DATE)

    async def async_close(self) -> None:
        """Déchargement de l'entrée : écrit tout de suite ce qui reste, puis plus rien.

        Une sauvegarde différée encore en attente aboutirait sinon jusqu'à
        SAVE_DELAY secondes plus tard, et, si l'entrée vient d'être supprimée,
        après async_remove_entry : le fichier supprimé réapparaîtrait.
        async_save annule la sauvegarde différée avant d'écrire.
        """
        self._closed = True
        if self._dirty:
            self._dirty = False
            await self._store.async_save(self._as_dict())

    async def async_remove(self) -> None:
        """Supprime le fichier de stockage (suppression de l'entrée)."""
        await self._store.async_remove()


class SyncManager:
    """Sérialise les synchros d'une entrée sans perdre aucune demande.

    Sept chemins peuvent déclencher une synchro (démarrage, intervalle,
    service, deux boutons, changement d'options, réimport). L'ancienne version
    IGNORAIT une demande arrivée pendant un passage : si l'ID Bitmoji ou la
    qualité changeait à ce moment-là, le réimport était perdu et l'ancien
    avatar restait affiché indéfiniment. Les demandes sont désormais cumulées
    (force et refresh_all sont des « ou » logiques) et la boucle repasse sous
    le verrou tant qu'il en reste.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, state: SyncState
    ) -> None:
        """Initialise la file, vide."""
        self._hass = hass
        self._entry = entry
        self._state = state
        self._lock = asyncio.Lock()
        self._pending = False
        self._pending_force = False
        self._pending_refresh_all = False
        self._runner: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        """Vrai si un passage (synchro ou nettoyage) est en cours."""
        return self._lock.locked()

    @callback
    def async_request(
        self, *, force: bool = False, refresh_all: bool = False
    ) -> asyncio.Task[None]:
        """Enregistre une demande et rend la main immédiatement.

        La synchro tourne en tâche de fond rattachée à l'entrée : elle est
        annulée à l'unload et ne retarde pas le démarrage de Home Assistant.
        Retourne la tâche qui la traitera (utile aux tests).
        """
        self._pending = True
        self._pending_force = self._pending_force or force
        self._pending_refresh_all = self._pending_refresh_all or refresh_all
        if self._runner is None or self._runner.done():
            self._runner = self._entry.async_create_background_task(
                self._hass,
                self._async_drain(),
                f"{DOMAIN} synchronisation {self._entry.entry_id}",
            )
        return self._runner

    async def _async_drain(self) -> None:
        async with self._lock:
            while self._pending:
                force = self._pending_force
                # Un réimport complet qui a échoué reste dû, même après un
                # redémarrage : sinon le différentiel sauterait les fichiers
                # (mêmes noms) et l'ancien contenu resterait en place.
                refresh_all = (
                    self._pending_refresh_all or self._state.refresh_all_pending
                )
                self._pending = self._pending_force = self._pending_refresh_all = False
                if refresh_all:
                    self._state.async_set_refresh_all_pending(pending=True)
                try:
                    ok = await catalog.async_run_sync(
                        self._hass,
                        self._entry,
                        self._state,
                        force=force,
                        refresh_all=refresh_all,
                    )
                except Exception:
                    # Garde de dernier recours : une erreur imprévue dans un
                    # passage ne doit ni tuer la file ni laisser le statut figé.
                    _LOGGER.exception(
                        "Erreur inattendue pendant la synchronisation Avatar Explorer"
                    )
                    self._state.async_mark_checked(
                        STATUS_ERROR,
                        "Erreur inattendue, voir le journal de Home Assistant",
                    )
                    continue
                # Un passage complet mené à terme, même partiel, a déjà levé le
                # drapeau (SyncState.async_finish_full_refresh). Ne reste dû
                # que celui qui s'est arrêté avant les téléchargements
                # (catalogue ou API export injoignables).
                if refresh_all and ok:
                    self._state.async_set_refresh_all_pending(pending=False)

    async def async_delete_orphans(self) -> tuple[int, int, int]:
        """Nettoyage des orphelins, sous le même verrou que les synchros.

        Sans ce verrou, un nettoyage pendant une synchro pourrait supprimer un
        fichier que la synchro vient d'écrire, ou se fier à une liste périmée.
        """
        async with self._lock:
            return await catalog.async_delete_orphans(
                self._hass, self._entry, self._state
            )


@dataclass
class AvatarExplorerRuntime:
    """Données d'exécution attachées à l'entrée (entry.runtime_data)."""

    state: SyncState
    sync: SyncManager
    # Valeurs de configuration qui pilotent la synchro, telles qu'au dernier
    # passage du listener d'options : sert à détecter ce qui a changé.
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    unsub_interval: CALLBACK_TYPE | None = None

    @callback
    def async_cancel_interval(self) -> None:
        """Annule le timer périodique en cours, s'il y en a un."""
        if self.unsub_interval is not None:
            self.unsub_interval()
            self.unsub_interval = None


type AvatarExplorerConfigEntry = ConfigEntry[AvatarExplorerRuntime]

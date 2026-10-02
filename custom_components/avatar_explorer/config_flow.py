"""Flux de configuration et d'options d'Avatar Explorer.

Les validations reprennent celles de l'API web (functions/api/export.js) : une
valeur que l'API refuserait en HTTP 400 est refusée dès le formulaire, au lieu
de produire une synchro en erreur plus tard. Elles ne s'appliquent qu'aux
saisies : une entrée existante n'est jamais revalidée.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .catalog import normalize_dir
from .const import (
    BITMOJI_ID_PATTERN,
    CONF_BITMOJI_ID,
    CONF_DIR,
    CONF_DUO_PAIR,
    CONF_HA_PERSON,
    CONF_LABEL,
    CONF_LANG,
    CONF_SCALE,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_USER_FOLDER,
    CONF_USERS,
    DEFAULT_DIR,
    DEFAULT_LANG,
    DEFAULT_SCALE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    FOLDER_PATTERN,
    LANG_OPTIONS,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_UPDATE_INTERVAL_HOURS,
    RESERVED_FOLDER,
    SCALE_VALUES,
    SUPPORTED_LANGS,
)

_BITMOJI_RE = re.compile(BITMOJI_ID_PATTERN)
_FOLDER_RE = re.compile(FOLDER_PATTERN)

CONF_DUO_USER1 = "duo_user1"
CONF_DUO_USER2 = "duo_user2"


def _scale_selector() -> selector.SelectSelector:
    """Liste Web / HD / Ultra pour le facteur de résolution (libellés traduits)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=SCALE_VALUES,
            mode=selector.SelectSelectorMode.LIST,
            translation_key=CONF_SCALE,
        )
    )


def _current_scale(source: dict[str, Any]) -> str:
    """Valeur courante en chaîne.

    Le sélecteur compare aux valeurs des options, or les configurations
    existantes ont pu stocker un entier.
    """
    return str(source.get(CONF_SCALE, DEFAULT_SCALE))


def _lang_selector() -> selector.SelectSelector:
    """Langue du catalogue.

    Elle ne change pas que l'affichage : les noms de fichiers dérivent du
    titre traduit, donc en changer télécharge un jeu d'images entièrement
    différent.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=LANG_OPTIONS,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _interval_selector() -> selector.NumberSelector:
    """Intervalle de vérification, borné (0 donnait une boucle serrée)."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=MIN_UPDATE_INTERVAL_HOURS,
            max=MAX_UPDATE_INTERVAL_HOURS,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="h",
        )
    )


def _suggested_lang(hass: HomeAssistant) -> str:
    """Langue de Home Assistant si le catalogue l'a, sinon le français."""
    lang = (hass.config.language or "").lower()
    if lang in SUPPORTED_LANGS:
        return lang
    primary = lang.split("-", 1)[0]
    if primary in SUPPORTED_LANGS:
        return primary
    return DEFAULT_LANG


def _options_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Options normalisées : intervalle entier, qualité en chaîne."""
    return {
        CONF_UPDATE_INTERVAL_HOURS: int(user_input[CONF_UPDATE_INTERVAL_HOURS]),
        CONF_SCALE: str(user_input[CONF_SCALE]),
        CONF_LANG: user_input[CONF_LANG],
    }


def validate_folder(folder: str, existing: list[str]) -> str | None:
    """Clé d'erreur pour un nom de dossier utilisateur, ou None s'il est valide.

    La comparaison ignore la casse : les entity_id sont en minuscules, deux
    dossiers « Kenny » et « kenny » produiraient les mêmes entités.
    """
    if not _FOLDER_RE.fullmatch(folder):
        return "invalid_folder"
    if folder.lower() == RESERVED_FOLDER.lower():
        return "reserved_folder"
    if folder.lower() in {f.lower() for f in existing}:
        return "duplicate_folder"
    return None


class AvatarExplorerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gestion du flux de configuration pour Avatar Explorer."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise un flux vide."""
        self._config_data: dict[str, Any] = {}
        self._users: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 1 : Définition du dossier racine des images."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_dir = normalize_dir(user_input[CONF_DIR])
            if base_dir is None:
                errors[CONF_DIR] = "invalid_dir"
            else:
                self._config_data[CONF_DIR] = base_dir
                return await self.async_step_add_user()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DIR, default=DEFAULT_DIR): str,
                }
            ),
            errors=errors,
        )

    async def async_step_add_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape 2 : Ajout d'un utilisateur (Dossier + Bitmoji ID)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            folder = user_input[CONF_USER_FOLDER].strip()
            bitmoji_id = user_input[CONF_BITMOJI_ID].strip()
            folder_error = validate_folder(
                folder, [u[CONF_USER_FOLDER] for u in self._users]
            )
            if folder_error:
                errors[CONF_USER_FOLDER] = folder_error
            if not _BITMOJI_RE.fullmatch(bitmoji_id):
                errors[CONF_BITMOJI_ID] = "invalid_bitmoji_id"
            if not errors:
                user: dict[str, Any] = {
                    CONF_USER_FOLDER: folder,
                    CONF_BITMOJI_ID: bitmoji_id,
                    # On utilise l'ID du dossier comme label par défaut pour HA
                    CONF_LABEL: folder,
                }
                if user_input.get(CONF_HA_PERSON):
                    user[CONF_HA_PERSON] = user_input[CONF_HA_PERSON]
                self._users.append(user)
                return await self.async_step_choice()

        return self.async_show_form(
            step_id="add_user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_FOLDER): str,  # Nom du dossier (ex: Kenny)
                    vol.Required(
                        CONF_BITMOJI_ID
                    ): str,  # ID Bitmoji (ex: 123456789012_1-s5)
                    vol.Optional(CONF_HA_PERSON): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="person")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_choice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Menu pour ajouter un autre utilisateur ou terminer."""
        return self.async_show_menu(
            step_id="choice", menu_options=["add_user", "finish"]
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape intermédiaire : désignation de la paire Duo si besoin."""
        if len(self._users) >= 2:
            return await self.async_step_duo_pair()
        return await self.async_step_settings()

    async def async_step_duo_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Désignation des deux utilisateurs formant le mode Duo."""
        folder_ids = [u[CONF_USER_FOLDER] for u in self._users]
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_DUO_USER1] == user_input[CONF_DUO_USER2]:
                errors[CONF_DUO_USER2] = "duo_same_user"
            else:
                self._config_data[CONF_DUO_PAIR] = [
                    user_input[CONF_DUO_USER1],
                    user_input[CONF_DUO_USER2],
                ]
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="duo_pair",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DUO_USER1): vol.In(folder_ids),
                    vol.Required(CONF_DUO_USER2): vol.In(folder_ids),
                }
            ),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Réglages de synchronisation (intervalle de vérification, qualité, langue)."""
        if user_input is not None:
            self._config_data[CONF_USERS] = self._users
            return self.async_create_entry(
                title=f"Avatar Explorer ({self._config_data[CONF_DIR]})",
                data=self._config_data,
                options=_options_from_input(user_input),
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL_HOURS,
                        default=DEFAULT_UPDATE_INTERVAL_HOURS,
                    ): _interval_selector(),
                    vol.Required(
                        CONF_SCALE, default=str(DEFAULT_SCALE)
                    ): _scale_selector(),
                    vol.Required(
                        CONF_LANG, default=_suggested_lang(self.hass)
                    ): _lang_selector(),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AvatarExplorerOptionsFlow:
        """Flux d'options."""
        return AvatarExplorerOptionsFlow()


class AvatarExplorerOptionsFlow(OptionsFlow):
    """Modifie l'intervalle, la qualité, la langue et les IDs Bitmoji après coup."""

    @staticmethod
    def _field_for(user: dict[str, Any]) -> str:
        """Nom du champ de formulaire portant l'ID Bitmoji d'un utilisateur."""
        return f"bitmoji_{user[CONF_USER_FOLDER]}"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Formulaire unique d'options."""
        entry = self.config_entry
        users: list[dict[str, Any]] = entry.data.get(CONF_USERS, [])
        errors: dict[str, str] = {}

        if user_input is not None:
            ids_changed = False
            new_users = []
            for user in users:
                field = self._field_for(user)
                new_id = (user_input.get(field) or "").strip()
                if new_id and not _BITMOJI_RE.fullmatch(new_id):
                    errors[field] = "invalid_bitmoji_id"
                if new_id != (user.get(CONF_BITMOJI_ID) or ""):
                    ids_changed = True
                new_users.append({**user, CONF_BITMOJI_ID: new_id})

            if not errors:
                new_options = {**entry.options, **_options_from_input(user_input)}
                if ids_changed:
                    # Les IDs vivent dans data (pas options) : c'est la
                    # structure que lit catalog pour construire les appels
                    # export. Données ET options sont écrites en UNE fois :
                    # deux écritures successives déclenchaient le listener
                    # avec les anciennes options (langue, qualité).
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_USERS: new_users},
                        options=new_options,
                    )
                # Le listener de l'entrée compare à l'état précédent et
                # déclenche lui-même le réimport ou la resynchro nécessaires.
                return self.async_create_entry(data=new_options)

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_UPDATE_INTERVAL_HOURS,
                default=entry.options.get(
                    CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
                ),
            ): _interval_selector(),
            vol.Required(
                CONF_SCALE,
                default=_current_scale(entry.options),
            ): _scale_selector(),
            vol.Required(
                CONF_LANG,
                default=entry.options.get(CONF_LANG, DEFAULT_LANG),
            ): _lang_selector(),
        }
        # Un champ par utilisateur configuré, pré-rempli avec l'ID actuel.
        for user in users:
            schema[
                vol.Optional(
                    self._field_for(user),
                    description={"suggested_value": user.get(CONF_BITMOJI_ID, "")},
                    default="",
                )
            ] = str

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "users": ", ".join(u[CONF_USER_FOLDER] for u in users) or "-",
            },
        )

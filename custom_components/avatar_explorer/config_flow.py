import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from .const import DOMAIN, DEFAULT_DIR

class AvatarExplorerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestion du flux de configuration pour Avatar Explorer."""
    VERSION = 1

    def __init__(self):
        self._config_data = {}
        self._users = []

    async def async_step_user(self, user_input=None):
        """Étape 1 : Définition du dossier racine des images."""
        if user_input is not None:
            self._config_data.update(user_input)
            return await self.async_step_add_user()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("dir", default=DEFAULT_DIR): str,
            })
        )

    async def async_step_add_user(self, user_input=None):
        """Étape 2 : Ajout d'un utilisateur (Dossier uniquement)."""
        if user_input is not None:
            # On utilise l'ID du dossier comme label par défaut pour HA
            user_input["label"] = user_input["user_id_folder"]
            self._users.append(user_input)
            return await self.async_step_choice()

        return self.async_show_form(
            step_id="add_user",
            data_schema=vol.Schema({
                vol.Required("user_id_folder"): str,  # Nom du dossier (ex: Kenny)
                vol.Optional("ha_person"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person")
                ),
            })
        )

    async def async_step_choice(self, user_input=None):
        """Menu pour ajouter un autre utilisateur ou terminer."""
        return self.async_show_menu(
            step_id="choice", 
            menu_options=["add_user", "finish"]
        )

    async def async_step_finish(self, user_input=None):
        """Création de l'entrée avec toutes les données collectées."""
        self._config_data["users"] = self._users
        
        # Le titre de l'intégration dans la page Services sera le chemin du dossier
        return self.async_create_entry(
            title=f"Avatar Explorer ({self._config_data['dir']})", 
            data=self._config_data
        )
"""Constantes de l'intégration Avatar Explorer."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "avatar_explorer"
DEFAULT_DIR: Final = "images/avatar"

CONF_DIR: Final = "dir"
CONF_USERS: Final = "users"
CONF_DUO_PAIR: Final = "duo_pair"
CONF_USER_FOLDER: Final = "user_id_folder"
CONF_BITMOJI_ID: Final = "bitmoji_id"
CONF_HA_PERSON: Final = "ha_person"
CONF_LABEL: Final = "label"
CONF_SCALE: Final = "scale"
CONF_UPDATE_INTERVAL_HOURS: Final = "update_interval_hours"
CONF_LANG: Final = "lang"

DEFAULT_SCALE: Final = 1
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 24
# Bornes de l'intervalle de vérification. Une valeur nulle produirait une
# boucle serrée ; au-delà d'une semaine, le catalogue (mis à jour chaque lundi)
# aurait le temps de changer plusieurs fois sans qu'on s'en aperçoive.
MIN_UPDATE_INTERVAL_HOURS: Final = 1
MAX_UPDATE_INTERVAL_HOURS: Final = 168

# Langue appliquée aux entrées qui n'en ont pas (créées avant l'option). Elle
# ne doit PAS suivre la langue de Home Assistant : ces installations ont des
# fichiers nommés en français, en changer retéléchargerait tout le catalogue.
# La langue de HA ne sert que de valeur proposée à la création d'une entrée.
DEFAULT_LANG: Final = "fr"

# Doit rester aligné sur SUPPORTED_LANGS de functions/api/export.js : l'API
# rejette toute autre valeur en HTTP 400.
#
# ATTENTION : la langue ne change pas que l'affichage. Les noms de fichiers
# sont dérivés du titre traduit de chaque pose, donc en changer produit un jeu
# d'images entièrement différent (~20 % de noms communs seulement entre fr et
# en), et un nombre d'images différent (1261 en fr, 1975 en en).
#
# Les libellés sont des endonymes : ils ne se traduisent pas.
LANG_OPTIONS: Final = [
    {"value": "fr", "label": "Français"},
    {"value": "fr-ca", "label": "Français (Canada)"},
    {"value": "en", "label": "English"},
    {"value": "es", "label": "Español"},
    {"value": "de", "label": "Deutsch"},
    {"value": "it", "label": "Italiano"},
    {"value": "pt", "label": "Português"},
    {"value": "pl", "label": "Polski"},
    {"value": "ro", "label": "Română"},
    {"value": "tr", "label": "Türkçe"},
    {"value": "el", "label": "Ελληνικά"},
    {"value": "ja", "label": "日本語"},
    {"value": "ko", "label": "한국어"},
    {"value": "zh", "label": "中文"},
]
SUPPORTED_LANGS: Final = frozenset(opt["value"] for opt in LANG_OPTIONS)

# Le paramètre scale de l'API Bitmoji est un facteur de résolution (1, 2 ou 4).
# Les libellés parlants (Web / HD / Ultra) sont dans les traductions, sous
# selector.scale : personne ne sait ce que « 4 » veut dire.
SCALE_VALUES: Final = ["1", "2", "4"]

# Le site s'appelait « Pose Explorer » (pose-explorer.pages.dev) jusqu'en
# juillet 2026 ; l'ancien domaine ne résout plus, il n'y a donc pas de repli
# possible sur celui-ci.
CATALOG_HOST: Final = "avatar-explorer.pages.dev"
CATALOG_BASE_URL: Final = f"https://{CATALOG_HOST}"
AIDE_JSON_URL: Final = f"{CATALOG_BASE_URL}/aide.json"
EXPORT_API_URL: Final = f"{CATALOG_BASE_URL}/api/export"

# Seuls hôtes que la synchro a le droit de contacter, en HTTPS uniquement. Le
# script d'export est fourni par le serveur : sans cette liste blanche, une
# compromission en amont pourrait faire appeler n'importe quelle adresse du
# réseau local (SSRF).
BITMOJI_CDN_HOST: Final = "sdk.bitmoji.com"
ALLOWED_DOWNLOAD_HOSTS: Final = frozenset({BITMOJI_CDN_HOST, CATALOG_HOST})

# Émis à chaque changement d'état de la synchro, pour que les entités
# d'affichage (date, état) se rafraîchissent sans interroger le réseau. Le
# signal est suffixé par l'entry_id (voir sync_signal).
SIGNAL_SYNC_UPDATED: Final = f"{DOMAIN}_sync_updated"

# Identifiants du device qui regroupe les entités de synchronisation.
SYSTEM_DEVICE_ID: Final = "system"
SYSTEM_DEVICE_NAME: Final = "Avatar Explorer"
MANUFACTURER: Final = "Avatar Explorer"

# Les IDs Bitmoji finissent dans l'URL de l'API, qui refuse tout ce qui sort
# de cette whitelist (cf. SAFE_PATTERN dans functions/api/export.js).
BITMOJI_ID_PATTERN: Final = r"^[a-zA-Z0-9_-]+$"
# Nom de dossier utilisateur : même alphabet que name1/name2 côté API, borné
# pour rester lisible dans les entity_id.
FOLDER_PATTERN: Final = r"^[A-Za-z0-9_-]{1,32}$"
# Le dossier du mode Duo porte ce nom en dur côté API et côté carte.
RESERVED_FOLDER: Final = "Duo"
# Même règle que DIR_SAFE_PATTERN de functions/api/export.js (après retrait des
# « / » de début et de fin) : ni « . » (donc pas de ../), ni segment vide.
DIR_PATTERN: Final = r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$"

# Chemin d'une pose servie par Home Assistant :
# /local/<dossier du catalogue>/<utilisateur ou Duo>/<fichier>.png.
# Même alphabet que DIR_PATTERN, FOLDER_PATTERN et les noms produits par l'API
# (SAFE_FILENAME_RE de catalog.py : tags [a-z0-9 _], suffixes _2, dossier Duo).
# Aucun « . » hors de l'extension, donc ni « .. », ni « %2e », ni « ? » ou « # ».
#
# Une seule regex pour les actions, l'entité text (_attr_pattern, ce qui couvre
# text.set_value appelé directement), la restauration et entity_picture.
# Les « - » sont échappés dans les classes : la regex est aussi compilée par
# le navigateur (attribut HTML pattern, drapeau « v »), qui refuse un « - » nu.
IMAGE_PATH_PATTERN: Final = (
    r"^/local/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*"
    r"/[A-Za-z0-9_\-]+/[A-Za-z0-9_\- ]+\.png$"
)

# Valeurs possibles de l'attribut « status » de la synchro.
STATUS_UNKNOWN: Final = "inconnu"
STATUS_UP_TO_DATE: Final = "a_jour"
STATUS_PARTIAL: Final = "partielle"
STATUS_ERROR: Final = "erreur"
SYNC_STATUSES: Final = [STATUS_UNKNOWN, STATUS_UP_TO_DATE, STATUS_PARTIAL, STATUS_ERROR]

# Budget global de la phase de téléchargement d'un passage. Le premier import
# complet (~3750 fichiers, 6 en parallèle) prend quelques minutes ; au-delà de
# ce budget, le passage est abandonné et marqué partiel, le reste sera repris
# au passage suivant. Sans borne, un serveur lent ou des Retry-After en série
# pourraient garder le verrou de synchro pendant des heures.
DOWNLOAD_PHASE_TIMEOUT: Final = 30 * 60
# Disjoncteur : nombre de fichiers consécutifs en échec sur une réponse 429 ou
# 5xx (après les nouvelles tentatives) au-delà duquel le passage est abandonné.
# Insister ne ferait qu'aggraver la limitation de débit côté serveur.
MAX_CONSECUTIVE_SERVER_ERRORS: Final = 20
# Chemins en échec lors d'un réimport complet, retentés aux passages suivants
# (voir SyncState.retry_paths). Au-delà, la liste n'est plus tenue et le
# réimport complet reste dû : avec autant d'échecs, il n'a pas vraiment eu lieu.
MAX_RETRY_PATHS: Final = 2000


def sync_signal(entry_id: str) -> str:
    """Nom du signal dispatcher propre à une entrée."""
    return f"{SIGNAL_SYNC_UPDATED}_{entry_id}"

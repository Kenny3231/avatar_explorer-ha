DOMAIN = "avatar_explorer"
DEFAULT_DIR = "images/avatar"

CONF_BITMOJI_ID = "bitmoji_id"
CONF_DUO_PAIR = "duo_pair"
CONF_SCALE = "scale"
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
CONF_LANG = "lang"

DEFAULT_SCALE = 1
DEFAULT_UPDATE_INTERVAL_HOURS = 24
DEFAULT_LANG = "fr"

# Doit rester aligné sur SUPPORTED_LANGS de functions/api/export.js : l'API
# rejette toute autre valeur en HTTP 400.
#
# ATTENTION : la langue ne change pas que l'affichage. Les noms de fichiers
# sont dérivés du titre traduit de chaque pose, donc en changer produit un jeu
# d'images entièrement différent (~20 % de noms communs seulement entre fr et
# en), et un nombre d'images différent (1261 en fr, 1975 en en).
LANG_OPTIONS = [
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

# Le paramètre scale de l'API Bitmoji est un facteur de résolution (1, 2 ou 4).
# On l'expose sous des noms parlants : personne ne sait ce que « 4 » veut dire.
SCALE_OPTIONS = [
    {"value": "1", "label": "Web — le plus léger (recommandé)"},
    {"value": "2", "label": "HD — deux fois plus détaillé"},
    {"value": "4", "label": "Ultra — quatre fois plus détaillé, fichiers lourds"},
]

# Le site s'appelait « Pose Explorer » (pose-explorer.pages.dev) jusqu'en
# juillet 2026 ; l'ancien domaine ne résout plus, il n'y a donc pas de repli
# possible sur celui-ci.
CATALOG_BASE_URL = "https://avatar-explorer.pages.dev"
AIDE_JSON_URL = f"{CATALOG_BASE_URL}/aide.json"
EXPORT_API_URL = f"{CATALOG_BASE_URL}/api/export"

# Émis à chaque changement d'état de la synchro, pour que les entités
# d'affichage (date, état) se rafraîchissent sans interroger le réseau.
SIGNAL_SYNC_UPDATED = f"{DOMAIN}_sync_updated"

# Identifiants du device qui regroupe les entités de synchronisation.
SYSTEM_DEVICE_ID = "system"

# Les IDs Bitmoji finissent dans l'URL de l'API, qui refuse tout ce qui sort
# de cette whitelist (cf. SAFE_PATTERN dans functions/api/export.js).
BITMOJI_ID_PATTERN = r"^[a-zA-Z0-9_-]+$"

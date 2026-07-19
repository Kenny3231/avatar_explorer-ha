DOMAIN = "avatar_explorer"
DEFAULT_DIR = "images/avatar"

CONF_BITMOJI_ID = "bitmoji_id"
CONF_DUO_PAIR = "duo_pair"
CONF_SCALE = "scale"
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"

DEFAULT_SCALE = 1
DEFAULT_UPDATE_INTERVAL_HOURS = 24

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

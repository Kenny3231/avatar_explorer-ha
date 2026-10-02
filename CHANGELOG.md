# Changelog

Toutes les modifications notables de ce projet sont consignées ici.
Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet respecte le [versionnage sémantique](https://semver.org/lang/fr/).

## [1.2.0] - 2026-10-02

### Sécurité

- Les chemins de fichiers issus du catalogue sont validés : tout nom contenant `..`, un segment vide ou sortant du dossier configuré est refusé, de même qu'un dossier remplacé par un lien symbolique.
- Les téléchargements n'acceptent que les URL en liste blanche (hôte d'Avatar Explorer) : une redirection vers un autre hôte est refusée. Le type de contenu est vérifié et la taille lue est bornée.
- Le nettoyage des orphelins refuse de toucher un dossier situé hors de la racine des images, et épargne les avatars encore utilisés.
- Seuls les dossiers des utilisateurs configurés et `Duo` sont écrits, recensés ou nettoyés : un dossier frère sous le dossier des images (`backgrounds/`...) n'est jamais touché, même par un réimport complet.
- Un chemin d'image strict (`/local/<dossier>/<utilisateur>/<pose>.png`, alphabet de l'API) est imposé aux actions, à `text.set_value` (motif de l'entité), à la restauration de l'état et à `entity_picture`.
- Les actions ne ciblent plus l'entité `text` d'une autre intégration ; seules les ressources Lovelace d'URL relative sont reconnues comme la carte.
- Les en-têtes `Retry-After`, `Content-Length` et `Location` malformés ne provoquent plus d'exception non gérée ; les téléchargements tournent dans un `asyncio.TaskGroup`, si bien qu'aucune écriture n'a lieu après la fin d'un passage.
- Durée bornée : 30 minutes au plus de téléchargement par passage, et arrêt après 20 réponses 429/5xx consécutives (statut `partielle`).
- Les journaux ne contiennent plus les ID Bitmoji ; le contenu renvoyé par le serveur y est cité tel quel (`%r`).
- Les actions `set_avatar` et `send_emoji` n'acceptent plus que des chemins `/local/...` vers une image PNG ; les noms d'utilisateur, d'ID Bitmoji et de dossier sont validés dans l'assistant de configuration.

### Corrigé

- Le minuteur de vérification périodique est réparé : il est recréé à chaque changement d'intervalle, annulé au déchargement, et l'intervalle est borné entre 1 et 168 heures.
- Les demandes de synchronisation simultanées (minuteur, boutons, action) passent par une file unique : aucune demande n'est perdue ni exécutée en double, et un réimport complet qui échoue avant les téléchargements reste en attente.
- Un réimport complet mené à terme mais partiel n'est plus relancé en entier à chaque passage : les fichiers en échec sont mémorisés (liste bornée) et seuls eux sont repris.
- L'état de synchronisation d'une entrée supprimée n'est plus recréé par une sauvegarde différée.
- Les traductions et `services.yaml` ne contiennent plus de chevrons (`<user>`), refusés par hassfest.
- Les erreurs réseau transitoires sont réessayées avec délai croissant, en respectant `Retry-After` (plafonné) sur les réponses 429 ; une réponse 404 n'est pas réessayée.
- Les actions sont validées par un schéma et produisent des erreurs traduites (utilisateur inconnu, service de notification introuvable, aucune entrée chargée) avant toute modification.
- La synchronisation continue de fonctionner si le capteur de synchronisation est désactivé : son état est désormais porté par l'entrée (`runtime_data`) et migré depuis l'ancien état restauré.
- Les entités regroupent leurs appareils, et le capteur d'un utilisateur suit sa personne liée sans interrogation périodique.
- Compatibilité conservée avec les installations existantes : `entity_id`, `unique_id`, options et entrées créées avant le mode Duo ou le choix de la langue (traitées en français).

### Modifié

- La carte est servie sur sa propre route `/avatar_explorer/avatar-card.js?v=<version>` (au lieu de `/local/avatar-card.js`) : elle ne masque plus le dossier `www/` de l'utilisateur et le navigateur la recharge à chaque version. Une ancienne ressource `/local/avatar-card.js` est migrée sur place, et les doublons sont supprimés. En mode YAML, la ressource est à ajouter à la main : une réparation indique la nouvelle URL tant que `configuration.yaml` n'est pas à jour (voir le README).
- Le code est réorganisé en modules `runtime.py`, `services.py`, `card.py` et `entity.py`.
- Version minimale de Home Assistant : 2026.1.0 (API récentes utilisées : `AddConfigEntryEntitiesCallback`, `ServiceCall.hass`...). `hacs.json` ne contient plus que les clés prises en charge par HACS 2.x.
- README : la section Confidentialité mentionne les deux hôtes contactés (`avatar-explorer.pages.dev` et `sdk.bitmoji.com`).
- README réécrit en français, avec une version anglaise (`README.en.md`) et des sections Confidentialité et Dépannage.

### Ajouté

- Carte : accessibilité (étiquettes pour les lecteurs d'écran, lightbox modale, fermeture à `Échap`, retour du focus), message d'erreur lisible quand la liste des poses est indisponible, interface en français et en anglais.
- Traductions anglaises (`strings.json`, `translations/en.json`) en plus du français.
- Langue du catalogue configurable, qualité des images (Web, HD, Ultra) et paire Duo.
- Bouton « Nettoyer les orphelins » (désactivé par défaut) et capteurs de diagnostic de synchronisation.
- Suite de tests (`pytest-homeassistant-custom-component`) couvrant les chemins et URL, la récupération réseau, l'assistant de configuration, le cycle de vie, les actions et la migration des ressources.
- CI GitHub Actions (hassfest, HACS sans le contrôle `brands`, ruff, tests sous Python 3.14) avec actions et dépendances de test épinglées, et Dependabot ; fichiers `LICENSE` (MIT) et `.gitignore`.
- Réparation « ressource Lovelace à mettre à jour » en mode YAML.

## [1.1.0]

Version précédente, publiée avant la mise en place de ce journal.

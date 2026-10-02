# Avatar Explorer pour Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Personnalis%C3%A9-orange.svg)](https://hacs.xyz)
[![Version](https://img.shields.io/github/v/release/Kenny3231/avatar_explorer-ha)](https://github.com/Kenny3231/avatar_explorer-ha/releases)
[![Validate](https://github.com/Kenny3231/avatar_explorer-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/Kenny3231/avatar_explorer-ha/actions/workflows/validate.yml)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

*[English version](README.en.md)*

Intégration personnalisée pour Home Assistant qui télécharge vos poses Bitmoji depuis [Avatar Explorer](https://avatar-explorer.pages.dev), les tient à jour toute seule, et fournit une carte Lovelace pour changer votre avatar en un clic ou envoyer une pose à un autre membre du foyer, avec notification mobile.

- Site : <https://avatar-explorer.pages.dev>
- Dépôt du site : <https://github.com/Kenny3231/Avatar_Explorer>

## Fonctionnalités

- **Synchronisation automatique et incrémentale** : l'intégration compare le catalogue distant à vos fichiers et ne télécharge que les poses manquantes ou modifiées. Intervalle de vérification réglable de 1 à 168 heures (24 h par défaut).
- **Langue du catalogue** : français, français (Canada), anglais, espagnol, allemand, italien, portugais, polonais, roumain, turc, grec, japonais, coréen, chinois. La langue détermine les titres, les mots-clés et les **noms de fichiers** des poses ; elle change aussi leur nombre (1261 en français, 1975 en anglais). Changer de langue télécharge donc un jeu d'images entièrement nouveau.
- **Qualité des images** : Web (la plus légère, recommandée), HD (deux fois plus détaillée) ou Ultra (quatre fois, fichiers lourds).
- **Mode Duo** : poses à deux personnages pour la paire d'utilisateurs de votre choix, dans un dossier `Duo`.
- **Boutons** : synchroniser maintenant, réimport complet, nettoyer les orphelins.
- **Capteurs** : un capteur par utilisateur et trois capteurs de diagnostic pour suivre la synchronisation.
- **Carte Lovelace** `custom:avatar-card` : recherche, filtre par catégorie, aperçu agrandi, utilisable au clavier et avec un lecteur d'écran, interface en français et en anglais.
- **Notifications** : envoi de la pose au téléphone du destinataire via un service `notify.*`.

## Installation

### Via HACS (recommandé)

1. Dans HACS, menu **⋮** > **Dépôts personnalisés**.
2. Ajoutez `https://github.com/Kenny3231/avatar_explorer-ha` avec la catégorie **Intégration**.
3. Installez **Avatar Explorer**, puis redémarrez Home Assistant.

### Manuelle

1. Copiez le dossier `custom_components/avatar_explorer/` dans `config/custom_components/`.
2. Redémarrez Home Assistant.

Home Assistant **2026.1.0** ou plus récent est requis.

## Configuration

Tout se fait dans l'interface : **Paramètres** > **Appareils et services** > **Ajouter une intégration** > **Avatar Explorer**.

1. **Dossier des images**, relatif au dossier `www/` de Home Assistant (par défaut `images/avatar`). Lettres, chiffres, `_`, `-` et `/` uniquement.
2. **Utilisateurs** : pour chacun, un nom de dossier (lettres, chiffres, `_` et `-`, 32 caractères au plus ; `Duo` est réservé), son **ID Bitmoji** et, facultativement, la personne Home Assistant liée.
3. **Paire Duo** : les deux utilisateurs du mode Duo.
4. **Synchronisation** : intervalle de vérification, qualité et langue du catalogue.

Ces réglages se modifient ensuite via **Configurer** sur l'intégration. Une seule instance de l'intégration est possible.

> **Trouver votre ID Bitmoji.** Le site Avatar Explorer télécharge les images mais ne l'affiche pas. Connectez-vous sur bitmoji.com et repérez-le avec les outils de développement du navigateur (F12). Format attendu : lettres, chiffres, tirets et tirets bas, par exemple `XXXXXXXXXX_X-s5`.

Changer un ID Bitmoji ou la qualité déclenche un réimport complet. Changer de langue télécharge un nouveau jeu d'images ; les anciennes restent sur le disque et les avatars affichés devront être choisis à nouveau.

Les images sont rangées dans `config/www/<dossier>/<utilisateur>/`, avec un fichier `metadata_<utilisateur>.json` par utilisateur (et un dossier `Duo`).

## Carte Lovelace

La carte est **enregistrée automatiquement** : l'intégration la sert sur `/avatar_explorer/avatar-card.js` (avec la version en paramètre, pour que le navigateur recharge la carte à chaque mise à jour) et l'ajoute aux ressources du tableau de bord. Une ancienne ressource `/local/avatar-card.js` est migrée sur place, sans retoucher vos tableaux de bord.

**Tableaux de bord en mode YAML** : Home Assistant ne permet pas d'ajouter la ressource automatiquement. Une réparation (**Paramètres** > **Système** > **Réparations**) l'indique, avec l'URL exacte à utiliser, tant que `configuration.yaml` ne contient pas l'URL de la version installée. Ajoutez-la à la main, en remplacement de `/local/avatar-card.js` s'il y figure, puis redémarrez :

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /avatar_explorer/avatar-card.js?v=1.2.0
      type: module
```

Exemple de carte :

```yaml
type: custom:avatar-card
dir: images/avatar          # dossier des images, comme dans l'intégration
show_duo: true              # affiche l'entrée Duo dans la liste
duo_label: "👩‍❤️‍👨 Nous"      # libellé du mode Duo
users:
  - user_id_folder: Kenny   # nom de dossier configuré dans l'intégration
    label: "🧔 Kenny"
    notify_service: mobile_app_iphone_de_kenny   # service notify à appeler à la réception
    is_default: true        # utilisateur sélectionné à l'ouverture
  - user_id_folder: Lea
    label: "👩 Lea"
    notify_service: mobile_app_telephone_de_lea
```

L'éditeur visuel de la carte propose les utilisateurs déjà créés par l'intégration, le choix de l'utilisateur par défaut et du service de notification. Une pose envoyée à un autre utilisateur déclenche une notification si `notify_service` est renseigné.

## Actions (services)

| Action | Champs | Effet |
|---|---|---|
| `avatar_explorer.set_avatar` | `user_id` (obligatoire), `image_path` (obligatoire) | Définit l'avatar d'un utilisateur (entité `text.avatar_<utilisateur>`). |
| `avatar_explorer.send_emoji` | `to_user` (obligatoire), `image_path` (obligatoire), `from_label`, `notify_service` | Envoie une pose à un utilisateur (entité `text.emoji_recu_<utilisateur>`) et, si `notify_service` est renseigné, une notification avec l'image. |
| `avatar_explorer.force_reimport` | aucun | Force la vérification et le téléchargement des poses manquantes, même si le catalogue est à jour. |

- `user_id` et `to_user` : nom de dossier de l'utilisateur, par exemple `Kenny`. Un utilisateur inconnu produit une erreur.
- `image_path` : chemin `/local/...` d'une image PNG du catalogue. Les autres chemins ou URL sont refusés.
- `notify_service` : service `notify`, avec ou sans le préfixe `notify.` (par exemple `mobile_app_telephone_de_lea`). Un service introuvable produit une erreur avant toute modification.
- `from_label` : libellé de l'expéditeur transmis par la carte, à titre informatif.

```yaml
action: avatar_explorer.send_emoji
data:
  to_user: Lea
  image_path: /local/images/avatar/Duo/Kenny__Lea__calin.png
  notify_service: mobile_app_telephone_de_lea
```

## Entités créées

| Entité | Rôle |
|---|---|
| `sensor.<utilisateur>_dynamique` | État de la personne Home Assistant liée ; l'image du capteur est l'avatar courant. |
| `text.avatar_<utilisateur>` | Chemin de l'avatar courant (écrit par `set_avatar`). |
| `text.emoji_recu_<utilisateur>` | Dernière pose reçue (écrit par `send_emoji`). |
| `sensor.avatar_explorer_sync` | Diagnostic : résumé de la dernière synchronisation. |
| `sensor.avatar_explorer_sync_etat` | Diagnostic : `a_jour`, `partielle`, `erreur` ou `inconnu`, avec les compteurs (téléchargées, déjà présentes, échecs, orphelines). |
| `sensor.avatar_explorer_sync_date` | Diagnostic : date de la dernière vérification. |
| `button.avatar_explorer_sync` | Synchroniser maintenant. |
| `button.avatar_explorer_reimport_complet` | Réécrit tous les fichiers. |
| `button.avatar_explorer_nettoyer_orphelins` | Supprime les images qui ne sont plus au catalogue (les avatars en cours d'utilisation sont épargnés). **Désactivé par défaut** : activez-le dans les paramètres de l'entité. |

## Confidentialité

- **Les images sont servies sans authentification.** Home Assistant publie le dossier `www/` sous `/local/` sans demander de connexion : toute personne pouvant joindre votre instance (n'importe qui si elle est exposée sur Internet) peut ouvrir ces URL si elle en connaît le nom. Ne placez rien de sensible dans ce dossier.
- **Les ID Bitmoji passent en paramètres de requête** vers l'API d'Avatar Explorer (`avatar-explorer.pages.dev`) à chaque synchronisation. Ils peuvent donc apparaître dans les journaux d'un serveur ou d'un proxy intermédiaire. Ils sont stockés dans la configuration de Home Assistant.
- L'intégration contacte deux hôtes, en HTTPS uniquement : `avatar-explorer.pages.dev` (horodatage du catalogue, liste des poses à télécharger, fichiers `metadata_*.json`) et `sdk.bitmoji.com` (les images elles-mêmes, dont l'URL contient votre ID Bitmoji). Toute autre adresse est refusée, redirections comprises.
- Les journaux de l'intégration ne contiennent jamais les ID Bitmoji : seuls le mode et les noms de dossier y figurent.

## Dépannage

Consultez les journaux :

```
ha core logs | grep avatar_explorer
```

Pour des traces détaillées, ajoutez dans `configuration.yaml` :

```yaml
logger:
  logs:
    custom_components.avatar_explorer: debug
```

- **La carte n'apparaît pas** : vérifiez que la ressource `/avatar_explorer/avatar-card.js` figure dans **Paramètres** > **Tableaux de bord** > **Ressources** (mode avancé du profil), puis videz le cache du navigateur.
- **Aucune image** : regardez `sensor.avatar_explorer_sync_etat` et son attribut `raison`, puis appuyez sur le bouton de synchronisation. Un statut `partielle` indique des échecs de téléchargement ponctuels ; la synchronisation suivante les reprend.
- **Serveur surchargé ou limite de requêtes** : l'intégration réessaie d'elle-même, en respectant le délai demandé par le serveur. Après 20 fichiers d'affilée refusés en 429 ou 5xx, ou 30 minutes de téléchargement, le passage s'arrête avec le statut `partielle` ; le passage suivant reprend ce qui manque.
- **Réimport complet partiel** : les fichiers en échec sont mémorisés et seuls eux sont repris aux passages suivants ; le réimport complet n'est pas relancé en entier.
- **Fichiers en trop après un changement de langue** : utilisez le bouton « Nettoyer les orphelins » une fois activé.

## Contribution

Les suggestions et rapports de bugs sont les bienvenus dans les [Issues](https://github.com/Kenny3231/avatar_explorer-ha/issues). Les tests s'exécutent avec `pip install -r requirements_test.txt` puis `pytest`.

## Licence

[MIT](LICENSE)

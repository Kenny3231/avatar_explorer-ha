Avatar Explorer 🧔👨
Avatar Explorer est une intégration personnalisée pour Home Assistant conçue pour gérer et afficher des avatars (Bitmojis) de manière dynamique. Elle permet de changer votre photo de profil en un clic et d'envoyer des "emojis" (réactions visuelles) vers d'autres utilisateurs ou tablettes de la maison, avec notifications mobiles intégrées.

🚀 Fonctionnalités
Sélecteur d'Avatar : Changez l'image de votre sensor "avatar" instantanément.

Système d'Envoi : Envoyez une image à un autre membre de la famille.

Notifications Natives : Envoi automatique d'une notification avec l'image sur l'appareil mobile du destinataire (configurable par utilisateur).

Mode Duo : Un mode spécial pour les couples ou la famille avec un affichage dédié.

Interface Fluide : Recherche par nom et filtrage par catégories.

📦 Installation
Via HACS (Recommandé)
Ouvrez HACS dans Home Assistant.

Cliquez sur les 3 petits points en haut à droite et choisissez Dépôts personnalisés.

Ajoutez l'URL de ce dépôt et sélectionnez la catégorie Intégration.

Cliquez sur Installer.

Redémarrez Home Assistant.

Installation Manuelle
Copiez le dossier custom_components/avatar_explorer/ dans votre dossier config/custom_components/.

Redémarrez Home Assistant.

🖼️ Téléchargement des Avatars (Important)
Pour que l'intégration fonctionne, vous avez besoin de fichiers d'avatars et de leurs fichiers metadata.json associés.

⚠️ Étape obligatoire actuellement :
Les bibliothèques d'avatars ne sont pas encore incluses automatiquement. Vous devez les télécharger manuellement depuis ce dépôt :
👉 GitHub : Pose-Explorer

Note : Une automatisation pour télécharger ces avatars directement depuis l'intégration est prévue pour une future mise à jour.

⚙️ Configuration
1. L'Intégration
Allez dans Paramètres > Appareils et services > Ajouter l'intégration.

Cherchez Avatar Explorer.

Indiquez le dossier racine (ex: images/avatar).

Ajoutez vos utilisateurs en indiquant le nom exact de leur dossier d'images (ex: Kenny).

2. La Carte Dashboard
L'intégration installe automatiquement la ressource de la carte. Pour l'afficher :

Ajoutez une carte manuellement dans votre tableau de bord.

Utilisez le type custom:avatar-card.

Dans l'éditeur visuel, configurez vos utilisateurs et leurs appareils de notification.

Exemple de configuration manuelle :

YAML
type: custom:avatar-card
duo_label: "👩‍❤️‍👨 Nous"
users:
  - user_id_folder: Kenny
    label: "🧔 Kenny"
    notify_service: mobile_app_iphone_de_kenny
    is_default: true
🛠️ Actions (Services) disponibles
L'intégration expose deux actions principales :

avatar_explorer.set_avatar : Définit l'image de profil d'un utilisateur.

avatar_explorer.send_emoji : Envoie une image et déclenche une notification.

🤝 Contribution
Les suggestions et rapports de bugs sont les bienvenus via les "Issues" du projet.

💡 Rappel pour l'utilisateur
Si vous avez configuré la carte pour utiliser le chemin /local/avatar-card.js, assurez-vous que le fichier avatar-card.js est bien présent dans votre dossier www/ de Home Assistant.
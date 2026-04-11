# Avatar Explorer 🧔

**Avatar Explorer** est une intégration personnalisée pour Home Assistant conçue pour gérer et afficher des avatars (Bitmojis) de manière dynamique. Elle permet de changer votre photo de profil en un clic et d'envoyer des "emojis" (réactions visuelles) vers d'autres utilisateurs ou tablettes de la maison, avec notifications mobiles intégrées.

---

## 🚀 Fonctionnalités

* **Sélecteur d'Avatar** : Changez l'image de votre sensor "avatar" instantanément.
* **Système d'Envoi** : Envoyez une image à un autre membre de la famille.
* **Notifications Natives** : Envoi automatique d'une notification avec l'image sur l'appareil mobile du destinataire (configurable par utilisateur).
* **Mode Duo** : Un mode spécial pour les couples ou la famille avec un affichage dédié.
* **Interface Fluide** : Recherche par nom et filtrage par catégories.

---

## 📦 Installation

### Via HACS (Recommandé)
1. Ouvrez **HACS** dans Home Assistant.
2. Cliquez sur les **3 petits points** en haut à droite et choisissez **Dépôts personnalisés**.
3. Ajoutez l'URL de ce dépôt et sélectionnez la catégorie **Intégration**.
4. Cliquez sur **Installer**.
5. Redémarrez Home Assistant.

### Installation Manuelle
1. Copiez le dossier `custom_components/avatar_explorer/` dans votre dossier `config/custom_components/`.
2. Redémarrez Home Assistant.

---

## 🖼️ Téléchargement des Avatars (Important)

Pour que l'intégration fonctionne, vous avez besoin de fichiers d'avatars et de leurs fichiers `metadata.json` associés.

⚠️ **Étape obligatoire actuellement :**
Les bibliothèques d'avatars ne sont pas encore incluses automatiquement. Vous devez les télécharger manuellement depuis ce dépôt :
👉 [**GitHub : Pose-Explorer**](https://github.com/Kenny3231/Pose-Explorer)

*Note : Une automatisation pour télécharger ces avatars directement depuis l'intégration est prévue pour une future mise à jour.*

---

## ⚙️ Configuration

### 1. L'Intégration
1. Allez dans **Paramètres** > **Appareils et services** > **Ajouter l'intégration**.
2. Cherchez **Avatar Explorer**.
3. Indiquez le dossier racine (ex: `images/avatar`).
4. Ajoutez vos utilisateurs en indiquant le nom exact de leur dossier d'images (ex: `Kenny`).

### 2. La Carte Dashboard
L'intégration enregistre automatiquement la ressource de la carte. Pour l'afficher :
1. Ajoutez une carte manuellement dans votre tableau de bord.
2. Utilisez le type `custom:avatar-card`.
3. Dans l'éditeur visuel, configurez vos utilisateurs et leurs appareils de notification.

**Exemple de configuration YAML :**
```yaml
type: custom:avatar-card
duo_label: "👩‍❤️‍👨 Nous"
users:
  - user_id_folder: Kenny
    label: "🧔 Kenny"
    notify_service: mobile_app_iphone_de_kenny
    is_default: true
```

🛠️ Actions (Services) disponibles
L'intégration expose deux actions principales :

avatar_explorer.set_avatar : Définit l'image de profil d'un utilisateur.

avatar_explorer.send_emoji : Envoie une image et déclenche une notification.

🤝 Contribution
Les suggestions et rapports de bugs sont les bienvenus via les "Issues" du projet.

💡 Note technique
L'intégration utilise /local/avatar-card.js comme point d'entrée statique pour la carte. Assurez-vous que le fichier avatar-card.js est présent dans le dossier de l'intégration pour que l'auto-enregistrement fonctionne correctement.

💡 Rappel pour l'utilisateur
Si vous avez configuré la carte pour utiliser le chemin /local/avatar-card.js, assurez-vous que le fichier avatar-card.js est bien présent dans votre dossier www/ de Home Assistant.

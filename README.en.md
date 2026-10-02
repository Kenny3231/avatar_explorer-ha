# Avatar Explorer for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Version](https://img.shields.io/github/v/release/Kenny3231/avatar_explorer-ha)](https://github.com/Kenny3231/avatar_explorer-ha/releases)
[![Validate](https://github.com/Kenny3231/avatar_explorer-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/Kenny3231/avatar_explorer-ha/actions/workflows/validate.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

*[Version française](README.md)*

Custom integration for Home Assistant that downloads your Bitmoji poses from [Avatar Explorer](https://avatar-explorer.pages.dev), keeps them up to date by itself, and provides a Lovelace card to change your avatar in one click or send a pose to another member of the household, with a mobile notification.

- Website: <https://avatar-explorer.pages.dev>
- Website repository: <https://github.com/Kenny3231/Avatar_Explorer>

## Features

- **Automatic, incremental sync**: the integration compares the remote catalog with your files and only downloads missing or changed poses. The check interval is adjustable from 1 to 168 hours (24 h by default).
- **Catalog language**: French, French (Canada), English, Spanish, German, Italian, Portuguese, Polish, Romanian, Turkish, Greek, Japanese, Korean, Chinese. The language sets the titles, keywords and **file names** of the poses, and also how many there are (1261 in French, 1975 in English). Changing language therefore downloads an entirely new set of images.
- **Image quality**: Web (lightest, recommended), HD (twice as detailed) or Ultra (four times, heavy files).
- **Duo mode**: two-character poses for the pair of users you choose, in a `Duo` folder.
- **Buttons**: sync now, full re-import, clean up orphans.
- **Sensors**: one per user, plus three diagnostic sensors to follow the sync.
- **Lovelace card** `custom:avatar-card`: search, category filter, enlarged preview, usable with a keyboard and a screen reader, French and English interface.
- **Notifications**: sends the pose to the recipient's phone through a `notify.*` service.

## Installation

### With HACS (recommended)

1. In HACS, open the **⋮** menu > **Custom repositories**.
2. Add `https://github.com/Kenny3231/avatar_explorer-ha` with the **Integration** category.
3. Install **Avatar Explorer**, then restart Home Assistant.

### Manual

1. Copy the `custom_components/avatar_explorer/` folder into `config/custom_components/`.
2. Restart Home Assistant.

Home Assistant **2026.1.0** or newer is required.

## Configuration

Everything is done in the UI: **Settings** > **Devices & services** > **Add integration** > **Avatar Explorer**.

1. **Image folder**, relative to the Home Assistant `www/` folder (default `images/avatar`). Letters, digits, `_`, `-` and `/` only.
2. **Users**: for each one, a folder name (letters, digits, `_` and `-`, 32 characters max; `Duo` is reserved), their **Bitmoji ID** and, optionally, the linked Home Assistant person.
3. **Duo pair**: the two users of the Duo mode.
4. **Synchronization**: check interval, quality and catalog language.

You can change these settings later with **Configure** on the integration. Only one instance of the integration is allowed.

> **Finding your Bitmoji ID.** The Avatar Explorer website downloads the images but does not show it. Log in on bitmoji.com and find it with the browser developer tools (F12). Expected format: letters, digits, dashes and underscores, for example `XXXXXXXXXX_X-s5`.

Changing a Bitmoji ID or the quality triggers a full re-import. Changing the language downloads a new set of images; the old ones stay on disk and the avatars currently displayed will have to be selected again.

Images are stored in `config/www/<folder>/<user>/`, with one `metadata_<user>.json` file per user (and a `Duo` folder).

## Lovelace card

The card is **registered automatically**: the integration serves it at `/avatar_explorer/avatar-card.js` (with the version as a parameter, so the browser reloads the card on every update) and adds it to the dashboard resources. An old `/local/avatar-card.js` resource is migrated in place, without touching your dashboards.

**Dashboards in YAML mode**: Home Assistant does not allow adding the resource automatically. A repair (**Settings** > **System** > **Repairs**) reports it, with the exact URL to use, as long as `configuration.yaml` does not contain the URL of the installed version. Add it by hand, replacing `/local/avatar-card.js` if it is listed, then restart:

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /avatar_explorer/avatar-card.js?v=1.2.0
      type: module
```

Card example:

```yaml
type: custom:avatar-card
dir: images/avatar          # image folder, as in the integration
show_duo: true              # shows the Duo entry in the list
duo_label: "👩‍❤️‍👨 Us"         # label of the Duo mode
users:
  - user_id_folder: Kenny   # folder name configured in the integration
    label: "🧔 Kenny"
    notify_service: mobile_app_kenny_iphone   # notify service called on reception
    is_default: true        # user selected when the card opens
  - user_id_folder: Lea
    label: "👩 Lea"
    notify_service: mobile_app_leas_phone
```

The card's visual editor offers the users already created by the integration, the default user and the notification service. A pose sent to another user triggers a notification when `notify_service` is set.

## Actions (services)

| Action | Fields | Effect |
|---|---|---|
| `avatar_explorer.set_avatar` | `user_id` (required), `image_path` (required) | Sets a user's avatar (`text.avatar_<user>` entity). |
| `avatar_explorer.send_emoji` | `to_user` (required), `image_path` (required), `from_label`, `notify_service` | Sends a pose to a user (`text.emoji_recu_<user>` entity) and, if `notify_service` is set, a notification with the image. |
| `avatar_explorer.force_reimport` | none | Forces a check and downloads the missing poses, even if the catalog is up to date. |

- `user_id` and `to_user`: the user's folder name, for example `Kenny`. An unknown user raises an error.
- `image_path`: `/local/...` path of a PNG image from the catalog. Other paths or URLs are rejected.
- `notify_service`: a `notify` service, with or without the `notify.` prefix (for example `mobile_app_leas_phone`). A service that does not exist raises an error before anything is changed.
- `from_label`: sender label passed by the card, informational.

```yaml
action: avatar_explorer.send_emoji
data:
  to_user: Lea
  image_path: /local/images/avatar/Duo/Kenny__Lea__calin.png
  notify_service: mobile_app_leas_phone
```

## Entities

| Entity | Role |
|---|---|
| `sensor.<user>_dynamique` | State of the linked Home Assistant person; the sensor picture is the current avatar. |
| `text.avatar_<user>` | Path of the current avatar (written by `set_avatar`). |
| `text.emoji_recu_<user>` | Last pose received (written by `send_emoji`). |
| `sensor.avatar_explorer_sync` | Diagnostic: summary of the last sync. |
| `sensor.avatar_explorer_sync_etat` | Diagnostic: `a_jour` (up to date), `partielle` (partial), `erreur` (error) or `inconnu` (unknown), with counters (downloaded, already present, failures, orphans). |
| `sensor.avatar_explorer_sync_date` | Diagnostic: date of the last check. |
| `button.avatar_explorer_sync` | Sync now. |
| `button.avatar_explorer_reimport_complet` | Rewrites every file. |
| `button.avatar_explorer_nettoyer_orphelins` | Deletes images that are no longer in the catalog (avatars in use are spared). **Disabled by default**: enable it in the entity settings. |

Entity IDs and attribute names are in French for compatibility with earlier versions.

## Privacy

- **Images are served without authentication.** Home Assistant publishes the `www/` folder under `/local/` without requiring a login: anyone who can reach your instance (anyone at all if it is exposed to the Internet) can open these URLs if they know the file name. Do not put anything sensitive in that folder.
- **Bitmoji IDs are sent as query parameters** to the Avatar Explorer API (`avatar-explorer.pages.dev`) on every sync. They may therefore show up in the logs of a server or intermediate proxy. They are stored in Home Assistant's configuration.
- The integration contacts two hosts, over HTTPS only: `avatar-explorer.pages.dev` (catalog timestamp, list of poses to download, `metadata_*.json` files) and `sdk.bitmoji.com` (the images themselves, whose URL contains your Bitmoji ID). Any other address is refused, redirects included.
- The integration's logs never contain Bitmoji IDs: only the mode and folder names are logged.

## Troubleshooting

Check the logs:

```
ha core logs | grep avatar_explorer
```

For detailed traces, add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.avatar_explorer: debug
```

- **The card does not appear**: check that the `/avatar_explorer/avatar-card.js` resource is listed under **Settings** > **Dashboards** > **Resources** (advanced mode in your profile), then clear the browser cache.
- **No images**: look at `sensor.avatar_explorer_sync_etat` and its `raison` attribute, then press the sync button. A `partielle` status means occasional download failures; the next sync retries them.
- **Overloaded server or rate limit**: the integration retries by itself, honoring the delay requested by the server. After 20 files in a row refused with 429 or 5xx, or 30 minutes of downloading, the run stops with the `partielle` status; the next run resumes what is missing.
- **Partial full re-import**: failed files are remembered and only they are retried on the following runs; the full re-import is not restarted from scratch.
- **Leftover files after a language change**: use the "Clean up orphans" button once enabled.

## Contributing

Suggestions and bug reports are welcome in the [Issues](https://github.com/Kenny3231/avatar_explorer-ha/issues). Run the tests with `pip install -r requirements_test.txt` then `pytest`.

## License

[MIT](LICENSE)

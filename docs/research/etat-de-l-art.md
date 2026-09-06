# État de l'art — routage de notifications, adaptateurs TTS et cartes d'alertes pour Home Assistant

Date : 2026-09-06. Cible : HA 2026.9. Sources : GitHub (API, étoiles et dates relevées le 06/09/2026),
listes HACS default (`hacs/default`, branche master du 06/09/2026), forum community.home-assistant.io,
docs HA et developers.home-assistant.io. Aucune recommandation de nommage ici : uniquement des faits.

## 0. Le contexte HA qui change tout (à lire d'abord)

| Fait | Source | Date |
|---|---|---|
| L'intégration `alert` est **gelée** : docstring `DEVELOPMENT OF THE ALERT INTEGRATION IS FROZEN`, `quality_scale: internal`, codeowners `@home-assistant/core` + `@frenck`. Motif du PR : « peut être remplacée par une automatisation, on ne veut pas maintenir ce genre d'intégration… avec les blueprints il y a moins besoin ». | [core PR #151486](https://github.com/home-assistant/core/pull/151486) (MartinHjelmare) | 2025-09-01 |
| `alert` ne sait appeler **que des services notify legacy** : `hass.services.async_call("notify", <notifier>, {message,title,data})`. Aucune prise en charge des entités notify / `notify.send_message`. | [entity.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/alert/entity.py) `_send_notification_message` | dev, 06/09/2026 |
| Le PR communautaire ajoutant les notifiers à base d'entités dans `alert` a été **fermé sans merge** par frenck : « development is frozen. We recommend using automations (or automation blueprints) instead ». | [core PR #155943](https://github.com/home-assistant/core/pull/155943) | fermé 2025-11-08 |
| Demande de bannière « déprécié » sur la doc `alert` : fermée pour inactivité, la page [alert](https://www.home-assistant.io/integrations/alert/) n'affiche **aucune** mention de gel. | [home-assistant.io #42151](https://github.com/home-assistant/home-assistant.io/issues/42151) | 2025-12-04 → 2026-02-10 |
| Plateforme **notify entity** : `notify.send_message` (message + title, ciblage entity/device/area/label), état = horodatage du dernier envoi. Migration « par phases », pas de calendrier ferme. | [Dev blog](https://developers.home-assistant.io/blog/2024/04/10/new-notify-entity-platform/), [architecture #1041](https://github.com/home-assistant/architecture/discussions/1041) | 2024-04 → 2025-01 |
| `notify.send_message` **n'accepte pas de `data`** (pas d'actions, image, tag, critical…). Demande ouverte, une seule réponse mainteneur (tr4nt0r) : « the notify entities are just the first step of an ongoing process ». | [discussion #3684](https://github.com/orgs/home-assistant/discussions/3684) | 2026-05-07, encore ouverte le 2026-08-30 |
| `mobile_app` expose des **entités notify** depuis 2026.5 ; helper UI « Notify group » pour grouper des entités notify. Les groupes notify legacy YAML (`platform: group`) restent documentés sans avis de dépréciation. | [doc notify](https://www.home-assistant.io/integrations/notify/), [doc group](https://www.home-assistant.io/integrations/group/) | 2026 |
| Dépréciations legacy concrètes : Telegram (`notify.telegram` → entités, 2025.11), template entities legacy (2025.12). `notify.alexa_media` a disparu chez certains après 2025.11.3. | [core PR #150720](https://github.com/home-assistant/core/pull/150720), [forum](https://community.home-assistant.io/t/action-notify-alexa-media-disappeared-after-2025-11-3-update/954055) | 2025-11 |
| `NotifyEntity._async_record_notification` (enregistrer un envoi déclenché autrement que par `send_message`) : approuvé par le core team. | [architecture #1238](https://github.com/home-assistant/architecture/discussions/1238) | approuvé 2026-03-19 |
| 2026.9 : section **« Active alerts »** du dashboard Sécurité (entités choisies + sévérité Alert/Warning, jaune/rouge, animation). Mécanisme **frontend propre**, sans lien avec `alert.*` ni avec notify ; remontée sur le dashboard Home annoncée « plus tard ». Changelog 2026.9 : rien sur notify/alert, seulement TTS (latence FFmpeg WAV #178709, `preferred_bitrate` #179760). | [Release 2026.9](https://www.home-assistant.io/blog/2026/09/02/release-20269/), [changelog](https://www.home-assistant.io/changelogs/core-2026.9/) | 2026-09-02 |

Lecture : HA ne prévoit **aucune** migration de `alert` vers les entités notify ; la ligne officielle est
« remplacez par des automatisations/blueprints ». Le trou « moteur d'alertes + acquittement + notifiers modernes »
est donc laissé au tiers (Alert2 l'occupe déjà, voir A).

## A. Routeurs / hubs de notification existants

### A.1 Custom components (Python)

| Projet | ⭐ | Dernier push | Dernière release | HACS | Point d'entrée | Routage par personne | Présence | DND / horaires | Snooze | Acquittement | Lien `alert.*` | Config |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [Notifier Hub](https://github.com/rafaalbelda/notifier_hub) (rafaalbelda) — GPL-3.0 | 35 | 2026-07-09 | v1.0.3 (2026-07-09) | custom repo | service `notifier_hub.send` (pas de plateforme `notify`) | oui (liste `persons`, filtre `location`) | oui, `person.*` ou tracker legacy ; `speech_home_only`, mode invité | switch DND + DND nuit via périodes Auto Volume | non | « confirmation avec escalade » par boutons | non (envoie vers des `notify.*`, PN, Alexa via AMP `notify.alexa_media` uniquement, Cast via `tts.*`, ha-sip) | UI + import YAML |
| [Supernotify](https://github.com/rhizomatics/supernotify) (rhizomatics) — Apache-2.0, min HA 2025.12.2 | 19 | 2026-09-06 | v2.3.1 (2026-09-06) | **default** | `supernotify.notify` + plateforme legacy `notify.supernotify` + « style entité notify, support UI limité » | oui, modèle « People » (`target: person.x` → email/SMS/mobile) | oui, « occupancy » dans les scénarios (`everyone_home_day`, recette Home Alone) | via scénarios conditionnels ; 4-5 priorités (`minimum`→`critical`) | oui, par actions mobiles : `SNOOZE/SILENCE/NORMAL` × `USER/EVERYONE` × `NONCRITICAL/EVERYTHING/TRANSPORT/DELIVERY/CAMERA/PRIORITY/MOBILE` ; **non persistant au reboot** ; services `clear_snoozes`/`enquire_snoozes` | non documenté | non | YAML (`supernotify.yaml`), scénarios, dédoublonnage, archive |
| [Universal Notifier](https://github.com/jumping2000/universal_notifier) (hassiohelp.eu) — MIT | 228 | 2026-09-06 | v0.9.0 (2026-09-06, « notify.send_message support ») | **default** | service `universal_notifier.send` | ciblage par canal, pas par personne | capteur `Family` (home/not_home) à partir de `person.*` | quiet hours (défaut 23:00-06:00) + switch « DND override » ; `priority: true` outrepasse et force le volume | non | non | non | UI (wizard) |
| [Ticker](https://github.com/analytix-energy-solutions/ticker) — Apache-2.0 (créé 2026-03-02) | 170 | 2026-07-26 | v1.8.2 (2026-07-14) | **default** | `ticker.notify` + s'enregistre comme service legacy `notify.ticker` (compat Alarmo/blueprints) | oui : catégories × abonnements par utilisateur (Always/Never/Conditional) | conditions zone/heure/état avec AND/OR/NOT ; **file d'attente** quand la condition n'est pas remplie | conditions horaires par abonnement | **oui, par utilisateur et par catégorie** (v1.3) | suivi d'acquittement + historique consultable | non | 2 panneaux sidebar (admin/utilisateur), wizard de migration des automatisations, « device recipients » TTS + carillon + restauration volume |
| [ANS — Advanced Notification System](https://github.com/txxa/hass-ans) (txxa) — MIT (créé 2025-10) | 69 | 2026-08-19 | — | custom repo | `ans.send_notification` (**sans paramètre `target`**, tout passe par les profils) | par destinataire (allow-list de types, blocage de sources) | non listé | DND par destinataire avec règles de contournement ; criticité LOW→CRITICAL | non | oui, registre d'acquittement persistant (tap/dismiss) | non | UI ; rate-limit, retries, dédup, audit, Repairs |
| [Notification Dispatcher « Herald »](https://github.com/jesterrace-666/ha-notification-dispatcher) — (créé 2026-05-10) | 0 | 2026-05-24 | 1.x | custom repo | `notification_dispatcher.send` | oui : profils `person.*` → `notify.*`, groupes, cible `all` | option « seulement si à la maison » | DND par personne + fenêtres semaine/week-end ; types critical/warning/info/reminder ; critical passe toujours ; fallback | non | non | non | UI |
| [Smart Presence Notify](https://github.com/portbusy/smart-presence-notify) — MIT (créé 2026-04-27) | 1 | 2026-08-31 | — | **default** | `smart_presence_notify.send` | tous les présents / admin / cible explicite | oui + file d'attente si personne (last/FIFO/summary) | priorité `high` court-circuite la file | non | Oui/Non actionnable | non | UI |
| [Alert2](https://github.com/redstone99/hass-alert2) (redstone99) — moteur d'alertes, pas un routeur | 87 | 2026-08-29 | v1.21 (2026-08-29) | **default** | entités `alert2.*` ; appelle des notifiers legacy (`notify.<x>`) ou un groupe YAML | notifiers par template (« qui est notifié ») | via templates | throttling, `supersedes` | oui | oui (`acq_required`, rappels stoppés) | remplace `alert` | YAML ou UI ; carte [hass-alert2-ui](https://github.com/redstone99/hass-alert2-ui) (13 ⭐, default) |
| [AlertSys](https://github.com/gleanlux/alertsys) — GPL-3.0 | 12 | 2026-07-07 | — | **default** | entités `alertsys.*` (level info/warning/error, `ack`) | — | — | répétition/intervalle | — | oui (ack = mute) | remplace `alert` | panneau sidebar « Alert Manager » (admin) |
| [Combined Notifications](https://github.com/Pjarbit/home-assistant-combined-notification-integration) — MIT | 39 | 2026-09-01 | v8.x | **default** | un capteur agrégé + compteur | — | — | — | — | — | non | UI ; carte dédiée (6 ⭐) |
| [HA-NotifyHelper](https://github.com/kukuxx/HA-NotifyHelper) | 14 | 2026-03-01 | — | custom | service dédié | — | — | — | — | — | non | — |

Lignée AppDaemon : [jumping2000/notifier](https://github.com/jumping2000/notifier) (32 ⭐, **archivé**, dernier
commit 2024-01-07) et [caiosweet/Package-Notification-HUB-AppDaemon](https://github.com/caiosweet/Package-Notification-HUB-AppDaemon)
(57 ⭐, 2023-07-08) → convertis en Universal Notifier et Notifier Hub. Plus aucun hub AppDaemon actif.

Forum : [Notifier Hub](https://community.home-assistant.io/t/notifier-hub-centralized-notifications-for-home-assistant/1015779)
(2026-07-01, 2 réponses ; un utilisateur demande FIFO anti-chevauchement TTS, snapshot/restore des players) ;
[Supernotify](https://community.home-assistant.io/t/new-on-hacs-supernotify/953691) (2025-11-21, 6 réponses ; frustration
« pas moyen de cibler une personne en standard ») ; [Notification Dispatcher](https://community.home-assistant.io/t/notification-dispatcher-centralized-notification-routing-for-home-assistant/1010007)
(2026-05-10, 0 réponse) ; [« Best approach for dynamic notification routing based on presence »](https://community.home-assistant.io/t/best-approach-for-handling-dynamic-notification-routing-based-on-presence-detection/1019151)
(2026-07-29) → réponse : Ticker.

### A.2 Blueprints et Node-RED

| Solution | Ce que ça fait | Limites |
|---|---|---|
| [📢 Notifications & Announcements](https://community.home-assistant.io/t/notifications-announcements/728100) (Blacky, 2024-05, v1.5 2025-08-29, HA ≥ 2024.6, 51 likes) | trigger état/zone/seuil → mobile + PN + TTS media_player, fenêtres horaires, options iOS/Android | une automatisation par cas, pas de routage par personne, pas d'ack |
| [Alert Notification Blueprint](https://gist.github.com/pavax/08705e383bdd3b58ea7b75a1f01c7e54) (pavax, 30 révisions, 2026-08-09) | répétition tant que l'état persiste, dismiss par `input_boolean`, actions custom (TTS) | pas de personnes ; ré-implémente `alert` sans entité |
| [Confirm/Dismiss/Timeout](https://gist.github.com/sle118/a7a9307185b7f923876fe8975c965aa9) (sle118) | notification actionnable avec confirm/dismiss/timeout | mono-destinataire |
| Node-RED : [sous-flow notification](https://flows.nodered.org/flow/662105e9bda01d2ef81b0bbac84385e8), tutos actionnables (Daniel Carr 2022, The Hook Up 2022) | briques de flux à copier | aucun « routeur » packagé avec personnes/DND/snooze |

## B. Parler : plateformes `notify` TTS et annonces

### B.1 Ce que le core offre

| Mécanisme | Statut | Détails |
|---|---|---|
| [`tts.speak`](https://www.home-assistant.io/actions/tts.speak/) | moderne | `entity_id` (moteur TTS), `media_player_entity_id`, `message`, `cache`, `language`, `options` (format, sample_rate…). Pas de paramètre announce. |
| [`media_player.play_media` `announce: true`](https://www.home-assistant.io/actions/media_player.play_media/) | moderne | « interrompt temporairement la lecture… si le lecteur le supporte ». Intégrations core déclarant `MediaPlayerEntityFeature.MEDIA_ANNOUNCE` (grep core dev, 06/09/2026) : **bang_olufsen, esphome, forked_daapd, group, music_assistant, sonos, squeezebox**. **Ni `cast`, ni `apple_tv`**. |
| [Notify TTS platform](https://www.home-assistant.io/integrations/notify.tts/) (`notify: - platform: tts`) | **legacy** (service `notify.<name>`, YAML, depuis 0.117, ~9 % des installs) | `entity_id` ou `tts_service` + `media_player` + `language`. Pas d'annonce, pas d'entité notify. C'est le seul pont core « notify → TTS », et c'est celui que `alert` peut appeler. |
| [Alexa Devices](https://www.home-assistant.io/integrations/alexa_devices/) (core, 2025.6) | moderne | 2 **entités notify** par appareil : `Speak` et `Announce` (carillon + message), via `notify.send_message`. Rate-limit Amazon sur multi-cibles → passer par les groupes Alexa. Bugs 2025 sur groupes WHA ([#146574](https://github.com/home-assistant/core/issues/146574), [#146892](https://github.com/home-assistant/core/issues/146892)). MFA obligatoire. |
| Notify group helper (UI) | moderne | groupe d'entités notify, `send_message` sans `data`. |
| Notify group legacy (`platform: group`) | legacy, non déprécié | seul moyen de fan-out avec `data` riche. |

### B.2 Music Assistant et ses annonces

[Announcements MA](https://www.music-assistant.io/integration/announcements/) : `tts.speak` vers un player MA ou
[`music_assistant.play_announcement`](https://www.home-assistant.io/actions/music_assistant.play_announcement/) (URL,
pré-carillon, volume). MA gère pause → annonce → reprise et allume/éteint le player. Overlay natif (ducking sans
couper la musique) **uniquement Sonos S2 et Sendspin** ; les autres (AirPlay, Squeezelite, Cast…) passent par
pause/reprise, avec « interruptions notables » sur groupes AirPlay/Squeezelite et reprise non garantie des enfants
de groupe. HomePod pris en charge par le provider [AirPlay](https://www.music-assistant.io/player-support/airplay/)
(exiger « Everyone on the same network » dans HomeKit ; AirPlay 2 « nouveau, peu testé »). L'ancien
`hass-music-assistant` custom (16 ⭐) est déprécié au profit du core.

### B.3 Custom components qui parlent

| Projet | ⭐ | Dernier push | HACS | Rôle |
|---|---|---|---|---|
| [Alexa Media Player](https://github.com/alandtse/alexa_media_player) | 1 974 | 2026-09-01 | default | `notify.alexa_media` legacy (`data.type: tts/announce/push`), API non officielle ; blueprint [Notify Alexa devices](https://community.home-assistant.io/t/notify-alexa-devices-using-alexa-media-player/602716). Requis par Notifier Hub. |
| [Chime TTS](https://github.com/nimroddolev/chime_tts) | 369 | 2026-09-05 | default | `chime_tts.say` / `say_url` / `replay` : concatène carillon + TTS en un fichier, volume, pause/reprise (HomePod cité), cache. Pas de plateforme notify, pas de routage. |
| [LMS TTS Notify](https://github.com/floris-b/lms_tts_notify) | 31 | 2025-09-30 | custom | file d'attente TTS pour Squeezebox, plateforme notify legacy. |
| [google_tts](https://github.com/IAmStiven/google_tts) | — | — | custom | moteur TTS (pas un adaptateur notify). |

Aucun custom component ne fournit aujourd'hui une **entité notify** (`notify.send_message`) qui parle sur Cast ou
AirPlay ; Alexa en a une (core). La demande [Notify TTS for AirPlay](https://community.home-assistant.io/t/notify-tts-also-for-airplay-privacy-first/722416)
(2024-04, 8 réponses) n'a eu que des contournements (`tts.speak` sur `apple_tv`, Chime TTS). Cast : problèmes
récurrents d'URL interne ([#142021](https://github.com/home-assistant/core/issues/142021)), et scripts communautaires
« resume after TTS » depuis 2020.

## C. Cartes Lovelace d'alertes / notifications

| Carte | ⭐ | Dernier push | HACS | Lit quoi | Notes |
|---|---|---|---|---|---|
| [AlertTicker-Card](https://github.com/djdevil/AlertTicker-Card) (MIT, créé 2026-03-28) | 318 | 2026-08-30 (v1.3.9.9.7) | custom repo | **états d'entités** quelconques + `device_class` + templates Jinja ; **pas** `alert.*`, pas les PN | 53 thèmes, snooze par alerte **en localStorage** (sync via événements WS), TTS/push depuis la carte, bannière overlay globale, écrit dans un `input_boolean`, éditeur visuel complet. |
| [Home Feed Card](https://github.com/gadgetchnnel/lovelace-home-feed-card) | 303 | **2024-02-23** | default | persistent notifications + calendriers + entités | référence historique, plus maintenue. |
| [hass-alert2-ui](https://github.com/redstone99/hass-alert2-ui) | 13 | 2026-08-29 | default | entités `alert2.*` uniquement | overview des alertes actives/snoozées/désactivées, more-info enrichi. |
| [Combined Notifications Card](https://github.com/Pjarbit/home-assistant-combined-notifications-card-new) | 6 | 2026-06-07 | custom | son capteur agrégé | appairage documenté avec AlertTicker. |
| [lovelace-notify-card](https://github.com/bernikr/lovelace-notify-card) | 63 | 2026-05-11 | default | — | envoyer une notif depuis le dashboard (sens inverse). |
| [ha-alert](https://github.com/bartjanisse/ha-alert) | 0 | 2026-03-27 | — | ses propres alertes (`ha_alert.create/acknowledge/dismiss`) | carte ack/dismiss incluse. |
| Core | — | — | — | `entity-filter`, tuile, [Active alerts 2026.9](https://www.home-assistant.io/blog/2026/09/02/release-20269/) | Active alerts : sélection d'entités + sévérité, dashboard Sécurité seulement. |

Aucune carte HACS ne lit les entités **`alert.*` du core** (état on/off/idle, `alert.turn_off` pour acquitter) ;
la demande [Alert card](https://community.home-assistant.io/t/alert-card/675412) (2024) est restée sans carte
dédiée. Aucune carte « tuiles DND par personne » packagée : le forum se contente d'`input_boolean` +
carte tuile ([exemple](https://community.home-assistant.io/t/how-to-create-dismissable-notifications-alerts-on-the-dashboard/934708)).

## D. Où va HA (synthèse des discussions 2024-2026)

1. **`alert` : gelé, pas déprécié, pas migré.** Gel officiel 2025-09-01 ; refus d'ajouter les notifiers-entités
   (2025-11-08) ; docs sans bannière ; code inchangé hors refactors globaux (derniers commits : imports, `@override`).
   Le remplaçant officiel est « une automatisation ou un blueprint », pas une intégration.
2. **Notify entity : le chantier avance lentement.** `send_message` = message + title ; `data` refusé par principe
   (« champs typés » à venir, cf. #1041) ; les intégrations legacy migrent une à une (Telegram 2025.11, mobile_app
   2026.5) en cassant les automatisations à la fin de la période de dépréciation. Les notifs riches mobiles
   (actions, tag, critical, image) restent **legacy-only** au 2026-08-30 (#3684).
3. **Aucun plan « alert → notify entity »** n'existe dans architecture/, core ou la doc. Le core investit à la place
   dans une couche frontend (« Active alerts », Sécurité 2026.9, extension au dashboard Home annoncée).
4. Conséquence pratique pour un routeur : pour être appelable par `alert` (et par Alarmo, blueprints, Frigate…),
   il faut **encore** exposer un service legacy `notify.<nom>` (c'est ce que font Supernotify et Ticker) ; exposer
   en plus une entité notify prépare la suite mais ne reçoit pas de `data`.

## E. Publier une intégration custom en 2026 — outillage et exigences

| Sujet | Fait | Source |
|---|---|---|
| Template de repo | [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint) : 603 ⭐, push 2026-09-06, devcontainer, `scripts/develop`, manifest avec `version`, `issue_tracker`, `config_flow`. Variante [jpawlowski/hacs.integration_blueprint](https://github.com/jpawlowski/hacs.integration_blueprint) (49 ⭐, 2026-08-24, MIT) : HA 2026.8+/Python 3.14, `uv`, Ruff, Pyright, pytest-homeassistant-custom-component préconfiguré, workflows hassfest + HACS, Release Please, fichiers d'instructions pour agents IA, sync hebdo du template. | README des deux repos |
| Tests | [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) 109 ⭐, **0.13.364 (2026-09-06) suit HA 2026.9.1** ; fixture `enable_custom_integrations` obligatoire ; importer depuis `pytest_homeassistant_custom_component.common`. | README |
| hassfest | action `home-assistant/actions/hassfest@master` ([home-assistant/actions](https://github.com/home-assistant/actions), 48 ⭐, 2026-08-03). Manifest custom : `domain`, `name`, `codeowners`, `documentation`, `issue_tracker`, `version` (obligatoire, AwesomeVersion), `integration_type` (`service`/`helper`/`hub`…), `iot_class`, `dependencies`, `requirements`. | [manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/) |
| Quality scale | 4 tiers (bronze/silver/gold/platinum) + spéciaux (`internal`, `legacy`, `custom`). Le tier **`custom` est attribué automatiquement** aux intégrations tierces : elles ne sont pas notées ; le `quality_scale.yaml` est un mécanisme core. Utile comme check-list (config flow UI, tests, doc, gestion erreurs/hors-ligne), pas comme label. | [quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/), [ADR-0022](https://github.com/home-assistant/architecture/blob/master/adr/0022-integration-quality-scale.md) |
| HACS action | `hacs/action@main` (37 ⭐, 2026-07-21), `category: integration|plugin|…` ; checks : archived, brands, description, hacsjson, images, information, issues, topics ; `ignore` possible mais **interdit pour l'inclusion default**. | [hacs.xyz/publish/action](https://www.hacs.xyz/docs/publish/action/) |
| Inclusion HACS default | repo public GitHub, non archivé, description + issues activées + topics, `hacs.json` (au moins `name`; `homeassistant` = version min), **release GitHub** (pas un simple tag), HACS action et hassfest sans erreur ni ignore, une seule intégration par repo sous `custom_components/<domain>/`, brand (`icon.png` 256×256 dans [home-assistant/brands](https://github.com/home-assistant/brands) `custom_integrations/<domain>/` ou dossier `brand/`), PR sur `hacs/default` depuis un fork perso par le propriétaire. Plugins Lovelace : images dans le README. | [hacs.xyz/publish/include](https://www.hacs.xyz/docs/publish/include/), [integration](https://www.hacs.xyz/docs/publish/integration/) |
| Ordre de grandeur | `hacs/default` : 3 264 intégrations, 774 plugins listés (06/09/2026). Parmi les routeurs : Supernotify, Universal Notifier, Ticker, Smart Presence Notify, Alert2, AlertSys, Combined Notifications y sont ; Notifier Hub, ANS, Notification Dispatcher, AlertTicker-Card n'y sont pas. | fichiers `integration`/`plugin` du repo |

## Trous confirmés (ce que personne ne fait au 06/09/2026)

1. **Proxy `notify.*` → `notify.*` transparent.** Tous les hubs imposent leur propre service (`x.send`,
   `ticker.notify`, `ans.send_notification`) et leur propre modèle de destinataires. Seuls Supernotify et Ticker
   exposent aussi un `notify.<nom>` legacy, aucun ne se contente d'être un « notify qui route vers des notify »
   configurable en UI.
2. **Couplage avec les entités `alert.*` du core.** Aucun routeur ne lit `alert.*`, n'appelle `alert.turn_off`
   à l'acquittement, ni ne s'enregistre comme notifier « intelligent » pour `alert`. Les moteurs alternatifs (Alert2,
   AlertSys) remplacent `alert` au lieu de le compléter.
3. **Snooze par personne × par alerte, persistant.** Supernotify : snooze riche mais perdu au reboot ; Ticker :
   snooze par utilisateur × catégorie ; AlertTicker : localStorage du navigateur. Personne ne combine
   personne + alerte + persistance HA (storage/restore) + levée par priorité.
4. **DND par personne piloté par entités HA standard** (`schedule.*`, `input_boolean.*`, `person.*`) plutôt que par
   un modèle interne : Notification Dispatcher et ANS ont un DND par personne mais dans leur propre config ;
   Universal Notifier a un DND global.
5. **Adaptateurs notify-entité pour la voix** : aucune entité notify (`send_message`) pour Cast ou AirPlay ; Cast et
   Apple TV n'implémentent pas `MEDIA_ANNOUNCE` ; la reprise après TTS sur Cast reste artisanale depuis 2020.
6. **Carte Lovelace lisant `alert.*`** (bulle/compteur, acquittement via `alert.turn_off`) et **tuiles DND par
   personne** : inexistantes en HACS.
7. **Ciblage rich `data` via entités notify** : bloqué côté core (#3684) ; tout routeur moderne devra garder un
   double chemin legacy/entité.

## À réutiliser (ne pas recoder)

- **Cœur d'alertes** : `alert` core (gelé mais stable, `alert.turn_off/turn_on/toggle`, `can_acknowledge`, `repeat`,
  `done_message`, `data`) ou **Alert2** si l'on veut événements, templates, throttling, `supersedes` — ne pas
  réécrire un moteur d'alertes.
- **Voix** : `tts.speak` + `media_player.play_media announce:true` (Sonos, MA, ESPHome, Squeezebox, B&O) ;
  **Music Assistant** pour pause/reprise et AirPlay/HomePod ; **Alexa Devices** core (entités `Speak`/`Announce`) plutôt
  que `notify.alexa_media` ; **Chime TTS** pour carillon + TTS en un fichier et la reprise sur Cast/HomePod.
- **Fan-out** : helper UI « Notify group » (entités) et groupe legacy `platform: group` (avec `data`).
- **Présence** : `person.*` natif ; pour les zones/queues, regarder le code de Ticker (Apache-2.0) et de Smart
  Presence Notify (MIT).
- **Snooze par action mobile** : la grammaire `SNOOZE/SILENCE × USER/EVERYONE × cible` de Supernotify (Apache-2.0)
  et son appariement device-id → personne.
- **Acquittement/historique** : registre persistant d'ANS (MIT) et lifecycle d'actions de Ticker.
- **Dashboard** : AlertTicker-Card (MIT) pour l'UX (overlay, thèmes, éditeur visuel), Alert2-UI pour la structure
  d'une carte adossée à des entités d'alerte ; Active alerts 2026.9 comme référence visuelle (couleurs, pulsation).
- **Outillage** : `ludeeus/integration_blueprint` ou `jpawlowski/hacs.integration_blueprint`,
  `pytest-homeassistant-custom-component`, `hacs/action` + `hassfest`, procédure `hacs/default` et `brands`.

# Analyse concurrentielle — Supernotify (rhizomatics/supernotify)

Date : 2026-09-06. Sources : dépôt GitHub public (clone shallow local), README (+10 traductions), `docs/` (mkdocs, ~140 pages), CHANGELOG.md, TODO.md, manifest/hacs.json, code Python lu en lecture seule (aucune ligne copiée — seuls des noms de clés de config, classes et constantes, faits non protégeables, sont cités), issues et releases via `gh`.

## 1. Fiche

- **Licence** : Apache 2.0. **Étoiles** : 19 (1 fork) — dépôt créé 25/10/2025 mais très actif.
- **Dernier commit/push** : 06/09/2026 (jour même), release `v2.3.1` publiée le jour même ; ~40 tags depuis `v1.12.1`, plusieurs bêtas par version mineure.
- **Issues** : 5 ouvertes après filtrage des PR.
- **HACS** : oui, dans le **store par défaut** (`hacs/default`), pas seulement en dépôt custom.
- **Config** : hybride. Depuis `v2.0.0`, le setup de base passe par **ConfigFlow UI** (découverte auto apps mobiles/Alexa). Tout l'avancé (`delivery`, `scenario`, `recipients`, `cameras`, `action_groups`, `links`, `snooze`) reste **YAML uniquement**, dans un fichier `supernotify.yaml` auto-généré par migration *Repair* au passage en 2.0. Une UI pour deliveries/scenarios est en discussion, pas livrée (issue #166).
- **HA minimale** : `2025.12.2`. Python 3.13–3.14. `quality_scale: silver`.
- **Taille** : 42 fichiers Python, ~13 500 lignes (dont 20 modules de transport) ; fichiers cœur : `notify.py` (920 l.), `notification.py` (989 l.), `model.py` (867 l.), `hass_api.py` (788 l.), `schema.py` (600 l.), `snoozer.py` (276 l.), `scenario.py` (283 l.).

## 2. Modèle

- **Transport** : adaptateur bas niveau par plateforme (20 intégrés : email, mobile_push, sms, alexa_devices/media_player, mqtt, tts, chime, ntfy, gotify, telegram, lametric, pushover, html5, matrix, kodi, discord, generic, notify_entity, persistent, media). `generic` enrobe n'importe quel autre `notify.*`.
- **Delivery** : canal nommé (`delivery.<nom>`) avec `target_usage` (no_action/no_delivery/merge_delivery/merge_always/fixed), `target_required` (always/never/optional), `selection` (default/scenario/explicit/fallback/fallback_on_error), `priority`, `occupancy`, `conditions`, `selection_rank`. Trois deliveries par défaut auto-créées (`DEFAULT_email`, `DEFAULT_mobile_push`, `DEFAULT_notify_entity`).
- **Scenario** : bloc de config réutilisable, sélectionné manuellement (`apply_scenarios`) ou via `condition` HA, override `target`/`data`/`enabled` sur des deliveries existantes.
- **Target/Recipient** : *Target* direct (`entity_id`, `device_id`, email, téléphone, id custom) ou indirect (`person_id` ; `label_id`/`area_id`/`floor_id` pas encore résolus partout, issues #9/#10 ouvertes). *Recipient* = entrée du **People Registry**, auto-découverte depuis tous les `person.*` HA, exposée en `sensor.supernotify_recipient_XXXX` **et** en `notify.recipient_XXXX` (vraie `NotifyEntity`, membre possible d'un `Notify Group` HA natif) — mais pas de table de routage « présence par personne » : par défaut tout le monde reçoit tout, à charge du scénario/condition de restreindre.
- **Occupancy** : gate au niveau *Delivery*, pas par personne (`any_in`/`any_out`/`all_in`/`all_out`/`only_in`/`only_out`/`all`/`none`), calculé sur l'ensemble des trackers connus.
- **DND/heures** : pas de concept dédié « silence pour telle personne » — bloc `condition` HA générique réutilisé au niveau Scenario/Delivery, global à la delivery et non nommé par personne.
- **Priorité** : 5 niveaux ordonnés (`minimum(1)` à `critical(5)`), mais validation **assouplie** en v1.8.2 après un bug (#39) : n'importe quelle chaîne custom est désormais acceptée.
- **Snooze/silence** (`snoozer.py`) : classe `Snoozer`, **purement en mémoire — persistance explicitement absente** (« there is no persistence yet », `docs/usage/snoozing.md`). Trois commandes (`SNOOZE`/`SILENCE`/`NORMAL`), portée globale (`EVERYTHING`, `NONCRITICAL`) ou qualifiée (`TRANSPORT`, `DELIVERY`, `CAMERA`, `PRIORITY`, `MOBILE`), déclenchées par une action Companion `SUPERNOTIFY_<COMMANDE>_<RecipientType>_<TargetType>[_<minutes>]`. Destinataire retrouvé via `context.user_id` → `person.*`. **Aucune notion d'acquittement** : seulement snooze/silence/normal.
- **Dedup** (distinct du snooze) : 3 politiques (message+titre identiques avec/sans priorité, ou aucune), cache `cachetools.TTLCache`, `force_resend: true` pour bypasser.
- **Templates** : Jinja2 HTML natif, template email par défaut livré, variables de condition additionnelles (`notification_priority/message/title`, `applied_scenarios`, `occupancy`).
- **Persistance** : aucun `homeassistant.helpers.storage.Store` nulle part dans le code (vérifié par grep) — seule la config persiste (ConfigEntry + `supernotify.yaml`) ; aucun état runtime (snooze, dédup) ne survit à un redémarrage.

## 3. Face au contrat Switchboard v0

| Fonction | Supernotify | Switchboard v0 |
|---|---|---|
| Routage par personne | Audience implicite (tout le monde par défaut), pas de ligne nommée par personne | Table de routage : une ligne par personne, règle `always/home_only/away_only` |
| Silence par personne | Aucun concept dédié ; `condition` HA générique au niveau Delivery/Scenario | `binary_sensor.<person>_silenced` via `schedule`/`input_boolean`, bypass sur `critical` |
| Snooze personne×cible | En mémoire, scopes global/transport/delivery/priority/camera/mobile ; **non persistant** | Persistant `Store`, indexé (personne, cible), avec expiration, survit au redémarrage |
| Acquittement | **Absent** — seules commandes SNOOZE/SILENCE/NORMAL | Bouton Companion → `mobile_app_notification_action` → `alert.turn_off` (allow-list) |
| Intégration `alert` core | **Aucune** — zéro référence au domaine dans tout le code | Native : ack sur `alert.*` + mode Observer (ADR-007) |
| Service legacy `notify.<x>_<cible>` | `self.targets` jamais défini → pas de services par cible ; équivalent via `notify.recipient_XXXX` | Service legacy dédié `notify.switchboard_<target>` via `targets` |
| Priorité | 5 niveaux, validation assouplie (accepte tout) | 4 niveaux fermés, un seul bypass (`critical`) |
| Config UI | Base (ConfigFlow) oui ; routage/deliveries/scenarios encore YAML-only | Prévu configurable en UI dès v0 |
| Callback Companion | `mobile_app_notification_action`, action `SUPERNOTIFY_<CMD>_<Type>_<Type>[_<min>]` | Même événement, action `switchboard:<ack\|snooze>:<target>:<minutes?>` |
| Dédup | Intégrée, 3 politiques, TTL cache | `tag` transmis, logique de dédup non spécifiée dans le contrat |
| Observabilité | Archive fichier/MQTT + trace de debug, actions `enquire_*` | `event.switchboard_delivery` + compteurs par personne/globaux |

**Fait par eux, pas par nous** : multi-canal riche (20 transports), templating email HTML, snapshots caméra PTZ, dédup intégrée, `NotifyEntity` par destinataire compatible `Notify Group`, découverte auto apps mobiles/Alexa, `Context` HA propagé de bout en bout (v2.3.0), 11 langues UI.

**Fait par nous, pas par eux** : routage par personne avec présence en table, silence nommé par personne, snooze persistant indexé (personne, cible), acquittement relié à `alert.turn_off` avec allow-list, mode Observer sur `alert.*`, service legacy par cible via `targets`.

## 4. Interface avec `alert`, services legacy, callbacks Companion

- **`alert` core** : absent après grep exhaustif — aucune lecture d'état `alert.*`, aucun appel `alert.turn_off`, aucune option qui référence ce domaine. Occupancy et `condition` sont son seul mécanisme conditionnel.
- **Services legacy/`targets`** : `SupernotifyAction` hérite de `BaseNotificationService` (legacy) mais ne renseigne jamais `self.targets` → pas de génération auto de `notify.supernotify_<cible>`. Le ciblage passe par `target:` sur l'action unique, ou par `notify.recipient_XXXX`.
- **Callbacks Companion** : `on_mobile_action()` s'abonne au même événement `mobile_app_notification_action` que celui prévu côté Switchboard, filtré sur préfixe `SUPERNOTIFY_`. Mapping device → personne par `context.user_id`, échec silencieux (`_LOGGER.warning`) si aucune correspondance — pas de remontée visible à l'utilisateur, contrairement au `repairs` prévu côté Switchboard pour `unknown_target`.

## 5. Points faibles observés

- **Snooze non persistant, documenté comme tel** — limite assumée mais qui interdit tout usage sérieux du snooze pour une alerte qui compte (redémarrage = tout repart).
- **Migrations parfois lourdes** : le passage à `v2.0.0` a nécessité repairs et fichier YAML dédié auto-généré ; le mainteneur recommandait en bêta de « supprimer l'intégration et la laisser se recréer » en cas de blocage.
- **Complexité de config reconnue par le mainteneur** : la doc note explicitement le risque d'un schéma « si flexible qu'il devient impossible à maintenir » (`target_usage`, `selection`, `selection_rank` combinés).
- **Bugs récents concrets** : `UnboundLocalError` sur `media_auto_pause` + volume (#176), `Path` non sérialisable JSON en log recorder à chaque snapshot (#173), `ptz_delay` appliqué même sans PTZ (#172), validation de priorité trop stricte puis totalement relâchée (#39).
- **Design instable sur les cibles de groupe** : deux issues ouvertes de longue date sans conclusion (#9 label/area/zone/room, #10 transports n'expandant pas les groupes).
- **Demandes utilisateurs non couvertes** : notifier tous les appareils Companion sans config préalable (#21), combiner TTS + push (#13), rate limiting (roadmap TODO.md non implémenté), documentation jugée insuffisante (#20).

## 6. Idées à reprendre (clean room) / pièges à éviter

1. **Propager le `Context` HA de bout en bout** (context_id, parent_id, user_id) à travers routage → sortie `notify.*` → action liée, comme Supernotify le fait depuis v2.3.0 — utile pour tracer un acquittement Switchboard jusqu'à sa cause dans l'Activity view HA.
2. **Exposer chaque destinataire comme `NotifyEntity` appelable**, compatible `Notify Group` HA natif — à envisager en complément du service legacy `notify.switchboard_<target>`.
3. **Documenter une limite connue plutôt que la déguiser** (leur doc snooze : « pas de persistance pour l'instant ») — à l'inverse, tester réellement un redémarrage HA avant d'annoncer la persistance du `Store` Switchboard comme acquise.
4. **Piège — relâchement de validation par lassitude** : leur priorité stricte a cassé des configs (#39) puis a été totalement ouverte ; garder les 4 niveaux fermés côté Switchboard et rejeter explicitement une valeur invalide plutôt que l'accepter en silence.
5. **Piège — échec de mapping personne silencieux** : leur matching `context.user_id → person` en échec ne loggue qu'un warning invisible à l'utilisateur ; ne pas dégrader le `repairs`/log déjà prévu côté Switchboard pour un ack refusé.
6. **Piège — sur-configuration** : leur propre doc reconnaît le risque d'un schéma trop flexible ; le périmètre volontairement restreint de Switchboard (contrat gelé ADR-011) est une protection à ne pas éroder au fil des demandes.
7. **Piège — migrations cassantes en cours de bêta** : tester tout changement de schéma de config Switchboard avec une mise à jour à chaud, pas seulement une installation propre.
8. **Reprendre le principe de deliveries par défaut auto-créées** sans config (email/mobile_push/notify_entity chez eux) — transposable à un mode « zéro config » minimal pour un premier essai de Switchboard avant de remplir la table de routage.

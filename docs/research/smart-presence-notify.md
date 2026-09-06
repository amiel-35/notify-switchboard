# Analyse concurrente — `smart-presence-notify` (portbusy)

Dépôt : https://github.com/portbusy/smart-presence-notify
Analyse factuelle uniquement, sans copie de code. Comparé au contrat
[`docs/notify-switchboard-contract-v0.md`](../notify-switchboard-contract-v0.md).

## 1. Fiche d'identité

| Critère | Valeur |
|---|---|
| Licence | MIT |
| Étoiles / forks | 1 étoile, 0 fork, 1 watcher |
| Dernier commit / release | push le 31/08/2026 ; dernière release **v0.4.0** (16/07/2026) ; premier commit 27/04/2026 (~4 mois de vie) |
| Mainteneur | un seul auteur (`portbusy`), commits applicatifs signés par lui ; le reste de l'activité "issues" n'est que des PR Dependabot (mises à jour de dépendances) |
| Issues/PR ouvertes | 2, toutes deux des PR Dependabot — **aucune vraie issue utilisateur ouverte ou fermée** trouvée |
| HACS | Oui, en "custom repository" (pas encore dans le store par défaut) ; `hacs.json` déclare `homeassistant: 2026.1.0` comme version mini |
| Config | 100% UI (`config_flow: true`, `single_config_entry: true`) ; pas de YAML de configuration (seul `services.yaml` documente l'unique service) |
| Taille/maturité | petit dépôt (222 Ko), ~10 fichiers Python, tests présents (`tests/`, CI GitHub Actions) mais pas de doc au-delà du README |

## 2. Modèle fonctionnel

Le concept central est un **service unique** `smart_presence_notify.send` (pas un proxy `notify.*` par cible), avec une logique de routage **100% présence globale**, pas par personne :

- **Présence** : un seul coordinateur (`SmartPresenceNotifyCoordinator`) suit l'état agrégé — `someone_home` (bool) et `home_persons` (liste) — recalculé sur chaque changement d'état des `person.*` déclarés en config. Pas de règle "always/home_only/away_only" par personne : la présence ne sert qu'à décider "envoyer maintenant" vs "mettre en file".
- **Cibles** (`target_mode`, un seul mode actif pour toute l'intégration, pas par règle) :
  - `broadcast` : tous les présents reçoivent ;
  - `single_admin` : un seul `is_admin` désigné (ou le premier présent si l'admin est absent) ;
  - `caller_decides` : l'appelant fournit `targets: [notify.xxx, ...]` directement dans l'appel de service.
  - `target_override` : contournement total de la logique, appel direct d'un service `notify.*`.
- **Priorité** : deux valeurs seulement, `normal` / `high` (pas de `info/critical`). `high` ne "bypass" pas une notification silencieuse — il choisit une cible différente (le premier présent, ou le fallback, ou la file) et ajoute un `authenticationRequired` implicite via son propre mécanisme d'actions.
- **DND / horaires / silence par personne** : **absent**. Il n'y a ni `schedule`, ni `input_boolean`, ni notion de "personne silencieuse" — seule l'absence physique (personne à la maison) déclenche la mise en file.
- **File d'attente (queue)** : remplace le "snooze". Quand personne n'est à la maison, la notification est stockée (`Store` HA, persistant) avec `expires_at` optionnel (timeout configurable). Trois modes de vidage à l'arrivée du premier présent : `last_only`, `fifo` (avec un `sleep(1)` entre chaque envoi), `summary` (titre concaténé, sauf si des notifications actionnables sont dans le lot → repli FIFO).
- **Acquittement** : pas de lien avec `alert.turn_off`. Le seul mécanisme d'interaction est un préréglage **Oui/Non** (`response_preset: yes_no`) qui génère deux actions Companion App encodées (`SNP_YES_<nonce>.<base64(response_id)>` / `SNP_NO_...`), avec anti-duplication par nonce en mémoire (perdue au redémarrage HA, jusqu'à 256 nonces gardés) et ré-émission d'un événement custom `smart_presence_notify_response` (pas un service `alert.*`).
- **Persistance** : uniquement la file d'attente (`Store` versionné) ; aucune persistance des réponses/snoozes au-delà de la session HA.
- **Entités exposées** : `sensor.smart_presence_notify_queue_count`, `sensor.smart_presence_notify_last_sent`, `sensor.smart_presence_notify_home_persons`, `binary_sensor.smart_presence_notify_someone_home` — toutes globales à l'intégration, aucune par personne.

## 3. Tableau comparatif

| Fonction | smart-presence-notify | Switchboard v0 |
|---|---|---|
| Interface d'entrée | 1 service custom `smart_presence_notify.send` | services legacy `notify.switchboard_<target>` (+ entité `notify.switchboard`) |
| Granularité du routage | globale (1 mode de cible pour toute l'install) | par ligne de table de routage (audience, presence rule) |
| Présence par personne | présence agrégée "quelqu'un est là" | règle par personne : `always`/`home_only`/`away_only` |
| Silence / DND par personne | absent | `schedule`/`input_boolean` par personne, bypass si `critical` |
| Snooze | absent (remplacé par la queue globale) | snooze persistant par (personne × cible), avec expiry |
| Acquittement lié à une alerte | absent (pas de lien `alert.*`) | `alert.turn_off` sur la ligne, allow-list stricte |
| Priorités | 2 niveaux (`normal`/`high`) | 4 niveaux (`info/normal/high/critical`), `critical` bypass tout |
| File d'attente hors-présence | oui, 3 modes (last/fifo/summary), timeout + fallback | non prévu (le contrat privilégie drop tracé + observer mode) |
| Boutons Companion | Oui/Non génériques (réponse libre) | `acknowledge`/`snooze_<n>` liés à la ligne de routage |
| Observabilité des drops | aucune (pas de compteur "dropped", pas de raison) | `sensor.switchboard_dropped_today` + raisons (`silenced`, `snoozed`, `unknown_target`) |
| Mode "observer" sur `alert.*` | absent | prévu (ADR-007) |
| Config | 100% UI, une seule config entry | UI prévue (contrat ne détaille pas encore le flow) |
| Entités par personne | aucune | `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes` |

## 4. Interface avec `alert` / notify legacy / Companion

- **`alert` core** : aucune interaction. Le dépôt ne référence jamais `alert.*` ; ce n'est pas un routeur pour des alertes existantes mais un point d'entrée applicatif autonome.
- **Services `notify` legacy** : consommateur, pas fournisseur de cibles nommées — il appelle `notify.<xxx>` en sortie (`_async_call_service` fait un `split(".", 1)` générique), mais n'expose lui-même qu'un seul service d'entrée (`smart_presence_notify.send`), pas de `notify.smart_presence_notify_<target>` par cible.
- **`targets` HA standard** : non utilisé nativement ; réimplémenté à la main via le champ `targets` du service (liste de services notify complets, pas de slugs).
- **Callbacks Companion** : écoute `mobile_app_notification_action`, parse une regex propriétaire sur le champ `action`, ré-émet un event custom. Pas de lecture de `context.user_id`, pas d'allow-list de sécurité (contrairement au contrat Switchboard qui exige que l'alerte acquittée soit dans la table de routage).

## 5. Faiblesses visibles / demandes utilisateurs

- Aucune vraie remontée utilisateur exploitable : les 2 seules "issues" ouvertes sont des PR Dependabot de maintenance ; pas de discussion GitHub, pas de wiki rempli, pas de retours HACS visibles publiquement. Le produit semble très jeune (~4 mois, 1 étoile) et mono-mainteneur.
- Faiblesses de conception repérées à la lecture du code :
  - Pas de granularité par personne pour les règles de présence/priorité — un seul `target_mode` global peu adapté à un foyer aux besoins hétérogènes (contrairement à l'objectif affiché de Switchboard).
  - Pas de DND/horaires par personne : une notification "high" pendant la nuit réveille la première personne présente sans façon de l'exclure.
  - La déduplication des réponses Oui/Non est **en mémoire seulement** (`_answered_response_nonces`), perdue à chaque redémarrage HA — fragilité assumée et documentée dans le code, mais absente du README.
  - Pas de traçabilité des échecs de routage (aucun compteur "dropped", aucune raison structurée) — à l'opposé du choix explicite de Switchboard (ADR de ne "rien perdre silencieusement").
  - Le mode `summary` de la queue perd les boutons d'action dès qu'un item actionnable est mélangé à des items simples (repli sur FIFO) — compromis pragmatique mais non configurable.
  - Pas de mode "observer" sur une entité existante : toute alerte doit être réécrite pour appeler le service custom, ce qui casse la compatibilité avec des automatisations `alert:` déjà en place.

## 6. Idées à reprendre (clean room) / pièges à éviter

1. **Queue de repli avec timeout + fallback configurable** — mécanisme propre et simple (mode `discard` vs `notify_fallback`) à réutiliser côté Switchboard pour le cas "personne dispo mais canal en échec", en complément (pas en remplacement) de la logique de snooze/silence par personne.
2. **Trois modes de vidage de file (last/FIFO/summary) avec repli automatique FIFO si des items actionnables sont présents** — bonne heuristique anti-perte de boutons, à documenter explicitement si Switchboard introduit une notion de file.
3. **Design "push-only coordinator"** (`DataUpdateCoordinator` alimenté uniquement par `async_set_updated_data`, jamais par polling) — pattern HA propre pour exposer un état interne (compteurs, dernier envoi) sans job périodique inutile.
4. **Espacement `asyncio.sleep(1)` entre les envois FIFO groupés** — évite le rate-limiting/écrasement de notifications Companion App envoyées en rafale ; à valider aussi pour Switchboard s'il vide plusieurs sorties d'un coup.
5. **Piège à éviter — pas d'`alert.*` intégré** : ne pas suivre ce modèle "service applicatif isolé" ; le choix Switchboard de rester un vrai proxy `notify` legacy + interface `alert` est une différenciation réelle et délibérée, à assumer dans la doc de positionnement.
6. **Piège à éviter — anti-duplication en mémoire pure** : la protection anti-doublon des réponses Companion (nonce en RAM, perdu au restart) est un raccourci fragile ; Switchboard doit persister ack/snooze via `Store` dès la v0 (déjà prévu dans le contrat) plutôt que céder à la même simplification.
7. **Piège à éviter — regex propriétaire sur `action` sans allow-list de sécurité** : le parsing de l'action Companion ne vérifie ni l'origine, ni que la question posée existe encore ; le contrat Switchboard fait mieux en exigeant que l'alerte acquittée soit listée dans la table de routage — à ne pas relâcher.
8. **Piège à éviter — un seul mode de cible global** : la simplicité d'UX (un radio-bouton `target_mode` pour toute l'installation) a un coût de flexibilité ; conserver la table de routage par ligne (déjà dans le contrat v0) reste supérieur pour un foyer avec des besoins contrastés par personne/canal.

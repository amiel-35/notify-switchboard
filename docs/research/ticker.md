# Analyse factuelle — Ticker (analytix-energy-solutions/ticker)

Source : https://github.com/analytix-energy-solutions/ticker, issues (ouvertes +
fermées) via `gh api repos/analytix-energy-solutions/ticker/issues?state=all`,
README, USER_GUIDE.md, CHANGELOG (section « Version history » du README),
releases GitHub, et lecture du code sous `custom_components/ticker/` (const.py,
notify.py, user_notify.py, config_flow.py, conditions.py, store_queue.py,
discovery.py, `__init__.py`). Aucun code copié ; seules les signatures,
constantes et logiques sont décrites pour comparaison.

## 1. Fiche d'identité

| Critère | Valeur |
|---|---|
| Licence | Apache-2.0 depuis v1.7.0 (18/05/2026) ; v1.0.0→v1.6.2 étaient en GPL-3.0, toujours disponibles sous cette licence |
| Étoiles | 170 |
| Forks | 11 |
| Créé | 02/03/2026 |
| Dernier commit (push) | 26/07/2026 |
| Releases | 21 tags du 04/03/2026 (v1.0.0) au 14/07/2026 (v1.8.2), cadence très soutenue (plusieurs sorties/mois, dont des betas publiques) |
| HACS default | Ajouté le 11/05/2026 (PR hacs/default#6189 mergée), soit ~2 mois après le premier commit et avant même v1.6.0 |
| Config | 100% UI. Le `config_flow.py` ne fait que créer une entry vide, instance unique (`_abort_if_unique_id_configured`) ; toute la configuration réelle (catégories, utilisateurs, conditions, recipients) se fait via deux panels custom (admin + utilisateur) pilotés par websocket, pas par options flow HA classique. Pas de YAML. |
| HA minimale | Non déclarée explicitement : ni `hacs.json` ni `manifest.json` ne portent de `homeassistant`/`min_ha_version`. Une seule contrainte de fait : usage de `MediaPlayerEntityFeature.MEDIA_ANNOUNCE` (2024.1+) et de `NotifyEntity` (plateforme notify moderne). |
| Taille du code | 56 fichiers Python + 35 fichiers JS (frontend des deux panels) sous `custom_components/ticker/`, 79 fichiers de tests. Taille du dépôt (API GitHub, base git) : ~1,28 Mo. Le README revendique explicitement un refactor pour garder « all files under 500 lines » (v1.2.0). |

## 2. Issues

39 issues au total (hors PR), classées ci-dessous (B=bug, D=demande, Q=question, R=refus/différé).

| # | Date | État | Titre | Catégorie | Résumé | Réponse mainteneur |
|---|---|---|---|---|---|---|
| 1 | 05/03 | fermée | `[object Object]` affiché pour les notify services (Users) | B | bug d'affichage front | corrigé (commit direct) |
| 2 | 05/03 | fermée | History ne montre pas le device cible | D | manque d'info dans l'historique | corrigé (commit direct) |
| 5 | 19/03 | fermée | Échec si le mobile ID a changé | B | slug `notify.mobile_app_*` figé à l'enregistrement, pas de rename côté HA | corrigé v1.3.0 (discovery réécrite sur device registry) |
| 7 | 20/03 | fermée | Notify au-delà de mobile_app (navigateur, Signal, Apprise) | D | demande de canaux génériques | accepté partiellement → Device recipients v1.4.0 ; **Apprise explicitement refusé** (« deviate tremendously from the core of Ticker ») |
| 8 | 20/03 | fermée | Erreur en passant un groupe en conditionnel | B | bug UI | corrigé PR #10 |
| 13 | 27/03 | fermée | Override par appel des action sets / smart delivery | D | dette de design signalée par le mainteneur lui-même | corrigé PR #17 (`action_set_id`) |
| 14 | 27/03 | **ouverte** | Support russe / i18n | D | localisation | **refusé/différé** : « no plans for real localization yet, project of itself » |
| 15 | 01/04 | fermée | Image perdue dans la notification | B | régression envoi image | corrigé v1.5.0, puis **réouvert** (perte d'image spécifique à la migration wizard) |
| 16 | 03/04 | fermée | Tri des logs | D | ergonomie admin | livré v1.6.0 |
| 19 | 04/04 | fermée | Copie YAML plante (`writeText` undefined) | B | crash dans l'app Companion / contexte non-HTTPS | corrigé v1.5.1 |
| 21 | 05/04 | fermée | Erreur dictionnaire à la création du 1er device | B | crash si `conditions` vide | hotfix v1.5.2 |
| 22 | 05/04 | fermée | Lier un device à un utilisateur | D | device-user link | livré v1.8.0 (F-39), après réflexion UX explicite (« keep the boss UI clean ») |
| 24 | 05/04 | fermée | Notifier plusieurs catégories en un appel | D | fan-out multi-catégories | livré v1.6.0 |
| 25 | 06/04 | fermée | Impossible de fixer "persistent" en mode Smart | B | bug UI catégorie | livré v1.6.0 |
| 26 | 09/04 | fermée | Ticker comme "device" HA | D | visibilité blueprint | livré v1.6.0, **mais** un utilisateur signale ensuite que la catégorie ne peut pas être passée depuis un blueprint device target (limite documentée : « device-action support deferred ») |
| 27 | 09/04 | fermée | Purger l'historique | D | gestion des logs | livré v1.6.0 |
| 28 | 10/04 | fermée | Alertes sur des valeurs de date | Q | confusion de périmètre | réponse pédagogique : Ticker route, ne déclenche pas — faire l'automatisation à côté et appeler `ticker.notify` |
| 29 | 12/04 | fermée | Migration casse les liens d'image | B | bug migration wizard | corrigé v1.6.0 (BUG-103) |
| 30 | 12/04 | fermée | Graphique manquant | B | faux positif (rafraîchissement) | fermé sans code |
| 31 | 13/04 | fermée | Plus d'états pour les conditions d'entité | D | UX conditions | partiel v1.7.0 ; **limite assumée** : peupler depuis les états observés jugé « infeasible at run-time » |
| 32 | 15/04 | fermée | Opérateur NOT sur une zone | D | conditions | livré v1.7.0 |
| 33 | 16/04 | **ouverte** | Gérer les abonnements depuis la vue catégorie | D | doublon d'UI perçu | **réserve du mainteneur** : crainte de clutter, demande de cas d'usage précis, reste sans suite |
| 35 | 25/04 | fermée | Son avant la TTS | D | chime pré-TTS | livré v1.7.0 |
| 36 | 27/04 | **ouverte** | Préfixe de titre par catégorie | D | personnalisation | accepté, récupéré par un contributeur externe ; le mainteneur généralise vers un futur « Category Notification Templates », reste ouvert |
| 37 | 08/05 | fermée | Nettoyage des devices obsolètes (doublons) | B | discovery : 2 chemins (entity/device registry) produisant des doublons | fix v1.6.1 (dédup post-merge), **réouvert** une fois pour un cas résiduel puis refermé sans cause claire identifiée |
| 38 | 12/05 | fermée | App Companion "prise en otage" par le panel Ticker | B | UX mobile, pas de sortie du panel | corrigé v1.8.0 (lié à #43/#51) |
| 42 | 15/05 | **ouverte** | Override email par abonnement (SMTP) | D | intégration tierce | mainteneur hésitant (« keeping Ticker away from weaving too far with other integrations ») ; l'utilisateur finit par **coder sa propre intégration séparée** (Email-Notify-Manager) — refus de fait |
| 43 | 21/05 | fermée | Ticker bloque la navigation dans l'app iPhone | B | UX mobile grave | corrigé v1.8.0 (#52, bouton hamburger) |
| 44 | 21/05 | **ouverte** | Un device notify par catégorie | D | routage fin par device | « let me look into it » puis silence ; PR pendante depuis mi-juillet sans suite (relance utilisateur sans réponse) |
| 45 | 24/05 | **ouverte** | Bug "Test Notification" (TTS) | B | pas de sélection du service TTS réel | aucune réponse mainteneur |
| 46 | 24/05 | fermée | Impossible d'éditer une catégorie après création | B | schéma de validation rejette `android_channel` | bug majeur, plusieurs utilisateurs bloqués sur du CRUD de base ; corrigé v1.8.0 via **PR communautaire** (#55, @jesfer) |
| 47 | 27/05 | **ouverte** | Passer des données à un script | D | — | 0 commentaire, aucune réponse |
| 48 | 10/06 | **ouverte** | "Functionality request" (générique) | D | — | réponse générique renvoyant vers l'absence de plans i18n court terme |
| 51 | 02/07 | fermée | Bouton hamburger absent en portrait mobile | B | UX mobile | corrigé via PR communautaire (#52, @danswett) |
| 53 | 02/07 | fermée | Deep-link `#history` ignoré au remount | B | navigation | corrigé via PR communautaire (#54, @danswett) |
| 56 | 05/07 | fermée | Panels admin/user en écran blanc | B | régression d'un refactor (BUG-111) | identifié par un utilisateur (revert d'un commit précis), corrigé en hotfix |
| 62 | 11/07 | **ouverte** | Exposer tous les paramètres `ticker.notify` en attributs de capteur | D | — | aucune réponse |
| 65 | 17/08 | **ouverte** | Délai long avant délivrance | B | latence de délivrance non expliquée | pas de diagnostic public, relance utilisateur sans réponse (30/08) |
| 67 | 30/08 | **ouverte** | Recipients TTS via Assist Satellite natif | D | — | aucune réponse (issue récente) |

### Synthèse — 10 douleurs/demandes les plus fréquentes

1. **Instabilité de la découverte des devices notify** : slugs `mobile_app_*` figés au renommage, doublons entre chemin entity-registry et device-registry (#5, #37).
2. **UX mobile cassée par les panels custom** : app Companion piégée sur le panel Ticker, pas de retour vers la sidebar HA, hamburger manquant en portrait (#38, #43, #51) — 3 issues distinctes pour le même défaut structurel des custom panels.
3. **Fragilité du schéma de validation des catégories** : un champ ajouté (`android_channel`) casse la sauvegarde de toutes les catégories existantes, bug bloquant pour plusieurs utilisateurs simultanément (#46).
4. **Migration wizard peu fiable** : plantage clipboard hors HTTPS/app Companion (#19), perte des liens image lors de la conversion (#15, #29).
5. **Moteur de conditions avec angles morts** : crash sur conditions vides (#21), bug de matching de zone par chaîne plutôt que par appartenance (documenté en interne comme BUG-102), impossibilité de peupler dynamiquement les valeurs d'état.
6. **Demandes récurrentes de canaux au-delà de mobile_app** (navigateur, Signal, Apprise, SMTP dédié) — direction assumée : ajouter des "device recipients" internes plutôt que devenir un bridge générique ; Apprise et l'intégration SMTP fine explicitement écartés.
7. **i18n/localisation demandée à plusieurs reprises**, toujours répondue par un report indéfini faute de ressources.
8. **Intégration blueprint/device incomplète** : Ticker s'enregistre comme device HA pour la découverte mais ne permet pas de faire transiter la catégorie depuis un blueprint device target — limitation documentée comme différée.
9. **Configuration TTS partielle** : pas de sélection du service TTS réel dans le test, et une mécanique de synchronisation chime/TTS bâtie sur des délais fixes empiriques (constantes `CHIME_TTS_GAP`, silence pré-pendu dans les fichiers audio pour contourner un bug Chromecast) plutôt que sur un événement fiable.
10. **Questions de performance/latence sans réponse publique** (#65) et un mainteneur qui, à l'inverse, exprime lui-même la crainte de la sur-complexité de l'UI en refusant d'ajouter des vues redondantes (#33).

## 3. Modèle de données

- **Abonnement** = triplet (person_id, category_id) → `mode` ∈ {always, never, conditional}, `set_by` ∈ {user, admin, orphan_fallback}. Pas de granularité par canal : un abonnement conditionne toute la catégorie pour cette personne.
- **Catégorie** : id, nom, mode par défaut, `action_set_id`, `smart_notification` (groupe/tag/sticky/persistent), `android_channel`, `navigate_to`, `expose_in_sensor`, overrides chime/volume. Pas de notion de "priorité" par catégorie — seul un flag `critical` booléen passé par appel.
- **Personnes** vs **Recipients** : les personnes (`STORAGE_KEY_USERS`) sont liées à des `person.*` HA ; les "recipients" (`STORAGE_KEY_RECIPIENTS`, F-18) sont des devices non-personnels (TV, tablette) avec `device_type` ∈ {push, tts}, pouvant être "liés" à une personne (F-39 `user_link`) pour hériter de ses abonnements tout en gardant conditions/chime/volume locaux.
- **Canaux/sorties** : découverte dynamique des `notify.*` par personne via device/entity registry (`discovery.py`), format auto-détecté (rich/plain/persistent) par motif de nom de service, TTS via `media_player.*`.
- **Priorité** : binaire (`critical: true/false`), pas d'échelle info/normal/high/critical.
- **Présence/conditions** : arbre AND/OR profondeur max 2 (`condition_tree`, F-2b) avec 3 types de règles — `zone` (matching par appartenance à `zone.attributes["persons"]`, corrigé après un bug de comparaison de chaînes), `time` (fenêtre after/before, jours ISO, fenêtres nocturnes), `state` (état d'entité). Opérateur NOT togglable par règle ou par groupe (v1.7.0). Format `rules[]` legacy conservé en fallback avec migration automatique.
- **DND/horaires** : pas de primitive dédiée — c'est une règle `time` du même moteur de conditions que la présence, avec `queue_until_met`/`deliver_when_met` pour décider entre envoi différé (queue) et abandon (skip).
- **Snooze** : store dédié (`STORAGE_KEY_SNOOZES`) par (person, category), durées fixes 15/30/60/120/240 min, déclenché uniquement via bouton d'action sur une notification livrée ; check pré-envoi qui droppe et logue `outcome=snoozed`.
- **Acquittement** : boutons d'action typés `script | snooze | dismiss` (F-5), rappelés via callback `mobile_app_notification_action` (`actions.py`). Aucun lien avec l'entité core `alert.*` de Home Assistant — Ticker ignore complètement ce domaine ; un "dismiss" n'appelle rien côté HA, il logue seulement l'action prise dans l'historique.
- **Dedupe/regroupement** : `smart_tag_mode` (none/category/title) pour le tag/replace côté OS, plus `clear_when` (F-30) qui enregistre un listener one-shot (state ou event) pour appeler automatiquement `ticker.clear_notification` — ces listeners ne survivent pas à un redémarrage HA (limite documentée).
- **Persistance** : `homeassistant.helpers.storage.Store` séparé par domaine (categories, subscriptions, users, queue, logs, snoozes, recipients, action_sets), `STORAGE_VERSION = 1`.
- **Templates** : "Action Sets Library" (F-5b) — jeux de boutons réutilisables (max 3), référencés par ID depuis une catégorie ou surchargés par appel (`action_set_id`).

## 4. Interface d'exposition

- **Pas d'intégration avec l'entité core `alert`** : aucune mention de `alert.turn_off` ni de consommation d'un `alert.*` dans le code inspecté (const.py, user_notify.py, recipient_notify.py, conditions.py, `__init__.py`).
- **Pas de `targets` legacy / pas de services par cible** : un seul point d'entrée métier, le service custom `ticker.notify` (domaine `ticker`, schéma riche : category — scalaire ou liste —, title, message, data, expiration, critical, navigate_to, clear_when, action_set_id, suppress_actions). En complément, une plateforme `notify` minimaliste (`notify.py`) enregistre une **unique** `NotifyEntity` nommée "Ticker" (`notify.ticker`) qui ne fait que retraduire `message/title/data.category` vers un appel à `ticker.notify` — présente uniquement pour la découvrabilité par Alarmo/blueprints, pas pour un routage par cible.
- **Callbacks Companion** : oui, `actions.py` installe un listener d'actions de notification (probablement sur l'event `mobile_app_notification_action` au vu de l'`ACTION_ID_PREFIX = "TICKER_"` et de l'architecture F-5) pour router script/snooze/dismiss.
- **Événements** : pas d'entité `event.*` dédiée comme point d'observation externe ; la traçabilité passe par les Stores internes (logs, historique) exposés via websocket aux deux panels, plus des capteurs `sensor.ticker_<category>` par catégorie pour Lovelace.
- **Device registry** : Ticker s'enregistre lui-même comme un device HA (`entry_type=service`, F-31) pour apparaître dans les sélecteurs de device des blueprints — visibilité seulement, pas d'action device exposée (limite documentée).

## 5. Fonction par fonction — Ticker vs Switchboard v0

| Fonction | Ticker | Switchboard v0 |
|---|---|---|
| Service d'entrée | `ticker.notify` (domaine custom, schéma riche) + `notify.ticker` (bridge minimal) | `notify.switchboard` + `notify.switchboard_<target>` (legacy `targets`) |
| Config | 100% UI, panels custom (websocket) | Config UI également, mais routage déclaratif par table (rows), pas deux panels applicatifs |
| Granularité de l'abonnement | par (personne, catégorie) — tout ou rien par catégorie | par (personne, cible) via présence/silence/snooze indépendants |
| Présence | règle `zone` dans le moteur de conditions, opt-in par abonnement conditionnel | règle native `always / home_only / away_only` évaluée systématiquement dans le pipeline de routage |
| Silence/DND | fenêtre horaire = une règle `time` parmi d'autres, pas de concept "silence" séparé | `schedule`/`input_boolean` dédiés par personne, concept de première classe |
| Priorité | booléen `critical` uniquement | échelle info/normal/high/critical, seul `critical` bypass le silence — logique proche mais Ticker n'a pas les paliers intermédiaires |
| Snooze | par (personne, catégorie), durées fixes, déclenché par bouton | par (personne, cible), avec expiry, persistant (`Store`), déclenché par callback snooze |
| Acquittement | "dismiss" = log interne uniquement, aucun lien avec `alert.*` | `alert.turn_off` explicite, avec allow-list de sécurité sur l'`alert.*` de la ligne de routage |
| Intégration `alert` core | **absente** | **contrat central** (ADR-007 observer mode inclus) |
| Dedupe/replace | tag OS-level (`smart_tag_mode`) + `clear_when` (non persistant au restart) | `tag` passé tel quel en `data`, pas de mécanisme de clear automatique dans le contrat v0 |
| Sortie multi-cible | fan-out par device/service découverts, en parallèle (`asyncio.gather`) | fan-out par `notify.*` output configuré par personne, erreurs isolées (contrat identique en esprit) |
| Anti-récursion | non documentée dans le code lu | rejet explicite si un output résout vers `notify.switchboard*`, au config-time et au runtime |
| Boutons/callbacks | Action Sets (script/snooze/dismiss), jusqu'à 3 boutons, listener `mobile_app_notification_action` | boutons `acknowledge`/`snooze_<minutes>` générés depuis la ligne de routage, même mécanisme de callback |
| Mode observateur (plan B) | absent | présent (ADR-007), écoute directe d'un `alert.*` sans figurer dans `notifiers` |
| Persistance | multiples `Store` HA par domaine de données | `Store` pour les snoozes (a minima, selon contrat) |
| Événements/observabilité | logs internes + websocket + sensors par catégorie | `event.switchboard_delivery` avec `event_types` fixes (routed/dropped/acknowledged/snoozed) — plus adapté à l'automatisation externe |
| Entités par personne | aucune entité HA par personne (tout est dans le Store + panels) | `binary_sensor.<person>_silenced`, `sensor.<person>_last_notification`, `sensor.<person>_active_snoozes` |
| Canaux hors mobile_app | devices "recipients" internes (push/TTS), refus d'Apprise/bridge générique | n'importe quel `notify.*` existant, sans device model propre — plus simple mais moins riche (pas de chime/volume/TTS géré) |
| i18n | demandé, jamais livré | labels de boutons via traductions HA natives (`common.*`) — approche plus légère et déjà couverte par le contrat |
| UI de configuration | 2 panels custom (sidebar) | non spécifié dans le contrat — a priori options flow HA standard |

Ce que Ticker fait et que Switchboard v0 ne fait pas : device recipients dédiés (TV/tablette) avec TTS+chime+volume, historique/queue avec panels dédiés, action sets réutilisables, conditions AND/OR à deux niveaux avec NOT, migration wizard depuis automatisations existantes, capteurs par catégorie pour dashboards, multi-catégorie par appel.

Ce que Switchboard v0 fait et que Ticker ne fait pas : intégration native avec l'entité core `alert` (y compris acquittement réel et mode observateur), échelle de priorité à 4 paliers avec bypass, séparation nette silence/snooze/présence comme primitives de premier ordre, entités per-person exploitables ailleurs dans HA (binary_sensor/sensor), garde-fou anti-récursion explicite, modèle d'événement structuré pour l'automatisation externe.

## 6. Positionnement

Ticker est une plateforme de notification complète (UI, historique, devices, TTS, migration) construite comme un sous-système applicatif propre avec son propre stockage et ses propres panels — c'est un produit, pas une brique de routage. Switchboard v0 est délibérément plus étroit : un proxy `notify` pur qui s'interface avec le primitif core `alert` déjà présent dans HA, sans réinventer catégories/historique/UI. Les issues de Ticker montrent que sa surface large a un coût direct : bugs de schéma qui cassent la sauvegarde de configuration existante (#46), UX mobile cassée par les panels custom à trois reprises (#38/#43/#51), et un mainteneur qui refuse ou diffère des demandes précisément par crainte de complexité (#33, #42, i18n). Le choix de Switchboard de rester un routeur `notify` avec `alert.turn_off` en sortie évite cette classe de problèmes — pas de panel custom à maintenir, pas de wizard de migration fragile, pas de schéma de stockage à faire évoluer sans casser l'existant. En contrepartie, Switchboard n'offre aucune des fonctions "produit" (historique visuel, devices TTS/chime, action sets) que des utilisateurs de Ticker réclament et obtiennent au fil des releases ; le contrat v0 n'a pas vocation à couvrir ce terrain, et rien dans les issues de Ticker ne remet en cause la pertinence du couple présence/silence/snooze/ack déjà prévu dans le contrat.

## 7. Idées à reprendre / pièges à éviter

**À reprendre (clean room, principe seulement) :**
1. Fan-out des sorties en parallèle (`asyncio.gather` avec `return_exceptions=True`) plutôt que séquentiel — Switchboard devrait faire de même pour ne pas faire attendre une personne à cause d'un `notify.*` lent.
2. Timeout explicite par appel de service de sortie (30 s chez Ticker) pour éviter qu'une intégration tierce bloque tout le routage.
3. Détection automatique du format de payload par plateforme (iOS forcé en "plain" même si détecté "rich" par device registry) — un bug corrigé une fois (BUG-061) qui vaut d'être anticipé si Switchboard enrichit un jour ses payloads.
4. Matching de zone/présence par appartenance à un attribut de liste (`zone.attributes["persons"]`) plutôt que par comparaison de chaîne d'état — Ticker a dû corriger cela après coup (BUG-102), Switchboard peut l'avoir juste dès le départ pour `person.*`.
5. Log explicite de chaque notification "expirée avant délivrance" plutôt qu'une simple suppression silencieuse — cohérent avec le principe déjà affirmé dans le contrat Switchboard ("nothing is silently lost").
6. Sanitisation stricte de tout champ qui finit dans une navigation ou une URL (le fix Ticker sur `navigate_to` rejette `https://`, `javascript:`, `//`) — à appliquer à tout champ similaire si Switchboard en introduit un jour.
7. Ne jamais dépendre d'un listener HA qui ne survit pas au redémarrage pour une garantie fonctionnelle (le `clear_when` de Ticker perd ses listeners au restart, documenté comme limitation) — le contrat Switchboard précise déjà que les snoozes sont persistés via `Store`, à vérifier que ce soit vrai de tout mécanisme équivalent.
8. Un dédoublonnage post-fusion par identifiant stable (`device_id`) quand deux chemins de découverte peuvent produire le même service sous deux formes — pertinent si Switchboard enrichit un jour sa résolution de `notify.*` par personne au-delà d'une liste déclarée en config.

**Pièges à éviter (tirés directement des issues) :**
1. Ne pas construire de panel(s) custom pour la configuration si un simple config/options flow HA standard suffit : trois issues distinctes (#38, #43, #51) viennent uniquement du fait que les panels custom de Ticker cassent la navigation native de l'app Companion. Switchboard, configurable en options flow standard, n'a structurellement pas ce risque — le garder ainsi.
2. Ne pas faire dépendre la validation de sauvegarde d'un schéma qui peut diverger entre ce qui est affiché et ce qui est accepté en update (#46 a bloqué la modification de catégories pour plusieurs utilisateurs simultanément à cause d'un champ ajouté sans mettre à jour le schéma de validation correspondant) — tout ajout de champ optionnel au contrat Switchboard doit être testé en écriture ET en relecture/édition.
3. Ne pas promettre une portée d'intégration tierce (Apprise, SMTP fin, bridges génériques) sans l'assumer explicitement dans le contrat — Ticker a dû refuser ces demandes après coup, générant de la frustration visible et un contournement par un fork utilisateur (#42). Le contrat Switchboard l'anticipe déjà ("outputs are whatever notify.* services exist"), à ne pas dévier de ce principe si une demande similaire arrive.

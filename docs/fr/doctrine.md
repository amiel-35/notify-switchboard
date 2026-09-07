# Doctrine — Suite de notifications pour Home Assistant

> **Version 0.2** (06/09/2026, 23h30) — v0.1 relue par un agent Opus à contexte
> vierge (verdict : go avec corrections) et recoupée avec l'état de l'art
> (`docs/etat-de-l-art-notifications-ha-2026-09-06.md`). Les corrections sont
> intégrées ; les ADR 007-013 tracent ce qui a changé. Décisions du mainteneur du
> 06/09 : dépôts publics, MIT, code/doc en anglais avec interface fr/es, HA de
> dev en Docker, sprints = incréments fonctionnels testables, autonomie totale
> de la session donneuse d'ordre.

## 1. Pourquoi

Dans la maison de référence : 28 alertes, 27 adresses câblées en dur vers un seul iPhone, deux
designs concurrents pour un même besoin, aucune règle « qui / quand /
présence », et des alertes qui meurent en silence quand leur capteur tombe
(KLIPPBOK, 06/09).

Le trou est générique, confirmé par l'état de l'art : HA fournit les briques
(`alert`, `event`, `person`, `schedule`, `notify`) mais **aucun proxy `notify`
transparent configurable en UI**, aucun couplage `alert.*` ↔ acquittement,
aucun snooze personne × alerte persistant, et **aucun `notify` qui parle sur
Cast ou AirPlay**. Les routeurs existants (Ticker, Supernotify, Universal
Notifier, ANS, Notifier Hub) ont chacun leur propre service et leur propre
moteur ; aucun ne complète `alert`, tous le remplacent ou l'ignorent.

> **Correction (07/09/2026).** La dernière affirmation ci-dessus est fausse :
> core fournit déjà un `notify` qui parle, la plateforme legacy `platform:
> tts` (`homeassistant/components/tts/notify.py`, vérifié sur le clone core
> 2026.9.1) — `entity_id` (un moteur `tts.*`, ou l'ancien `tts_service`) plus
> `media_player` comme cible. Visée sur un lecteur Music Assistant, l'annonce
> met la musique en pause puis la reprend ; visée sur un lecteur Cast brut,
> elle l'interrompt sans reprise. Conséquence : les dépôts sœurs Cast
> Notifier et AirPlay Notifier sont largement redondants avec ce que core
> fait déjà (leur mainteneur les archive) ; seul Assist Satellite Notifier
> couvre un vrai trou, `assist_satellite` n'ayant aucune plateforme `notify`.
> On ne réécrit pas le paragraphe ci-dessus pour préserver l'historique de la
> décision — cette correction le remplace en pratique.

## 2. Principes

1. **Natif d'abord.** `alert` porte l'état et le cycle de vie (répétition,
   acquittement, retour à la normale) ; `event` porte les faits ponctuels ;
   `person` porte la présence ; `schedule` / `input_boolean` portent les plages
   de silence et le DND — **le routeur les lit, il ne les possède pas** ;
   `notify` est le contrat d'entrée et de sortie.
2. **Deux natures, pas trois.** *Persistant* = un état qui dure jusqu'à ce que
   quelque chose le change → une `alert`. *Information* = un fait ponctuel →
   un événement / un `notify` direct. Urgence, destinataire, droit de
   réveiller sont des **attributs**.
3. **Un proxy, pas un canal.** Le routeur n'envoie rien lui-même ; il appelle
   des `notify.*` existants. Aucun appel réseau sortant, aucune dépendance
   externe.
4. **La voix est un adaptateur séparé.** Les adaptateurs voix sont des
   `notify.*` autonomes, pour des *informations* choisies. Ce principe est
   **une règle de configuration documentée**, pas une garantie du code : rien
   n'empêche techniquement de lister un adaptateur voix dans une `alert`
   (ADR-010). Dans la maison de référence, la voix n'est pas un canal d'alerte.
5. **Sécurité et voix.** Recommandation forte documentée : ne jamais faire
   parler un texte dérivé d'un `alarm_control_panel.*` ou d'un `lock.*`. Le
   routeur reçoit une chaîne déjà rendue et ne peut pas le garantir ; les
   adaptateurs voix offrent une deny-list optionnelle sur `data.source_entity`
   quand il est fourni (ADR-010).
6. **Générique et configurable.** Rien de spécifique à la maison de référence dans
   le code. Les classes (`building`, `pets`…) sont des **exemples de doc**,
   jamais des constantes.
7. **Chaque dépôt vit seul.** Contrats entre eux = ceux de HA.
8. **Rien sur l'instance de production avant validation.** Dev et tests sur l'instance HA
   jetable du serveur de dev ; déploiement dans la maison de référence = chantier HA-Familly, avec
   l'accord du mainteneur, après release.
9. **Clean room.** Notifier Hub est GPL-3.0 : **aucune ligne** n'en est
   reprise. Inspiration d'idées seulement (`confirmation`, `escalate`). Idem
   pour tout dépôt non MIT/Apache/BSD.

## 3. Architecture et contrats

### 3.1 Socle `notify` (ADR-007)

- **Entrée principale = service `notify` legacy** (`BaseNotificationService`)
  — la seule forme que `alert.notifiers` sait appeler (core#164855 : migrer
  vers `NotifyEntity` casse `alert`). `alert` est **gelé** côté HA (sept.
  2025) : ce socle est stable mais sans avenir garanti.
- La propriété **`targets`** du service legacy engendre un service par cible :
  `notify.switchboard_<cible>`. Chaque cible est une **ligne de la table de
  routage** configurée en UI : elle porte la classe, la priorité par défaut,
  l'`alert.*` associée (facultative) et les personnes concernées. C'est ainsi
  qu'une `alert` — dont `data` est statique et non templatable — dit au
  routeur *qui elle est* : elle liste `switchboard_fuite_eau` dans ses
  `notifiers`. Aucune donnée à faire transiter.
- **`NotifyEntity` exposée en plus**, documentée comme **dégradée** : message
  + titre seulement (l'API n'a ni `target` ni `data`, issue #3684 ouverte) →
  routage avec la classe par défaut, priorité `normal`.
- **Plan B écrit** (si HA retire le legacy) : le routeur écoute directement
  les transitions d'état des `alert.*` référencées dans sa table
  (`on` → route, `idle` → done, `off` → silence) et n'a plus besoin d'être
  notifier. Cette écoute est **implémentée dès la v0.1 en option** (`mode:
  observer`), ce qui rend le plan B testé et non théorique.

### 3.2 Flux

```
   état qui dure                      fait ponctuel
        │                                  │
  binary_sensor.*                    event.* / automation
        │                                  │
     alert.* ─ notifiers: [switchboard_<cible>] ─►  notify.switchboard_<cible>   ◄─ notify.send_message
  (repeat, ack, done)        (ou mode observer : écoute de alert.*)     │           (entité, dégradé)
                                                                        ▼
                                   table de routage : cible → classe, priorité, alert.*, personnes
                                                                        │ par personne :
                                                                        │  concernée ? présente si requis ?
                                                                        │  silence (schedule/input_boolean lus) ?
                                                                        │  priorité qui lève ? snooze actif ?
                                                                        ▼
        notify.mobile_app_<personne> (Companion)   notify.persistent_notification   [notify.<voix>, par config]
                          │
             action « Vu » / « Snooze » ──► routeur ──► alert.turn_off (allow-list) / report
```

### 3.3 Contrat d'entrée (gelé par `contract.md` + test de contrat, ADR-011)

- `message`, `title` : texte, transmis tels quels.
- `target` (legacy) : nom(s) de cible(s) de la table ; absent → cible par défaut.
- `data.priority` : `info` | `normal` | `high` | `critical` (surcharge la cible).
  Seul `critical` lève un silence.
- `data.source_entity` : facultatif, entité d'origine (pour les deny-lists voix
  et les diagnostics).
- `data.*` restant (`tag`, `url`, `push`, `actions`, `image`…) : **fusionné**
  avec ce que la cible définit (routeur < appelant) et transmis aux sorties.
- **Noms publics gelés à la 1.0** : le domaine `notify_switchboard`, le service
  `notify.switchboard`, le schéma `notify.switchboard_<cible>`, les clés
  `data.*` ci-dessus. Les renommer casse toutes les `alert:` des utilisateurs.

### 3.4 Contrat de sortie

Appel des `notify.*` configurés pour chaque personne retenue, avec `message`,
`title`, `data` fusionné + boutons du routeur. Une sortie qui lève une
exception n'empêche pas les autres (journalisée, `repairs` si récurrent).
Cibles absentes au démarrage : tolérées et réessayées (ordre de chargement) ;
cibles disparues : `repairs`. **Récursion interdite** : une sortie pointant
sur `notify.switchboard*` est refusée au config flow et au runtime.

### 3.5 Entités exposées

Par personne (unique_id = `entry_id` + `entity_id` de la `person`, jamais un
nom d'affichage) : `binary_sensor.<p>_silenced` (silence effectif calculé),
`sensor.<p>_last_notification`, `sensor.<p>_active_snoozes`. Globales :
`sensor.switchboard_routed_today`, `sensor.switchboard_dropped_today`
(attributs : raisons), `event.switchboard_delivery` (types fixes : `routed`,
`dropped`, `acknowledged`, `snoozed` ; ce n'est pas un journal — l'historique
est celui du recorder). `diagnostics.py` avec `async_redact_data` sur les
corps de messages. Snoozes persistés via `Store` (survivent au redémarrage).

### 3.6 Acquittement et snooze (ADR-008, ADR-009)

- Boutons ajoutés par le routeur aux sorties Companion : « Acknowledge »,
  « Snooze 1 h », etc., libellés **traduits via `async_get_translations`**
  dans la langue de HA (les fichiers `translations/` ne couvrent pas le texte
  routé ; on les étend d'une section `common`).
- Réception : événement `mobile_app_notification_action`. Le routeur :
  n'acquitte qu'une `alert.*` **présente dans sa table** (allow-list), journalise
  `context.user_id`, refuse tout identifiant hors table.
- `authenticationRequired: true` **par défaut** pour toute cible de priorité
  `high`/`critical` (pas d'action depuis l'écran verrouillé).
- Snooze : par personne × cible, durées et bornes définies par la cible (une
  cible peut interdire le snooze et/ou l'acquittement) ; report de nuit à
  l'heure de fin de silence de la personne. Fuseau : celui de HA ; tests
  traversant minuit et un changement d'heure obligatoires.
- Rafales : dédoublonnage par `tag` + fenêtre configurable par cible.

## 4. Dépôts

| Rôle | Nom | Contenu |
|---|---|---|
| Routeur (+ parapluie) | **Notify Switchboard** — `amiel-35/notify-switchboard`, domaine `notify_switchboard` | intégration ; `docs/` porte doctrine (EN), ADR, contract.md, blueprints, exemples |
| Voix Cast | **Cast Notifier** — `cast-notifier`, domaine `cast_notifier` (ADR-014 : « Google Home Notifier » écarté, nom déjà porté par un projet Node de 574 ★ au même usage) | plateforme `notify` legacy + entité qui parle sur Cast (`tts.speak`, volume restauré, langue, deny-list `alarm_control_panel`/`lock` sur `data.source_entity`) |
| Voix AirPlay | **AirPlay Notifier** — `airplay-notifier` | idem via Music Assistant si présent, sinon lecteur AirPlay HA |
| Voix Alexa | **Alexa Notifier** — reporté | **Alexa Devices** (core) expose déjà des entités notify Speak/Announce ; à ne faire que si un besoin non couvert apparaît |
| Cartes | `notify-switchboard-cards` | bulle sur `alert.*`, tuiles de silence par personne |

Décision du mainteneur : les adaptateurs restent **indépendants et séparés** (un
dépôt chacun), même si le contrat est identique — un backend commun partagé
en code est acceptable, pas un dépôt unique. Tous : publics, MIT, anglais ;
interface `en` (source), `fr` (relu par le mainteneur), `es` (annoncé « machine
translated, contributions welcome »).

## 5. Standards techniques

- **Cible** : HA ≥ 2026.9.1, **Python 3.14.2+** (HA 2026.9 exige 3.14).
  Support : la version courante de HA ; la précédente n'est pas testée
  (`pytest-homeassistant-custom-component` est épinglé à une version).
- **Manifest** : `iot_class: calculated`, `integration_type: helper`,
  `config_flow: true`, `version`, `documentation`, `issue_tracker`,
  `codeowners`. Pas d'intégration HACS dans `dependencies` (hassfest résout
  contre core) : `after_dependencies` + `hass.services.has_service` au runtime.
- **HACS** : `hacs.json` avec `zip_release: true` **et** `filename`,
  `homeassistant: "2026.9.1"`, `render_readme`. Un composant par dépôt, tout
  sous `custom_components/<domain>/`, README, description + topics GitHub,
  **icône embarquée** dans `custom_components/<domain>/brand/icon.png` +
  `icon@2x.png` (256/512, fond transparent) — depuis HA 2026.3 le dépôt
  `home-assistant/brands` **refuse** les nouvelles intégrations custom ; la
  vérification « brands » de l'action HACS accepte l'icône embarquée (vérifié
  le 07/09 sur le routeur, CI verte sans `ignore: brands`). Icônes générées
  localement (famille commune : badge bleu #1F3A5F, glyphe blanc).
- **Config** : config flow obligatoire ; `ConfigEntry.version/minor_version`
  et `async_migrate_entry` dès la v0.1 ; unique_id stables (§3.5).
- **Plateformes `notify` legacy — règles apprises aux relectures du 07/09**
  (Cast et AirPlay Notifier, no-go tous les deux pour les mêmes causes) :
  (1) core ne retire **jamais** un service `notify.*` legacy au déchargement
  d'une entrée et **ne le réenregistre pas** s'il existe déjà (`legacy.py`
  retourne tôt) → chaque intégration doit `hass.services.async_remove` son
  service dans `entry.async_on_unload` et purger `hass.data[NOTIFY_SERVICES]`,
  sinon les options ne prennent jamais effet ; (2) le service **lit l'entrée
  vivante** à chaque appel, ne capture jamais les options ; (3) tout état
  partagé (volume, timers) : verrou par cible, `try/finally`, timers annulés
  et liés au cycle de vie ; (4) `data.*` validé par un schéma voluptuous,
  `source_entity` normalisé (`ensure_list`, `str`, `casefold`) et refusé s'il
  est inexploitable ; (5) un device par entrée + `translation_key`, jamais un
  `_attr_name` littéral ; (6) les tests doivent couvrir reload d'options,
  unload/remove, échec du TTS, chevauchement, lecteur déjà en lecture.
- **Qualité** : `quality_scale.yaml` tenu comme **discipline interne** (le
  programme quality scale est réservé au core ; HACS ne l'exige pas).
- **Code** : `ruff` (format + lint), **config mypy reprise de core** (pas
  `--strict`), pas d'I/O bloquant, `_attr_has_entity_name`, `async_redact_data`.
- **Tests** : `pytest-homeassistant-custom-component` (version alignée sur
  2026.9.1) ; couverture ≥ 80 % sur le routage ; tests de config flow, de
  migration, de traduction (jeux de clés `en/fr/es` identiques) ; **test de
  contrat** (§3.3) ; **tests bout en bout** avec horloge simulée
  (`async_fire_time_changed`) : `alert on → repeat → route → Vu → turn_off →
  done_message`, redémarrage HA au milieu (snoozes restaurés), une sortie qui
  lève une exception, minuit et changement d'heure.
- **CI** : `hassfest`, `hacs/action`, ruff, mypy, pytest ; bloquant sur `main`.
  Pré-commit local identique pour les agents (sinon ils bouclent sur la CI).
- **Versionnage** : SemVer ; `0.x` jusqu'au gel du contrat ; `CHANGELOG.md`
  (Keep a Changelog) ; tag `vX.Y.Z` → release GitHub avec le zip.
- **Git** : `main` protégée, PR-only, squash, commits conventionnels ; **seul
  le donneur d'ordre merge** ; les agents ne touchent pas `.github/workflows`
  hors sprint dédié. Auteur des commits : le mainteneur (`amiel-35`), trailer
  `Co-Authored-By` pour l'agent.
- **Gouvernance** : `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  templates issue/PR. Les PR externes sont revues par le donneur d'ordre et
  validées par le mainteneur ; **jamais approuvées par un agent**.
- **Vie privée** : aucun secret en dépôt, aucune télémétrie ; diagnostics
  expurgés ; option « ne pas conserver le corps des messages ».
- **i18n** : `strings.json`/`translations/` pour l'UI ; section `common` +
  `async_get_translations` pour le texte que le routeur ajoute aux messages.

## 6. Harness

| Rôle | Tenu par | Responsabilité |
|---|---|---|
| **Donneur d'ordre** | session principale | brief + **tests d'acceptation pytest en échec livrés avec le brief**, découpe, lancement des agents, arbitrage, merge, release, contact du mainteneur |
| **Codeur cœur** | agent Opus | routeur : routage, config flow, entités — fait passer les tests d'acceptation **sans les modifier** |
| **Codeur périphérie** | agent Sonnet | adaptateurs, cartes, blueprints, traductions `es`, docs |
| **Testeur** | agent Sonnet, séparé | couverture, cas limites, `hassfest` ; ne modifie pas le code produit ; findings |
| **Relecteur** | agent Opus, contexte vierge | reçoit doctrine + `contract.md` + tous les ADR + diff + sortie CI + `checklist-relecture.md` ; verdict **go / no-go** uniquement |
| **Intégrateur** | donneur d'ordre | seul autorisé à toucher l'instance de dev ; scénarios bout en bout ; tag |

Règles :
- Les agents reçoivent le brief, la doctrine, `contract.md`, les ADR — jamais
  l'historique de conversation. Ils travaillent dans un **clone de
  `home-assistant/core` à la version cible** disponible localement ; **tout
  appel d'API core cité dans la PR doit pointer un fichier core** (parade à
  l'hallucination d'API, risque n°1).
- Codeur et testeur distincts ; le relecteur n'a vu ni l'un ni l'autre.
- **Un agent = un worktree git isolé** (`isolation: worktree`), jamais deux
  agents dans la même copie de travail : un agent docs a un jour basculé la
  branche courante pendant qu'un commit de l'orchestrateur partait, et a dû
  démêler l'historique à la main. Seul l'orchestrateur travaille dans la
  copie principale, et il n'y commit que lorsqu'aucun agent n'y tourne.
  Précision : l'option `isolation: worktree` de l'outil Agent crée un
  worktree du dépôt **de la session donneuse d'ordre**, pas du dépôt cible —
  pour tout autre dépôt, l'agent doit lui-même faire
  `git worktree add <dossier> -b <branche> origin/main` dans le dépôt cible et
  y travailler ; l'orchestrateur fait de même pour ses propres correctifs
  (worktrees sous `~/Projets/<repo>-worktrees/`), et ne lance **aucune**
  commande git dans la copie principale tant qu'un agent y code.
- Un finding du testeur **bloque la DoD** ou est accepté explicitement dans
  `known-issues.md`.
- Toute PR qui touche `contract.md` sans ADR est rejetée.
- Divergence avec la doctrine → ADR ou correction du code, jamais silence.

### Definition of Done

1. Tests d'acceptation du brief verts sans modification ; CI verte ; couverture tenue.
2. Relecture *go*.
3. Déployé sur l'instance de dev par l'intégrateur ; scénario bout en bout consigné.
4. `en` figé par le donneur d'ordre ; `fr` complet (relecture du mainteneur demandée à la release) ; `es` complet et étiqueté.
5. `contract.md`, `CHANGELOG`, ADR à jour ; tag ; release avec note lisible par un non-technicien.
6. `known-issues.md` à jour ; roadmap mise à jour ; le mainteneur prévenu.

## 7. Roadmap (ADR-012)

| # | Incrément | Critère d'acceptation exécutable | Dépend de |
|---|---|---|---|
| S0 | **Socle** (exception assumée : pas fonctionnel) | dépôt public, CI verte sur le squelette, `hassfest` OK, instance de dev joignable, `contract.md` v0 | — |
| S1 | **Routeur v0.1 = ex-S1+S2 fusionnés** : service legacy + `targets`, table de routage en UI, personnes ↔ services, présence, silence lu (`schedule`/`input_boolean`), priorités, boutons Vu/Snooze sécurisés, snoozes persistés, mode observer, entités, diagnostics, migration | une `alert` de test avec `notifiers: [switchboard_test]` : routée vers la personne présente et pas vers l'absente ; silence bloque sauf `critical` ; « Vu » depuis Companion → `alert.turn_off` (refusé hors allow-list) ; snooze 1 h retient ; redémarrage → snooze conservé ; cible interdisant le snooze → bouton absent | S0 |
| S2 | **Cartes v0.1** : bulle sur `alert.*` (compte, liste, acquitter, snoozer), tuiles de silence par personne ; accessibilité (§8) | la tablette murale de la maison de référence affiche les `alert.*` actives, acquitte, snooze ; contraste et clavier vérifiés | S1 |
| S3 | **Blueprints + doc + quickstart** : « état → alert routée », « événement → info routée », « source indisponible > N min → alert » (le cas KLIPPBOK, ADR-013) | un utilisateur externe installe et route une alerte en 10 min en suivant le README seul | S1 |
| S4 | **Google Home Notifier v0.1** | « la machine est finie » lue dans la cuisine via `notify.google_home_cuisine`, volume restauré | — |
| S5 | **AirPlay Notifier v0.1** | annonce lue sur un lecteur AirPlay | — |
| S6 | **HACS default** : brands, topics, soumission | acceptation HACS | S1-S3 |
| — | Alexa Notifier | reporté (couvert par Alexa Devices core) | — |

S4/S5 sont indépendants et peuvent s'intercaler dès S0 fini si le mainteneur veut la
voix pour la sonnette tôt.

**État d'avancement (07/09)** : S0 ✔ ; **S1 ✔ Notify Switchboard v0.1.0**
publié (182 tests, relecture go + correctifs, bout en bout sur l'instance de
dev) ; **S2 cartes ✔ v0.1.0** publié (91 tests, relecture no-go → go,
vérification visuelle : acquittement en direct OK, un défaut cosmétique en
issue) ; **S3 blueprints/quickstart ✔** fusionné ; **S4 Cast Notifier ✔
v0.1.0** publié (55 tests, no-go → go, bout en bout sur l'instance de dev ;
0.1.1 en cours pour l'ADR-015) ; **S5 AirPlay Notifier** : 69 tests, no-go →
correctifs → no-go de peu (hassfest placeholder + course sur le volume) →
derniers correctifs en cours, tag imminent ; **S6 HACS default** : pas
commencé (brands à soumettre) ; **routeur 0.2.0** (services UI + textes de
ligne, ADR-016) : spécification en cours.

## 8. Accessibilité des cartes (S2)

Couleurs par variables de thème HA (jamais en dur), information jamais portée
par la seule couleur (l'écran mural se lit de loin), cibles tactiles ≥ 48 px,
`aria-label`/rôles sur les boutons, navigation clavier et focus visible, pas
de troncature à 200 %, `prefers-reduced-motion` respecté.

## 9. Instance de développement

Conteneur `ha-dev` (`ghcr.io/home-assistant/home-assistant:2026.9.1` — tags
complets, pas de tag mineur) sur le serveur de dev, config et sources
montées en bind mount depuis le dépôt local, `127.0.0.1:8124` (tunnel SSH).
Compte `dev` ; token longue durée « claude-dev » sur le Mac (`~/.config/ha/dev-secret`).
`person`/`schedule` factices ; Companion d'un appareil de test. Rien de la
maison réelle. **Seul l'intégrateur y touche.**

## 10. Décisions produit propres à la maison (hors code)

Classes et personnes concernées ; priorités et ce qui lève un silence ; règle
d'absence ; acquittement vs snooze par cible ; heures de silence par personne ;
voix pour quelles informations ; Companion chez les enfants. → configuration
dans la maison de référence après release.

## 11. Risques et parades

| Risque | Parade |
|---|---|
| HA retire les services `notify` legacy (déjà cassant pour `alert`, core#164855) | mode observer implémenté et testé dès v0.1 (plan B) ; `NotifyEntity` en plus ; veille des discussions HA |
| `alert` gelé | on ne dépend que de son comportement actuel ; Alert2/AlertSys suivis comme alternatives |
| Concurrence : Ticker (170 ★, default), Supernotify, ANS | positionnement écrit : complément d'`alert`, proxy pur, UI, snooze persistant, natif d'abord ; pas de moteur maison |
| Hallucination d'API par les agents | clone core local + citations obligatoires + pré-commit hassfest/mypy |
| Mainteneur unique | tests, CI stricte, `known-issues.md`, gouvernance écrite |
| Portée qui gonfle | un dépôt par extension ; Alexa reporté ; le routeur reste un proxy |
| Green sous-dimensionné | routeur sans état lourd |

## 12. Journal des décisions (ADR)

- **ADR-001** natif d'abord ; **ADR-002** proxy `notify` pur ; **ADR-003** voix
  = adaptateurs séparés ; **ADR-004** Notifier Hub écarté (routage global, DND
  sans effet sur le push, pas de plateforme notify, GPL, inactif) ;
  **ADR-005** public/MIT/EN + fr/es ; **ADR-006** sprints = incréments.
- **ADR-007 (06/09, v0.2)** : socle = service `notify` legacy avec `targets` ;
  `NotifyEntity` dégradée en plus ; mode observer comme plan B testé.
- **ADR-008** : l'identité de l'alerte passe par la **cible** (`switchboard_<cible>`
  ↔ ligne de table), pas par `data` (non templatable dans `alert`).
- **ADR-009** : actions sécurisées — allow-list des `alert.*` acquittables,
  `authenticationRequired` par défaut sur `high`/`critical`, `context.user_id`
  journalisé.
- **ADR-010** : « voix ≠ alerte » et « sécurité hors voix » sont des règles de
  configuration documentées + deny-list optionnelle sur `data.source_entity`,
  pas des garanties du code.
- **ADR-011** : `contract.md` + test de contrat ; noms publics gelés à la 1.0.
- **ADR-012** : roadmap réordonnée — S1 absorbe l'acquittement, cartes et
  blueprints avant la voix, Alexa reporté (Alexa Devices core).
- **ADR-013** : la surveillance d'indisponibilité des sources (cas KLIPPBOK)
  est livrée en **blueprint** (S3), pas dans le routeur.
- **ADR-014 (07/09)** : l'adaptateur voix Cast s'appelle **Cast Notifier**
  (`cast-notifier`, `cast_notifier`), pas « Google Home Notifier » : ce nom
  est celui d'un projet Node.js de 574 ★ au même usage, et « Cast » couvre
  aussi Nest Hub et Chromecast. Style « X Notifier » conservé (AirPlay
  Notifier, Alexa Notifier si un jour).
- **ADR-015 (07/09)** : un adaptateur qui **refuse** un message (deny-list,
  `data` invalide) **lève une `ServiceValidationError` traduite et
  journalise** — jamais un refus silencieux (le bout en bout de Cast 0.1.0 a
  montré qu'un appelant recevait un 200 sur un message refusé). Coût assumé :
  une `alert` qui liste un notifier refusé verra une erreur à chaque
  répétition, ce qui est la bonne information. AirPlay 0.1.0 l'applique ;
  Cast s'aligne en 0.1.1.

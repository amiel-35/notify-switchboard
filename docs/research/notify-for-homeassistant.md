# Analyse concurrentielle — Notify! Alerts for Home Assistant (simplytoast1/Notify-for-HomeAssistant)

Date : 2026-09-06. Source : dépôt GitHub public, README (547 lignes), releases,
`manifest.json`, `hacs.json`. Aucun code copié ; seuls des noms de services,
de champs et d'endpoints (faits, non protégeables) sont cités.

## 1. Nature exacte et fiche

**Ce n'est pas un routeur/proxy `notify`, ni une carte Lovelace.** C'est une
**intégration HA classique** (`custom_components/notify_api/`, catégorie
HACS « Integration », `integration_type: service`, `iot_class: cloud_push`)
qui expose un **client pour un service tiers propriétaire** : l'API Notify!
Partner de push.getnotifyapp.com (société Pingie.com). Il n'y a aucun
dossier `www/` ni carte frontend — le HACS badge « render_readme: true »
sert juste à afficher le README dans HACS.

Fiche :
- **Licence** : MIT (fichier `LICENSE` présent).
- **Étoiles** : 2 (0 fork, 2 watchers) — dépôt jeune et confidentiel.
- **Créé** : 21/11/2025. **Dernier commit / push** : 31/08/2026 (release v1.2.1
  le même jour). Rythme de release soutenu sur 2026 (v1.0.1 → v1.2.1 en
  ~9 mois).
- **Issues** : 0 ouverte, 0 fermée — aucun retour utilisateur public
  exploitable (pas de signal de bug/demande récurrente sur le tracker).
- **HACS** : oui, listé comme repo custom (pas encore dans le store par
  défaut a priori, s'installe via « Custom repositories »).
- **Config** : 100 % UI (config_flow), pas de YAML. Un identifiant
  Device/Group ID + token saisis dans le flow, validés via `GET /link`
  avant création de l'entrée (sans envoyer de notification réelle — point
  UX intéressant). Une option « Configure » pose des valeurs par défaut
  (titre, icône, image, thread, time_sensitive) par entrée.
- Fichiers : `__init__.py`, `api.py`, `config_flow.py`, `const.py`,
  `notify.py`, `services.py` (+ `services.yaml`, `strings.json`,
  `translations/en.json`, `brand/`). Un client HTTP maison (`aiohttp`)
  vers `push.getnotifyapp.com`, pas de dépendance externe déclarée
  (`requirements: []`).

## 2. Modèle : stockage, routage, persistance, acknowledgement, UI

Le modèle est **1 entrée de config = 1 appareil/groupe Notify! = 1 service
`notify.<nom>`**. Il n'y a pas de notion de « personne » HA
(`person.*`), pas de présence, pas de silence programmable, pas de snooze,
pas d'audience multi-destinataires calculée côté HA : l'audience est déjà
décidée côté app Notify! (un « Device Group » y agrège plusieurs
appareils, HA ne fait qu'appeler le service correspondant). Chaque appel
`notify.<nom>` part tel quel vers l'API distante (`POST /notify-json/{id}`).

- **Stockage** : uniquement les credentials (ID + token) et les défauts
  d'entrée, dans le config entry HA standard. Aucun historique, aucun état
  de snooze, aucun accusé de réception n'est gardé côté HA.
- **Acquittement** : absent au sens Switchboard. La seule action retour est
  le bouton d'une Live Activity, qui déclenche une requête HTTPS
  **envoyée directement par le téléphone** vers une URL de votre choix
  (ex. un webhook HA) — ce n'est pas un callback `mobile_app_notification_action`
  ni un service HA appelé côté intégration ; l'API Notify! n'est pas dans
  la boucle.
- **UI** : pas de dashboard Lovelace fourni ; toute la gestion (device,
  device group, beacons) se fait dans l'app tierce Notify!, hors HA.
- **Fonctionnalités propres, hors du périmètre notify classique** : Live
  Activities (tuile Lock Screen avec cycle start/update/end, jauge de
  progression, countdown local `ends_in`, étapes `steps`/`step`, jusqu'à 6
  « metrics », bouton tappable), Widgets Home Screen persistants
  (`widget_set`/`widget_delete`, 10 max par appareil), Beacons (monitoring
  inversé : `beacon_ping` régulier, alerte si HA s'arrête de pinguer —
  couvre le point mort classique « qui surveille HA lui-même »).

## 3. Tableau comparatif

| Fonction | Notify! Alerts (ce projet) | Notify Switchboard v0 (+ cartes) |
|---|---|---|
| Nature | Intégration = client d'un service push tiers payant/propriétaire | Proxy `notify` interne, domaine `notify_switchboard`, cartes Lovelace incluses |
| Destinataires | 1 entrée = 1 device/groupe Notify! (agrégation faite côté app tierce) | Table de routage par `person.*`, audience calculée par ligne |
| Présence | Aucune | Règle `always/home_only/away_only` par personne |
| Silence | Aucun (à gérer en amont dans les automatisations HA) | `schedule`/`input_boolean` par personne, bypass sur `priority: critical` |
| Snooze | Aucun | Snoozes persistants par (personne, cible), `Store`, avec expiration |
| Acquittement | Bouton Live Activity → webhook HTTPS déclenché par le téléphone, hors HA | Bouton Companion → `mobile_app_notification_action` → `alert.turn_off` (allow-list) |
| Intégration `alert` | Aucune | Native : ack sur `alert.*`, mode Observer sur transitions d'état |
| Sorties | Une seule API propriétaire (push iOS/navigateur/macOS via Notify!) | N'importe quel `notify.*` existant (dont potentiellement `notify.<device>` de ce projet) |
| Persistance des messages | Historique dans l'app Notify! (hors HA) | `Store` HA pour snoozes ; compteurs `sensor.switchboard_routed_today`/`dropped_today` |
| UI de config | 100 % config_flow, defaults par entrée | UI prévue (non détaillée ici), + cartes Lovelace (bulle alertes, tuiles silence) |
| Richesse du message | Titre, icône, image hero, threading, `time_sensitive`, Live Activity, widget | `message`/`title`/`data` fusionnées, boutons ack/snooze ajoutés |
| Dédup/anti-spam | Threading (`group_type`) côté device uniquement | `tag` transmis pour dédup, mais logique de dédup non spécifiée dans le contrat |
| Observabilité | Logs HA classiques + réponse API (ex. group partiellement livré) | Entité `event.switchboard_delivery` avec `routed/dropped/acknowledged/snoozed`, capteurs par personne |

## 4. Interface avec `alert`, `persistent_notification`, `notify`, Companion

- **`alert`** : aucune interface. Le projet ignore complètement le domaine
  `alert` — pas d'écoute d'état, pas de service `alert.turn_off`, pas de
  configuration liée à une entité `alert.*`.
- **`persistent_notification`** : aucune mention dans le README ni dans la
  liste de fichiers ; pas de miroir de notification persistante.
- **`notify` legacy/entités** : c'est son cœur de métier — il **crée** des
  services `notify.<slug>` (un par entrée), au style legacy classique
  (service par plateforme), pas d'entité `NotifyEntity`. Le nom du service
  dérive du nom donné à l'entrée (piège historique documenté dans le
  changelog 1.1.0 : apostrophe/accent cassait le nom, deux entrées pouvant
  produire le même slug et se marcher dessus — corrigé mais instructif).
- **Companion (app mobile officielle HA)** : **non utilisé**. Le projet
  court-circuite complètement l'app Home Assistant Companion : il pousse
  directement vers l'app tierce « Notify! » (iOS/macOS/navigateur), pas de
  lien avec `mobile_app.*`, `notify.mobile_app_*`, ni les actions/callback
  `mobile_app_notification_action` qu'utilise Switchboard pour ack/snooze.

## 5. Faiblesses visibles, demandes utilisateurs

- **Zéro issue publique** (ouvertes ou fermées) : impossible de sourcer de
  vraies demandes/retours d'utilisateurs sur ce dépôt — signal de traction
  encore faible (2 étoiles, pas de discussions).
- **Dépendance à un service tiers propriétaire** (Pingie.com/Notify!) :
  nécessite un compte externe, un token, une app dédiée ; à l'opposé de
  l'esprit « tout en local » de HA — risque de continuité si le service
  ferme.
- **Pas de multi-plateforme homogène** : les fonctionnalités riches (Live
  Activity, widget) ne marchent que sur iPhone ; navigateur/macOS/groupe
  sont dégradés en simple notification, avec des erreurs historiquement
  opaques avant le correctif 1.2.1 (« refusé sans dire pourquoi »).
- **Pas de dédup/priorité/silence** : tout ce que Switchboard traite
  (audience, silence, snooze, criticité) est absent ; à la charge des
  automatisations amont.
- **Aucun accusé de réception réintégrable dans HA** : le bouton Live
  Activity appelle un webhook choisi par l'utilisateur, mais rien dans
  l'intégration ne ferme automatiquement une alerte HA suite à un tap.
- **Piège numérique documenté** : `ends_in` non plafonné comme `progress`
  — un envoi en millisecondes au lieu de secondes est refusé plutôt que
  silencieusement mal interprété (bon choix défensif, mais à noter comme
  piège d'implémentation classique évité ici).
- **Rate limit partagé** : la vérification de credentials (`GET /link`)
  et l'envoi partagent le même quota (5/min par adresse) — donc tester la
  config peut griller le budget d'envoi réel.

## 6. Idées à reprendre (clean room) / pièges à éviter

1. **Validation des credentials avant création d'entrée, sans effet de
   bord visible** (`GET /link` ne notifie pas le device) — à reprendre pour
   toute future vérification de config Switchboard (ex. vérifier qu'un
   `notify.*` cible existe sans lui envoyer de message test).
2. **Accepter les deux casses de clés** (snake_case et camelCase) pour les
   champs `data` copiés-collés depuis une doc externe — réduit la friction
   utilisateur ; à envisager si Switchboard expose un jour des alias.
3. **Refuser explicitement plutôt que silencieusement échouer** : un appel
   incompatible (Live Activity vers un navigateur) renvoie un message
   nommant la fonctionnalité demandée et la raison, au lieu d'un échec
   opaque — aligné avec l'esprit `dropped` avec raison du contrat
   Switchboard ; bon rappel de toujours nommer la raison précise (pas
   juste « refused »).
3bis. **Logger une clé de `data` inconnue une seule fois** (pas à chaque
   appel) plutôt que de la faire échouer — équilibre bon entre silence
   total et flood de logs, utile pour le traitement des clés `data`
   arbitraires du contrat Switchboard (`# any other key is merged`).
4. **Idempotence documentée explicitement** : « appeler `end` sur une
   tuile déjà finie est un succès, pas une erreur » — pattern à répliquer
   pour `alert.turn_off` côté Switchboard (acquitter une alerte déjà
   acquittée ne doit jamais lever).
5. **Distinguer clairement ce qui persiste de ce qui ne persiste pas** :
   le README a un paragraphe dédié « countdown côté client (`ends_in`,
   0 appel réseau supplémentaire) vs. barre de progression (1 appel par
   changement) » — pour Switchboard, documenter aussi clairement le coût
   de chaque mécanisme (snooze persistant vs compteurs volatils).
6. **Piège de nommage à éviter absolument côté Switchboard** : leur bug
   historique (accents/apostrophes cassant un nom de service, deux entrées
   collisionnant sur le même slug) est directement transposable au
   slug `<target>` de `notify.switchboard_<target>` — vérifier l'unicité
   du slug de routing-table row et le comportement sur caractères
   spéciaux/accents dès la validation de config.
7. **Champ `unknown_key` traité comme un typo signalé, pas une erreur
   bloquante** — cohérent avec la tolérance voulue par le contrat
   Switchboard (« any other key is merged »), mais suggère d'ajouter un
   log d'avertissement ponctuel pour une clé jamais vue dans `data`,
   utile en diagnostic sans casser l'appelant.
8. **Ne pas suivre une redirection HTTP portant un token en query string**
   (mentionné dans le changelog 1.1.0) — rappel utile si Switchboard
   finit par causer des appels sortants HTTP (ex. futurs outputs webhook) :
   ne jamais suivre aveuglément une redirection qui pourrait leaker un
   secret dans l'URL.

Piège d'affichage/consommation : sans objet direct — ce projet n'a pas de
carte Lovelace ; toute l'UI de consultation (historique, device group,
beacons) vit dans l'app tierce, hors HA. Aucun enseignement direct à tirer
pour la bulle d'alertes ou les tuiles de silence prévues par Switchboard.

# Analyse concurrente — `messages_store` (FernandoZueet)

Dépôt : https://github.com/FernandoZueet/messages_store
Analyse factuelle uniquement, sans copie de code. Comparé au contrat
[`docs/notify-switchboard-contract-v0.md`](../notify-switchboard-contract-v0.md).

## 1. Nature et fiche d'identité

Ce n'est **ni** un centre de notifications, **ni** un historique de messages
envoyés : c'est un **CMS texte** (base clé→valeur de "slugs" → messages),
pensé pour externaliser le contenu textuel des automatisations (TTS,
notifications mobiles, Telegram) hors du YAML, avec templating
(`(state:entity_id)`, `(slug:x)`, `%s`) et génération assistée par IA.

| Critère | Valeur |
|---|---|
| Licence | MIT |
| Étoiles / forks | 12 étoiles, 1 fork, 1 watcher |
| Créé / dernier push / dernière release | créé 31/08/2024 ; dernier push 29/08/2025 ; release **1.3.0** (29/08/2025) — **dépôt dormant depuis ~1 an** |
| Mainteneur | un seul auteur, peu de PR externes mergées (4 PR au total, 2 issues ouvertes sans réponse) |
| HACS | oui, mais uniquement en "custom repository" (README : ajout manuel de l'URL), pas dans le store par défaut |
| Config | `config_flow: true`, instance unique (`single_instance_allowed`), option UI pour choisir une entité `ai_task` + instructions par défaut |
| `integration_type` / `iot_class` | `service` / `local_push` — délibérément **sans entité** (pas de `sensor.*`) |

## 2. Modèle de stockage et de lecture

- **Stockage** : SQLite brut (module `sqlite3`, pas `recorder`, pas
  `homeassistant.helpers.storage.Store`). Point notable et risqué :
  `PATH_DB_SQLITE = "home-assistant_v2.db"` — le composant ouvre une
  **deuxième connexion directe au fichier SQLite du `recorder` lui-même**
  et y crée sa propre table `messages_store (id, slug, message)`, en
  parallèle des écritures du recorder. Pas de migration de schéma visible,
  pas de verrouillage particulier au-delà de celui de SQLite.
- **Rétention** : aucune notion de TTL/purge — chaque `slug` est un
  enregistrement permanent jusqu'à suppression explicite
  (`delete_message`). Une liste de messages sous un même slug est stockée
  concaténée avec un séparateur `|`.
- **Lecture/acquittement** : `get_message`/`get_messages` renvoient le
  contenu (avec substitution de tags et remplacement `%s`) ; **aucune
  notion de lu/acquitté/livré** — ce n'est pas un log d'événements, un
  slug n'a pas de statut.
- **Affichage** : un panneau natif dans la sidebar HA (pas une carte
  Lovelace), servi via `async_register_built_in_panel` +
  `_panel_custom` en `embed_iframe`, appli front séparée
  (`frontend/` : TypeScript + Tailwind + Rollup) pour lister/chercher/
  éditer/ajouter les slugs. Réservé aux admins (`require_admin: true`).
- **API/services** : `add_message`, `get_message`, `edit_message`,
  `delete_message`, `get_messages` (filtre, groupement, aléatoire),
  `add_bulk_messages`, `generate_ai_messages` (via une entité `ai_task`
  configurée dans les options — seul point qui peut sortir du LAN si
  l'`ai_task` pointe vers un LLM cloud).
- **Vie privée** : sinon 100% local ; le risque n'est pas la fuite de
  données mais la **cohabitation non maîtrisée avec le fichier du
  recorder** (verrous, corruption potentielle en cas d'écriture
  concurrente, pas de sauvegarde/restauration dédiée).

## 3. Tableau comparatif

| Fonction | messages_store | Switchboard v0 |
|---|---|---|
| Nature | CMS texte (slug → message), pas de routage | proxy `notify` par personne avec routage |
| Entrée | services CRUD sur des slugs | `notify.switchboard_<target>` (legacy + entity) |
| Cible / présence | aucune notion de destinataire | règle par personne (`always`/`home_only`/`away_only`) |
| Silence / snooze | absent | par personne, `input_boolean`/`schedule` + snooze persistant |
| Lien avec `alert` | aucun | `alert.turn_off` sur acquittement, allow-list |
| Historique des envois | aucun (ce n'est pas son rôle) | prévu via `event.switchboard_delivery` + diagnostics |
| Stockage persistant | SQLite brut dans `home-assistant_v2.db` | `Store` HA pour les snoozes (contrat) |
| Interface | panneau sidebar (iframe, app front dédiée) | cartes Lovelace (bulle d'alertes) |
| Génération IA du contenu | oui (`generate_ai_messages` via `ai_task`) | non prévu |

## 4. Interface avec `notify` / `persistent_notification` / `alert` / Companion

`messages_store` n'est **ni un `notify.*`, ni un consommateur de
`notify`** : il ne s'abonne à rien et n'appelle jamais lui-même un
service `notify`. C'est une brique **en amont**, appelée depuis une
automatisation pour obtenir une chaîne de texte, que l'utilisateur passe
ensuite lui-même à `notify.mobile_app_x`, `tts.speak`, Telegram, etc.
Aucune référence à `persistent_notification`, `alert` ou aux actions
Companion App dans le code exploré — zéro couplage avec l'écosystème de
notification HA, contrairement à Switchboard qui en est le cœur.

## 5. Faiblesses visibles / demandes utilisateurs

- Partage du fichier SQLite du recorder : architecturalement fragile, non
  documenté comme un choix assumé, aucun test de résilience visible.
- Pas d'action `append_message` (demandée et fermée sans suite, issue
  #6) : on ne peut qu'ajouter un slug entier ou l'écraser, pas y ajouter
  une variante.
- Issue #7 (ouverte, sans réponse) : un utilisateur ne sait pas comment
  simplement afficher un message sur une carte markdown du dashboard —
  révèle l'absence de toute entité/état exposé nativement (il faut un
  template sensor qui appelle le service en aval, ou du JS custom).
- Issue #4 "Component not working" (ouverte, sans réponse) sur HA
  2025.3 — pas de suivi de compatibilité visible, dépôt en pause depuis
  un an malgré des demandes actives.
- Pas de tests automatisés ni de CI visibles dans l'arborescence
  explorée (contrairement à d'autres projets comparables).

## 6. Idées à reprendre (clean room) / pièges à éviter

1. **Idée** : un vrai "template engine" pour le corps des messages
   (`(state:x)`, placeholders `%s`) est une bonne séparation contenu/logique
   — à envisager si Switchboard doit un jour enrichir le `message` avant
   diffusion, mais côté source de l'appel `notify.switchboard_*`, pas dans
   le routeur lui-même (garder le routeur "bête" côté contenu, cf. ADR-008
   du contrat qui exclut déjà le contexte de l'alerte du payload).
2. **Idée** : panneau sidebar dédié (plutôt qu'une carte Lovelace) pour un
   usage admin uniquement — à garder en tête si un jour un écran de
   *configuration* de la table de routage Switchboard (vs juste
   affichage) devient nécessaire ; mais pour la "bulle d'alertes" grand
   public, la carte Lovelace reste le bon choix (accès non-admin).
3. **Piège à éviter absolument** : ne jamais ouvrir de connexion directe
   au fichier du `recorder` (`home-assistant_v2.db`). Si Switchboard a
   besoin de persistance (snoozes, historique), utiliser exclusivement
   `homeassistant.helpers.storage.Store` (déjà le choix du contrat) ou,
   pour un historique, le bus d'événements + `logbook`/`recorder` via les
   API officielles — jamais un accès SQLite parallèle.
4. **Piège** : ne pas confondre "store de contenu" et "historique de
   diffusion" — les deux besoins sont orthogonaux ; `messages_store`
   prouve par l'exemple qu'on peut avoir un CRUD texte très utile sans
   jamais tracer qui a reçu quoi.
5. **Sur la question ouverte de Switchboard** ("faut-il un historique des
   notifications routées, sous quelle forme native ?") : ce concurrent ne
   répond pas au besoin (il ne logue rien), mais son échec à répondre à
   l'issue #7 est un signal utile — les utilisateurs veulent au minimum
   **voir le dernier état sur le dashboard**, pas nécessairement un log
   complet. Recommandation dérivée : les entités déjà prévues au contrat
   (`sensor.<person>_last_notification`, `sensor.switchboard_routed_today`
   /`_dropped_today`) couvrent déjà ce besoin minimal sans historique
   persistant ; un vrai historique borné (ex. dernières N entrées par
   `event.switchboard_delivery`, consultable via `logbook`, qui a sa
   propre rétention configurable côté recorder) est suffisant — inutile
   de réinventer un stockage SQLite maison comme le fait ce concurrent.
6. **Idée mineure** : le mode "grouped"/"random" de `get_messages` (piocher
   un message aléatoire par slug) est une bonne pratique UX pour éviter la
   monotonie des messages récurrents — transposable au *contenu* des
   notifications Switchboard si un jour on varie les libellés, mais hors
   scope du routeur lui-même.

# Analyse concurrente — `Email-Notify-Manager` (cy-bertrand)

Dépôt : https://github.com/cy-bertrand/Email-Notify-Manager
Analyse factuelle uniquement, sans copie de code. Comparé au contrat
[`docs/contract.md`](../contract.md).

## 1. Fiche d'identité

| Critère | Valeur |
|---|---|
| Nature du projet | Intégration HA de **gestion d'e-mails en libre-service par utilisateur** (pas un gestionnaire de notifications multi-canal, pas un routeur d'alertes) : un admin définit des "automations" nommées, chaque utilisateur HA choisit lui-même ses adresses e-mail et ses conditions depuis un panneau sidebar dédié |
| Licence | GPL-3.0 |
| Étoiles / forks / watchers | 1 étoile, 0 fork, 1 watcher, 0 subscriber |
| Dernier commit / release | push le 30/07/2026 (commits doc uniquement) ; dernier vrai commit applicatif le 18/05/2026 ; unique release **v3.3.0** (18/05/2026, "first fully working release") ; premier commit ~17/05/2026 — dépôt très jeune (~2,5 mois de vie, activité de code figée depuis mi-mai) |
| Mainteneur | un seul auteur (`cy-bertrand`), 24 commits, aucun autre contributeur |
| Issues/PR | **0** issue et **0** PR, ouvertes ou fermées — aucun signal utilisateur exploitable sur GitHub |
| HACS | Oui, catégorie *integration*, `hacs.json` présent, se revendique "HACS Default" ; installable aussi en dépôt personnalisé |
| Config | 100% UI (`config_flow: true`) pour le SMTP (serveur/port/identifiants/expéditeur/STARTTLS), testé en direct via `smtplib` à la création ; **une seule config entry autorisée** (`already_configured` bloque toute deuxième instance) ; les "automations" elles-mêmes sont gérées via le panneau frontend (WebSocket), pas via config_flow |
| HA minimale | `2025.10.0` (déclaré dans `hacs.json`) |

## 2. Modèle fonctionnel

Le concept central est un **service unique** `email_notify_manager.send_email_notification` appelé par les automatisations HA de l'utilisateur, combiné à des **préférences par (utilisateur × automation)** définies en libre-service :

- **Destinataires** : des **utilisateurs HA** (comptes, pas des `person.*` directement) désignés dans chaque "automation" par nom d'utilisateur ou UUID (`allowed_users`) ; liste vide = tous les comptes non-système. La résolution se fait par correspondance floue `user.id in allowed_users or user.name in allowed_users` — fragile à la casse et à un renommage (le README avertit explicitement du piège de casse).
- **Canal** : **e-mail uniquement**, envoi SMTP natif (`smtplib`, bloquant, exécuté via `async_add_executor_job`), une connexion/authentification/`quit()` **par utilisateur éligible et par appel de service**, en boucle séquentielle. Pas d'autre canal, pas de `notify.*` en sortie.
- **File d'attente / regroupement (digest)** : **aucun**. Chaque appel du service = autant d'envois SMTP immédiats que d'utilisateurs éligibles, aucune mise en attente, aucun regroupement de plusieurs messages en un seul e-mail.
- **Conditions par utilisateur (auto-gérées dans le panel)** :
  - Localisation : `always` / `home` / `away` / `zone_in` / `zone_out`, évaluée sur `person.*` (ou `device_tracker.*`) dont l'attribut `user_id` correspond au compte ; les zones sont testées par un calcul haversine maison (pas la logique zone native de HA).
  - Horaire : `always` / `range` avec heure de début/fin (`HH:MM`) + jours de la semaine cochés — une porte "envoyer / ne pas envoyer" évaluée à l'instant T.
  - Une condition non remplie = message **perdu**, pas différé : rien ne renvoie l'e-mail à la réouverture de la fenêtre horaire ou au retour dans la zone.
- **Snooze / acquittement** : absents. Le seul état persistant par automation est un booléen `enabled` (marche/arrêt), pas de silence temporaire, pas de bouton d'action, aucun lien avec une entité `alert.*`.
- **Persistance** : deux `Store` HA — automations (`id → label, allowed_users`) et préférences (`user_id → automation_id → {enabled, emails, conditions}`). Aucun historique des envois/échecs, aucun compteur "routé"/"dropped".
- **Templates** : `title`/`message`/`html_message` sont fournis tels quels par l'automation appelante (rendu Jinja2 fait côté YAML de l'appelant) ; envoi multipart texte+HTML si `html_message` fourni. Rien n'est templaté ni traduit côté intégration — seules les chaînes de l'UI (config flow, panel) sont en `fr`/`en`.
- **Frontend** : un panneau JS unique (~48 Ko) servi par une route statique HA et ajouté à la sidebar (`require_admin=False`), avec un onglet "Administration" affiché côté client aux admins mais dont chaque commande WebSocket est re-vérifiée côté serveur (`connection.user.is_admin`) — pas de faille de sécurité malgré le gate visuel côté client.

## 3. Tableau comparatif

| Fonction | Email-Notify-Manager | Switchboard v0 |
|---|---|---|
| Interface d'entrée | 1 service custom `email_notify_manager.send_email_notification` | services legacy `notify.switchboard_<target>` (+ entité `notify.switchboard`) |
| Nature de l'intégration | gestionnaire d'e-mails en self-service par utilisateur | proxy `notify` générique multi-canal, multi-cible |
| Destinataires | comptes utilisateurs HA (via `allowed_users`) | `person.*` déclarés dans l'audience d'une ligne de routage |
| Canaux de sortie | e-mail SMTP natif uniquement | tout service `notify.<output>` existant |
| Silence / DND par personne | seul un toggle global `enabled` par (utilisateur × automation) | `schedule`/`input_boolean` par personne, bypass si `critical` |
| Snooze | absent | snooze persistant par (personne × cible), avec expiry |
| Regroupement / digest | absent — un envoi SMTP par destinataire et par appel | non prévu en v0 (drop tracé + observer mode plutôt qu'un digest) |
| Conditions horaires | porte on/off par automation, message perdu si hors fenêtre | silence via `schedule`/`input_boolean`, pas de digest non plus en v0 |
| Acquittement lié à une alerte | absent, aucun lien avec `alert.*` | `alert.turn_off` sur la ligne, allow-list stricte |
| Priorités | aucune notion de priorité | 4 niveaux (`info/normal/high/critical`), `critical` bypass tout |
| Observabilité des échecs/drops | logs HA uniquement, aucun compteur exposé | `sensor.switchboard_dropped_today` + raisons structurées |
| Config | UI, une seule config entry (SMTP) | UI prévue par le contrat, table de routage multi-lignes |
| Entités créées | aucune (services + panel + WebSocket seulement) | entités par personne + entités globales |

## 4. Interface avec `alert` / notify legacy / config flow

- **`alert` core** : aucune interaction. Le domaine n'est jamais référencé dans le code ; le champ `automation_id` est une chaîne libre choisie par l'admin, sans rapport avec une entité `alert.*`.
- **Services `notify` legacy** : l'intégration n'expose **pas** de service `notify.*` ni d'entité `notify` — c'est un service de domaine propre (`email_notify_manager.send_email_notification`), invisible dans la liste des cibles `notify` de HA et sans propriété `targets` standard. Elle ne consomme pas non plus de `notify.*` en sortie (l'envoi SMTP est natif, pas délégué).
- **Config flow** : un flow simple et robuste — test de connexion SMTP synchrone (`smtplib`) avant création de l'entrée, erreurs distinctes (`invalid_auth`/`cannot_connect`/`unknown`), options flow pour changer les identifiants. Mais **une seule entrée possible** (`self._async_current_entries()` → abort `already_configured`) : un seul compte SMTP pour tout le foyer, et chaque sauvegarde d'options déclenche un `async_reload` complet de l'entrée (listener d'update inconditionnel).
- **Gestion des "automations"** : ne passe pas par un config flow ni par des sous-entrées — c'est un CRUD exposé uniquement via WebSocket (`enm/admin/upsert_automation`, `enm/admin/delete_automation`), piloté depuis le panneau frontend, pas depuis Paramètres → Intégrations.

## 5. Faiblesses visibles / demandes utilisateurs

- **Aucun signal utilisateur exploitable** : 0 issue, 0 PR, 0 discussion, wiki vide, 1 étoile, mono-mainteneur, code figé depuis mi-mai (seuls les commits suivants ne touchent que le README). Impossible d'extraire de vraies "demandes utilisateurs" — le projet est trop jeune et trop peu adopté pour ça ; les faiblesses ci-dessous viennent uniquement de la lecture du code et de la doc.
- Faiblesses de conception repérées à la lecture :
  - Aucune rétention des messages non envoyés (condition horaire/zone non remplie, échec SMTP) : tout est un `skip` silencieux ou un log d'erreur, jamais une remise en file — un message "raté" est perdu définitivement.
  - Envoi SMTP séquentiel et bloquant, une connexion complète (connect/login/quit) par destinataire et par appel — pas de réutilisation de connexion, pas de traitement par lot, exposé à du throttling côté fournisseur en cas de fan-out à plusieurs utilisateurs.
  - Résolution des destinataires par correspondance nom/UUID peu robuste (sensible à la casse et au renommage d'utilisateur, documenté comme piège dans le README lui-même plutôt que corrigé dans le code).
  - Une seule config entry SMTP pour toute l'installation : pas de multi-fournisseur, pas de compte d'envoi différent par automation.
  - Pas de traçabilité des envois (aucun historique, aucun compteur, aucune raison de drop exposée) — le dépannage se limite à `ha logs | grep email_notify` selon la doc elle-même.
  - Quelques logs internes affichent des caractères mal encodés (`SMTP non configurÃ©`, `envoyÃ© Ã ...`) — signe d'un souci d'encodage source, sans impact fonctionnel mais révélateur d'une maturité de code limitée.

## 6. Idées à reprendre (clean room) / pièges à éviter

1. **Panneau self-service par destinataire** — bonne idée UX (chaque personne configure ses propres canaux/conditions sans toucher au YAML) ; à garder en tête si Switchboard veut un jour une UI "mes notifications" par personne, en complément — pas en remplacement — de la table de routage YAML/UI actuelle.
2. **Test de connexion synchrone dans le config flow avant création de l'entrée**, avec erreurs distinguées (`invalid_auth`/`cannot_connect`) — réflexe UX propre, transposable si Switchboard doit un jour valider un output à la configuration.
3. **Séparation stricte gestion (WebSocket + panel) / exécution (service HA)** — le CRUD des automations ne pollue pas le service d'envoi ; modèle sain à garder si Switchboard expose un jour une UI d'édition de la table de routage.
4. **Piège majeur à éviter — pas de rétention, pas de digest** : ENM traite une condition horaire/zone non remplie comme une perte pure et simple, jamais comme un report. Pour un futur "digest de nuit" côté Switchboard, la bonne architecture est l'inverse : persister (via `Store`) chaque message "à reporter" avec son destinataire et sa cible, puis à l'heure de flush (fixe, ou à la réouverture d'un `schedule`) **regrouper tous les messages en attente pour un même (personne, cible) en un seul appel `notify.<output>`** — jamais rejouer un envoi par message.
5. **Piège à éviter — canal lent traité comme un canal rapide** : ouvrir une connexion SMTP complète par destinataire et par appel ne passe pas à l'échelle et n'a aucun retry. Si Switchboard interagit un jour avec un canal lent similaire (e-mail en sortie via `notify.smtp`), le report de nuit doit être pensé comme **un seul envoi consolidé par (personne, cible) au flush**, pas comme N appels immédiats espérant chacun réussir.
6. **Piège à éviter — perte silencieuse des échecs** : aucun compteur, aucune raison structurée, dépannage par grep de logs. Confirme par la négative le choix déjà pris dans le contrat Switchboard (`sensor.switchboard_dropped_today` + raisons `silenced`/`snoozed`/`unknown_target`) — à ne surtout pas relâcher au moment de l'implémentation.
7. **Piège à éviter — aucun lien avec `alert`** : ENM n'a ni acquittement ni notion d'alerte source ; ça valide que l'interface native avec `alert.turn_off` et l'allow-list de sécurité déjà prévues dans le contrat Switchboard sont une vraie différenciation, pas un détail secondaire à sacrifier pour aller plus vite.
8. **Piège à éviter — résolution de destinataire par chaîne libre (nom ou UUID mélangés)** : source de bugs silencieux en cas de renommage. Switchboard doit continuer à s'appuyer strictement sur les `entity_id` `person.*` (identifiants stables) plutôt que sur des noms d'utilisateur saisis à la main.

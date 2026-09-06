# Analyse des projets voisins — synthèse (06/09/2026, 23h)

Six dépôts analysés par des agents (un rapport chacun dans ce dossier), plus
l'état de l'art général (`../etat-de-l-art-notifications-ha-2026-09-06.md`).
Aucun code repris ; licences notées.

| Projet | Nature | Licence / vie | Ce qu'il partage avec nous | Ce qui nous distingue |
|---|---|---|---|---|
| **Ticker** (170 ★, HACS default, 21 releases en 5 mois) | produit complet : abonnements (personne × catégorie), conditions AND/OR, snooze, TTS/chime, historique, 2 panels custom | Apache-2.0 ; très actif | snooze par personne × catégorie, callbacks Companion, priorité `critical` | **aucun lien avec `alert` core** (pas de `turn_off`, pas d'observer) ; service custom `ticker.notify` + `notify.ticker` minimal, pas de `targets` ; panels custom qui cassent la navigation Companion (3 issues) ; ack = simple log |
| **Supernotify** (19 ★, default, v2.3.1) | hub multi-canal (20 transports, templating, dédup, PTZ) | Apache-2.0 ; actif | hérite de `BaseNotificationService`, callbacks Companion | audience implicite (tout le monde), pas de table par personne ; snooze **en mémoire** (documenté non persistant) ; zéro référence à `alert` ; pas de `targets` ; complexité de config reconnue |
| **smart-presence-notify** (1 ★) | envoi présence-aware | MIT ; 4 mois | file persistante (Store) avec fallback | présence **globale**, 2 priorités, dédup **en RAM**, pas de DND par personne, pas d'`alert` |
| **Notifier Hub** (35 ★) | hub voix + texte (ex-AppDaemon) | GPL-3.0 ; inactif depuis 09/07 | carnet d'adresses, présence, DND, `confirmation`/`escalate` | routage global, DND sans effet sur le push, pas de plateforme `notify`, pas d'`alert` |
| **Email-Notify-Manager** (1 ★) | e-mail en libre-service par utilisateur | GPL-3.0 ; figé | conditions horaire/zone | un message hors condition est **perdu** (anti-pattern du report) ; pas de `notify.*`, pas d'entités |
| **messages_store** (12 ★) | CMS de textes de messages | MIT ; dormant | — | écrit en SQLite **dans la base du recorder** (à ne jamais faire) ; pas un historique de diffusion |
| **Notify-for-HomeAssistant** (2 ★) | client d'un service tiers payant (Notify!/Pingie) | MIT | Live Activities, beacons | hors sujet (pas de routage, contourne Companion) ; bug historique de slugs de services (accents, collisions) |

## Positionnement de Notify Switchboard (factuel)

1. **Seul à compléter `alert` core** : acquittement → `alert.turn_off` avec
   allow-list, mode observer sur les transitions, services legacy par cible
   via `targets` (aucun voisin n'utilise `targets`).
2. **Proxy pur** : pas de canal, pas de moteur de conditions maison, pas de
   panel custom ; la présence, les plages et le DND sont des entités HA
   existantes (`person`, `schedule`, `input_boolean`).
3. **Persistance et traçabilité** : snoozes et report de nuit via `Store`
   (Supernotify et smart-presence perdent au redémarrage) ; compteurs de
   drops **avec raisons** (aucun voisin ne les expose).
4. **Config flow standard**, pas de panel : la leçon Ticker (#38/#43/#51 :
   navigation Companion cassée) et le bug d'édition concurrente (#46).

## Leçons injectées dans le Sprint 1

- **Slugs** : normaliser (`slugify`) et refuser les collisions au config flow ;
  tester accents/apostrophes (Notify-for-HA).
- **Rien en RAM seule** : snoozes, reports, dédup par `tag` → `Store` (leçons
  Supernotify, smart-presence).
- **Jamais de SQLite parallèle** au recorder (messages_store).
- **Un message hors plage n'est jamais perdu** : reporté ou compté comme drop
  avec raison (Email-Notify-Manager).
- **Pas de panel custom** ; config flow + options flow, tuiles natives (Ticker).
- **Édition concurrente** : options flow atomique, validation de schéma
  complète avant écriture (Ticker #46).
- **i18n dès la v0.1** (demande récurrente non servie chez Ticker).
- Demandes Ticker non couvertes à surveiller : latence (#65), TTS sur
  satellites Assist (#67), passthrough vers un script (#47) — le passthrough
  est trivial pour un proxy (`notify.*` group ou script en sortie via un
  `notify` de façade).

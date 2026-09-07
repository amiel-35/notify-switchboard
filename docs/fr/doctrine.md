# Doctrine — suite de notifications pour Home Assistant

Résumé des principes en vigueur pour Notify Switchboard et sa suite
(intégration custom Home Assistant). L'historique des décisions (dates,
alternatives écartées, correctifs) vit dans les ADR anglais du dépôt
(`docs/ADR/`) et dans [`../ARCHITECTURE.md`](../ARCHITECTURE.md) ; ce
document ne raconte pas comment on y est arrivé, seulement où on en est.

## 1. Pourquoi

Home Assistant fournit déjà les briques d'un système de notification :
`alert` pour un état qui dure (répétition, acquittement, retour à la
normale), `event` et les automatisations pour un fait ponctuel, `person`
pour la présence, `schedule`/`input_boolean` pour les plages de silence, et
`notify` comme contrat d'envoi universel. Ce qui manque nativement est une
couche de distribution par personne : qui doit être prévenu, et quand.
Notify Switchboard est cette couche, posée devant `notify.*` sans rien
remplacer.

## 2. Principes

1. **Natif d'abord.** Le routeur lit l'état que Home Assistant modélise déjà
   (présence, silence, alerte) ; il ne le possède pas. Quand une brique
   native suffit, on l'utilise plutôt que d'ajouter une option au routeur.
2. **Un proxy, pas un canal.** Le routeur n'envoie jamais rien lui-même ; il
   appelle des services `notify.*` qui existent déjà. Aucun appel réseau
   sortant propre à l'intégration, aucune dépendance externe.
3. **Deux natures, pas trois.** *Persistant* : un état qui dure jusqu'à ce
   que quelque chose le change — une `alert`. *Information* : un fait
   ponctuel — un événement ou un appel `notify` direct. Urgence,
   destinataire et droit de réveiller sont des attributs de l'appel, pas une
   troisième nature.
4. **La voix est une sortie comme une autre, jamais une alerte par défaut.**
   Une enceinte devient un service `notify.*` via la plateforme native
   `notify: platform: tts` du cœur de Home Assistant, visée sur un lecteur
   Music Assistant pour obtenir pause/reprise. C'est la voie recommandée : il
   n'existe plus d'adaptateur dédié pour Cast ou AirPlay dans cette suite,
   le cœur couvrant déjà ce besoin. Seul `assist_satellite` — qui n'a pas de
   plateforme `notify` native — garde un adaptateur séparé, Assist Satellite
   Notifier, maintenu mais sans développement actif. Que ce soit via `tts`
   ou via ce satellite, une sortie voix n'est jamais câblée à une alerte par
   défaut : le choisir est un acte de configuration explicite, cible par
   cible.
5. **Rien ne doit être lu à voix haute sans y penser.** Un texte dérivé d'un
   `alarm_control_panel.*` ou d'un `lock.*` ne doit jamais atteindre une
   sortie voix. C'est une règle de configuration documentée, pas une
   garantie que le code applique à la place de l'utilisateur.
6. **Générique et configurable.** Rien de spécifique à l'installation d'un
   foyer particulier dans le code : ni nom, ni pièce, ni appareil. Les
   exemples de la documentation sont des exemples, jamais des constantes.
7. **Chaque dépôt vit seul.** Le routeur (`notify-switchboard`) et l'adaptateur
   voix restant (Assist Satellite Notifier) sont deux dépôts indépendants,
   chacun avec son propre cycle de publication. Le contrat qui les relie est
   celui de Home Assistant lui-même — les services `notify.*` — jamais un
   couplage de code entre les deux.

## 3. Ce que le routeur fait, en une phrase

Il reçoit un appel (`message`, `title`, `data`), consulte sa table de
routage, décide par personne — présence, silence, snooze, priorité — et
appelle les sorties `notify.*` retenues. Il conserve un minimum d'état
propre (snoozes, silences temporaires, épisodes d'alerte) pour tenir ses
promesses — pas de rappel en double, pas de message « retour à la normale »
envoyé à qui n'a jamais reçu l'alerte — mais rien de plus. Le contrat exact
(noms figés, ordre de décision, ce que chaque option change) vit dans
[`../contract.md`](../contract.md), gelé au sens de l'ADR-0011.

## 4. Standards techniques, en résumé

Intégration HACS classique : `config_flow` obligatoire, migrations de
`ConfigEntry` dès la première version, identifiants d'entité stables et
traduits (anglais figé, français et espagnol pour l'affichage). Tests par
`pytest-homeassistant-custom-component`, couverture élevée sur le moteur de
décision, suite d'acceptation gelée une fois publiée. CI bloquante sur
`main` (format, lint, types, `hassfest`, tests). Aucun secret ni donnée
personnelle dans le dépôt ; les diagnostics exportés sont expurgés.

## 5. Ce que cette doctrine ne couvre pas

Les choix de configuration propres à une installation donnée (qui est dans
l'audience de quelle cible, quelles priorités, quelles heures de silence) ne
vivent pas ici : ce sont des réglages, pas une doctrine. Cette page ne
décrit pas non plus le déroulé des versions passées — c'est l'objet du
`CHANGELOG.md` et des ADR anglais.

---
title: "18 Raton : scénarios et répliques de la page d'accueil"
---
# 18 Raton : scénarios et répliques de la page d'accueil

Raton est l'assistant de la page d'accueil (`/`). Cette page décrit comment il
choisit ce qu'il dit et quel dessin il montre, et sert de carnet d'idées : tout
ce qui est prévu y figure, branché ou non, avec le dessin encore à faire.

La source de vérité du code est le catalogue `CATALOGUE` de
`back/services/raton/scenarios.py`. Ce document le reprend ; en cas d'écart, le code et cette
page doivent être corrigés dans le même changement.

## Place dans l'accueil

Raton est la partie haute de `/` ; la barre de chat est
décrite dans [11 Interface HTML](11-interface-html.md#accueil).

## Principe

Une **visite** commence après 30 minutes sans charger `/`. Chaque chargement de
`/` dans une visite affiche une phrase, selon un déroulé fixe :

1. **Longue absence** (1er chargement uniquement) : si la dernière visite date de
   2 jours ou plus, une phrase du scénario `longue_absence`.
2. **Accueil horaire** : une phrase tirée au hasard parmi les scénarios de moment
   dont la condition tient (5 h–9 h, 9 h–12 h, 12 h–14 h, 22 h–minuit,
   minuit–5 h). C'est le 1er chargement s'il n'y a pas d'absence, le 2e sinon. Si
   aucune plage ne tient (par exemple 15 h), on passe directement à l'étape 3.
3. **Tirage au hasard**, pour tous les chargements suivants : une phrase parmi
   celles de `ecran_ferme`, `nouveautes` et `defaut` dont le scénario tient
   (`nouveautes` ne tient pas entre 22 h et 5 h).
   **`ecran_ferme` est prioritaire** : tant que la limite du jour est atteinte,
   seules ses phrases sortent. Une phrase déjà vue dans la visite ne revient pas ;
   quand tout a été vu, un nouveau tour commence, sans rejouer la phrase qui vient
   d'être affichée.

Autres règles :

- Un scénario porte **plusieurs phrases** ; chacune peut avoir son propre dessin
  (à défaut, celui du scénario).
- Chaque phrase s'affiche avec son dessin ; la mention « Limite de temps d'écran atteinte aujourd'hui »
  (scénario de fermeture) et un éventuel bouton sont ceux de son scénario. Il n'y a pas de ligne secondaire.
- Un scénario parqué (`active=False`) garde son déclencheur, sa réplique et le
  brief de son dessin, mais n'est jamais tiré.
- Il n'y a pas de ton : toutes les phrases valent pour tout le monde.
- **Seules les phrases listées ci-dessous existent** : une phrase se retire du
  tableau, elle ne se désactive pas ; un scénario sans phrase retenue est parqué.

## Scénarios actifs

| Étape | Id | Déclencheur | Phrases | Dessin |
|---|---|---|---|---|
| 1. Absence | `longue_absence` | Dernière visite il y a 2 jours ou plus | « 2j sans toi. Le raton a eu le temps de ranger. » | `rangement.webp` |
| 2. Accueil | `matin_tot` | Première visite du jour, de 5 h à 9 h | « Le raton n'est pas du matin, mais il est là. » · « Déjà debout ? Le raton cherche encore son café. » · « Tôt, hein ? Le raton est là, à moitié. » · « Déjà là ? Même le café n'est pas prêt. » | `cafetiere.webp` |
| 2. Accueil | `matin` | Première visite du jour, de 9 h à 12 h | « Va bosser, on bingera après. » | `dossiers.webp` |
| 2. Accueil | `minuit_passe` | Entre minuit et 5 h | « Tu me réveilles pour regarder quoi encore comme connerie ? » · « Les vidéos seront encore là demain. Le sommeil, lui, ne se rattrape pas. » (`hamac_dos.webp`) | `bonnet_nuit.webp` |
| 3. Tirage | `ecran_ferme` | 100 % de la limite du jour d'un type de contenu ; prioritaire dans le tirage | « C'est tout pour aujourd'hui. Je ferme boutique. » ; mention « Limite de temps d'écran atteinte aujourd'hui » (sans jauge) et bouton « Voir l'historique » vers `/dashboard/historique` | `rideau.webp` |
| 3. Tirage | `nouveautes` | Au moins une fiche `is_new`, et pas entre 22 h et 5 h | « Il y a du nouveau, Chef. » (`journal.webp`) · « Tes youtubeurs ont bossé pendant que tu dormais. » (`laptop.webp`) · « Le facteur est passé. Il a laissé du contenu. » (`facteur.webp`) ; bouton « Voir les nouveautés » vers `/dashboard/nouveautes` | `journal.webp` |
| 3. Tirage | `defaut` | Toujours vrai | « Alors, qu'est-ce qu'on s'envoie aujourd'hui ? » | `popcorn.webp` |

Seuils : `LONG_ABSENCE_DAYS` et `CLOSING_RATIO` en tête de
`back/services/raton/scenarios.py`, `SESSION_GAP` en tête de
`back/services/raton/visits.py`.

Données utilisées :

Tout est celui de l'utilisateur courant (voir
[12 API et routes](12-api-et-routes.md), « Utilisateur d'une requête ») :

- **Temps d'écran** : ses lectures `played` du jour (même calcul que Paramètres) et
  ses limites journalières par type (`screen_time_<kind>_today_limit_minutes`). On
  retient le type dont le ratio est le plus élevé (déclenchement de la fermeture).
- **Nouveautés** : ses fiches `user_videos.is_new` sur les chaînes dont sa cloche
  du type (vidéos ou shorts) est active, comme la page `/dashboard/nouveautes`
  (`followed_video_condition`).
- **Dernière visite** : ses réglages `raton_last_seen_at` et
  `raton_session_previous_visit_at`. Un écart de 30 minutes entre deux chargements
  ouvre une nouvelle visite.
- **Phrases déjà vues** : son réglage `raton_visit_shown`, liste JSON de clés
  `<id du scénario>:<rang de la phrase>`, remise à vide à chaque nouvelle visite.

## Page de test des variations

`GET /raton/variations` liste, sans condition, toutes les phrases de tous les
scénarios actifs, groupées par étape, chacune avec son dessin, sa mention de limite ou son bouton. Elle
sert à relire les phrases et à voir chaque rendu ; elle ne touche ni aux phrases
déjà vues ni aux dates de visite. Un lien y mène depuis Paramètres (carte
« Raton »).

## Idées parquées

| Id | Déclencheur | Réplique ou action | Dessin |
|---|---|---|---|
| `tard` | Entre 22 h et minuit | « Va te prendre un livre, ce n'est plus l'heure ici. » et deux autres | à dessiner : carnet |
| `pause_midi` | De 12 h à 14 h, avec une lecture dans la journée | « Pause déjeuner ? Fais digérer d'abord, regarde après. » et trois autres | à dessiner : chaise longue |
| `limite_proche` | 90 % de la limite du jour | « Molo l'ami. On a bien bingé à ce que je vois. » et deux autres | à dessiner : doigt levé |
| `quart_d_heure` | 15 minutes ou moins avant la limite | « Quinze minutes, pas plus. Fais-en bon usage. » et deux autres | à dessiner : regarde sa montre |
| `enchainement` | 3 lectures d'affilée sans pause | « Une dernière vidéo ? Tu dis ça depuis tout à l'heure. » | à dessiner : bras croisés |
| `prise_tiree` | Clic sur une lecture après la fermeture | « J'ai tiré la prise. Je suis désolé. Presque. » | à dessiner : débranche une prise |
| `telephone` | Limite dépassée, 2e passage du jour | « Juste balance ton téléphone. » | à dessiner : patte vers l'écran |
| `savais_tu` | Fiche liée aux notes ou à une vidéo récente | « Savais-tu que… » + lien vers la vidéo | `journal.webp` |
| `binge` | Hier : plus de 2 h ou plus de 5 fiches | Commentaire au cas par cas | `cinema.webp` |
| `tache_inachevee` | Tâche ou conversation inachevée | « Bonjour chef, on n'a pas fini. On y retourne ? » | à dessiner : tape du pied |
| `clavier_ia` | Tâche IA en cours | Raton tape au clavier (remplace le balancement) | à dessiner : au clavier |
| `chiffres` | Réponse qui contient des chiffres | « Les chiffres ne sont pas bons, vérifie par toi-même. » | à dessiner : calculatrice |
| `erreur` | Erreur de l'IA ou d'un téléchargement | Tête dans les mains | à dessiner : tête dans les mains |
| `a_reparer` | Page vide ou à réparer | Marteau et tournevis | à dessiner : marteau, tournevis |
| `meteo` | Dehors : la météo | « Va voir dehors, il connaît la météo, le malin. » | à dessiner : à la fenêtre |

`meteo` demande une source externe alors que l'application est pensée pour un
réseau local : à trancher avant tout développement.

## Dessins

Fichiers dans `front/static/img/raton/`, en WebP **encre sur fond transparent**
(l'opacité vient de l'obscurité du trait) pour que le dessin se pose sur le
fond crème de la page. Un nouveau dessin (fond blanc cassé en entrée) se
convertit de la même façon : niveau de gris inversé en canal alpha, couleur
unie `#2b2018`.

| Fichier | Dessin | Utilisé par |
|---|---|---|
| `journal.webp` | Raton lit le journal | phrases sans dessin propre |
| `rideau.webp` | Raton tire le rideau | `ecran_ferme` |
| `popcorn.webp` | Raton, lunettes 3D et popcorn | `defaut` |
| `cinema.webp` | Raton, lunettes 3D et popcorn (première version) | `binge` (parqué) |
| `rangement.webp` | Raton range des livres dans une bibliothèque | `longue_absence` |
| `dossiers.webp` | Raton porte une pile de dossiers | « Va bosser, on bingera après. » |
| `facteur.webp` | Raton en casquette de facteur, sacoche d'enveloppes | « Le facteur est passé. » |
| `laptop.webp` | Raton devant un laptop | « Tes youtubeurs ont bossé… » |
| `bonnet_nuit.webp` | Raton en bonnet de nuit au lit, un œil ouvert, lampe de chevet allumée | `minuit_passe` |
| `cafetiere.webp` | Raton, tasse à la main, devant une cafetière qui goutte | `matin_tot` |
| `hamac_dos.webp` | Raton couché dans un hamac, lune derrière | « Les vidéos seront encore là demain… » |

`missing_art()` dans `back/services/raton/picker.py` liste les scénarios sans dessin dédié ;
les dessins sont des fichiers du front (`front/static/img/raton/`), et un test vérifie que
chaque dessin déclaré y est.
Dessins à faire : les idées parquées ci-dessus.

## Ajouter ou brancher un scénario

1. Ajouter (ou modifier) une entrée dans `CATALOGUE`.
2. Pour l'activer : `active=True`, une `stage` (absence, accueil ou tirage) et une
   fonction dans `CONDITIONS` portant le même `id` (un test vérifie que les deux
   listes coïncident).
3. Déposer le dessin dans `front/static/img/raton/` et renseigner `art` ; une phrase
   qui a son propre dessin s'écrit `("texte", "fichier.webp")`.
4. Mettre à jour les tableaux ci-dessus.

## Limites du MVP

- La fermeture est un **message** sur l'accueil : elle ne bloque pas la lecture.
- L'heure est celle du serveur.
- Une seule réplique par affichage ; le tirage n'a de mémoire que dans la visite
  en cours, pas d'une visite à l'autre.
- Le panneau de suggestions « au focus du champ » reprend le menu existant de
  la barre de chat (quatre amorces de question), pas encore des questions
  complètes liées au scénario du jour.

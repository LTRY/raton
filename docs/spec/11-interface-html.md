---
title: "11 Interface HTML"
---
# 11 Interface HTML

## Base

Toutes les pages HTML etendent `base.html`.

CSS compile via Tailwind (pipeline de build, pas de runtime JS) - voir
"CSS (Tailwind)" dans
[04 Configuration et deploiement](04-configuration-et-deploiement.md).
Palette "chaleureuse et personnelle" (terracotta/ambre sur fond creme,
theme clair uniquement ; seul le mini-lecteur audio est sombre, couleurs en
dur) et police Plus Jakarta Sans (Google Fonts,
chargee depuis `<head>`), portees par des tokens CSS dans
`front/static/css/tailwind.input.css`.

Icone de l'application : le raton laveur aux lunettes 3D et au pop-corn,
`front/static/img/apple-touch-icon.png` (180 x 180, fond creme opaque : iOS
n'accepte pas la transparence) declaree par `<link rel="apple-touch-icon">`
dans `<head>`, et `favicon.png` (64 x 64) par `<link rel="icon">`. Sans
elle, « Ajouter a l'ecran d'accueil » affiche la simple lettre « P ». Le nom
sous l'icone vient de `apple-mobile-web-app-title` (« Raton »).

Navigation pilotee par Turbo Drive (`front/static/js/vendor/turbo.min.js`,
vendored, charge dans `<head>` avec `data-turbo-track="reload"`) : les clics
sur les liens et la plupart des soumissions de formulaire deviennent des
visites en arriere-plan (fetch + remplacement du `<body>`) au lieu d'un
rechargement complet, ce qui permet au mini-lecteur audio persistant (voir
[08 Medias et lecteurs](08-medias-et-lecteurs.md)) de continuer a jouer
pendant la navigation. Desactive, via `data-turbo="false"`
sur le `<form>` concerne, sur tout formulaire deja intercepte en JS
(`fetch` + `event.preventDefault()`) pour eviter une double soumission :
telechargement/import de chaine (`data-async-download`/`data-async-job`),
import de playlist par URL ou CSV (memes attributs, voir "Playlists"
ci-dessous), actions transcript (`data-transcript-action`), widget de chat
(`data-chat-form`/`data-chat-clear`), import CSV d'abonnements, étoiles de
notation (`form.rating-control`). Les formulaires simples (commentaire,
categories de chaine, parametres) ne sont pas exclus et beneficient de Turbo
sans changement de comportement.

Le surlignage d'une etoile de notation au survol (couleur du palier qu'elle
donnerait, leger decalage vers le haut) n'existe que sous `@media (hover: hover)` :
sur ecran tactile, un doigt qui effleure une etoile sans appuyer ne la
surligne pas (le `:hover` simule par le navigateur resterait colle).
Le focus clavier (`:focus-visible`) garde sa couleur.

Un formulaire POST qui redirige vers la page d'ou il a ete soumis (cloche de
suivi, ordre et contenu d'une playlist, commentaire,
categories...) rafraichit la page sans deplacer le
defilement : `<meta name="turbo-refresh-scroll" content="preserve">` dans
`<head>`, et `app.js` force l'action Turbo `replace` quand la redirection
revient sur le meme chemin (meme si la query string differe, par exemple
`?message=...`), y compris pour une redirection d'erreur (`level=error`) :
la notification flottante reste visible quel que soit le defilement. Une
redirection vers une autre page reste une navigation normale. Le
tirer-pour-rafraichir, qui recharge la page courante, conserve lui aussi le
defilement.

### Aucun defilement horizontal de page sur telephone

Regle de design valable pour toute page et tout composant : sur telephone
(iPhone/Safari en premier), la page ne bouge jamais lateralement. Elle n'est
jamais plus large que l'ecran et un glissement ne revele pas de vide a
droite.

- Un contenu plus large que l'ecran (carrousel, tableau, bloc de code,
  pastilles de filtre) defile **dans son propre conteneur**
  (`overflow-x: auto`), jamais dans la page.
- Un enfant de grille ou de flex qui contient un tel contenu, un `select` ou
  un `input` declare `min-width: 0` (grille : `minmax(0, 1fr)`), sinon il
  elargit son parent au-dela de l'ecran.
- Les chaines longues sans espace (URL, titres, noms de fichier) passent a la
  ligne (`overflow-wrap: anywhere`) ou sont tronquees ; pas de largeur fixe
  superieure a ~320px hors d'un conteneur defilant.
- `html` et `body` portent `overflow-x: clip` comme filet de derniere
  chance (`clip` ne cree pas de conteneur de defilement, donc `position:
  sticky` continue de fonctionner). Ce n'est pas la correction : l'element
  qui deborde doit etre contraint.
- Verification : a 390px de large, `document.documentElement.scrollWidth`
  vaut `clientWidth`.

### Temps de chargement des pages

Regle valable pour toute page : elle ne doit pas etre longue a charger, et le
temps de chargement ne doit pas croitre avec la taille de la bibliotheque.

- Le nombre de requetes SQL d'une page ne depend pas du nombre de lignes
  affichees : les relations lues par le template sont chargees d'avance
  (`selectinload`/`joinedload`), jamais une requete par ligne.
- Une table qui grossit a chaque lecture (`download_jobs` de statut `played`)
  n'est jamais lue en entier pour un calcul qui ne regarde qu'une periode :
  `recent_played_jobs` (`back/services/videos/playback.py`) borne la lecture aux 30 jours
  des temps de lecture (aujourd'hui/7 jours/30 jours) et charge les videos
  d'un coup. `/settings` et `/dashboard/historique` l'utilisent.
- Un fichier du disque (`metadata.json`, transcript) n'est pas relu pour chaque
  ligne d'une liste. Une carte (`downloaded_video_card`, `back/services/videos/library_view.py`) ne lit aucun fichier :
  sa duree vient de `videos.duration_seconds`. Le media est parfois monte depuis une VM
  (Docker sur macOS) ou un `metadata.json` de ~140 Ko coute 20 a 100 ms a froid : le relire
  pour 100 cartes rendait `/dashboard/nouveautes` et `/videos` longs de
  plusieurs dizaines de secondes.
  Les pages `/playlists` et `/playlists/{id}` suivent la meme regle (duree et tri
  par duree depuis la colonne, `items`/`video`/`channel` charges d'avance).
  Les couvertures de `/playlists` sont chargees en une requete et rattachees a
  leur element (`list_playlists`, `back/services/playlists/listing.py`) : la
  carte d'identite de la session ne garde que des references faibles, s'y fier
  coutait une requete par playlist. L'export CSV d'une playlist
  (`playlist_csv_export`) charge aussi ses elements et leurs fiches d'avance
  (il coutait une requete par fiche).
- Verification : `tests/test_page_load.py` fixe un plafond du nombre de
  requetes pour une bibliotheque de 150 lectures, et verifie que `/`,
  `/dashboard/nouveautes`, `/videos`, `/playlists` et `/playlists/{id}` n'ouvrent aucun `metadata.json`,
  et que le cout de `/playlists` ne grandit pas avec le nombre de playlists.

### Mesurer une page lente

Une page lente peut perdre son temps dans le SQL, le rendu, l'attente d'un
thread, un CPU ou une VM saturee : le profil d'une seule page ne les distingue
pas. `RequestTimingMiddleware` (`back/core/request_timing.py`) ecrit donc, pour
chaque requete, une ligne `raton.timing` :
`GET /dashboard/nouveautes -> 200 312 ms (sql 13 stmts, 41 ms)`.

- Un ecart important entre le temps total et le temps SQL signifie que le
  temps est perdu hors des requetes (Python, threads, hote).
- Une requete de 1 s ou plus passe en `WARNING` (`SLOW ...`) avec la memoire
  (`rss`), le nombre de threads et la charge (`load`) du process.
- Les memes chiffres sont dans l'en-tete `Server-Timing` (onglet Reseau des
  outils du navigateur). Les vignettes et fichiers statiques ne sont logges que
  lorsqu'ils sont lents.
- `LOOP-LAG` : la boucle d'evenements s'est reveillee avec 0,5 s de retard ou
  plus (quelque chose l'a bloquee, ou le CPU n'etait pas disponible).
- Lire les lignes : `docker compose logs app | grep -E "SLOW|LOOP-LAG"`.

### Polices et compression

- La police Plus Jakarta Sans est servie par l'application
  (`front/static/fonts/*.woff2`, police variable 200-800, licence OFL, sous-ensembles
  `latin` et `latin-ext`), declaree par `@font-face` dans
  `front/static/css/tailwind.input.css` avec `font-display: swap`, et prechargee
  depuis `<head>`. Aucune requete vers un autre domaine n'est necessaire pour
  afficher une page : l'application fonctionne hors ligne.
- Les reponses texte (HTML, CSS, JS, JSON, SVG) de plus de 1 Ko sont compressees
  en gzip quand le navigateur l'accepte (`TextGZipMiddleware`,
  `back/core/compression.py`). Les flux audio/video et les images ne le sont
  jamais : deja compresses, et la compression casserait leurs `Range`.

### Vignettes des cartes

La vignette d'une carte video (`video_card`, `_macros.html`) est une `<img>`
`loading="lazy"` `decoding="async"` avec `srcset` sur les copies reduites
(`/api/videos/{id}/thumbnail?w=320` et `?w=640`, voir
[08 Medias et lecteurs](08-medias-et-lecteurs.md)), jamais un `background-image`
(qui ne se charge pas a la demande). `sizes` est volontairement un peu sous la
largeur reelle (100 px sur telephone) : un iPhone 3x prend alors la copie 320
plutot que la 640, indiscernable a cette taille. Le navigateur choisit la copie,
le serveur ne detecte pas l'appareil.

### Notifications flottantes

Toute notification de la plateforme (resultat d'une action, erreur) est une
notification flottante `.toast`, jamais un bandeau dans le contenu de la
page :

- emplacement unique `.toast-stack`, rendu par `base.html` : fixe en haut a
  droite sous l'en-tete sur ordinateur, sur toute la largeur en haut de
  l'ecran sur telephone ; plusieurs notifications s'empilent ;
- `base.html` y rend le parametre `?message=...` de la page (variables de
  contexte `message`/`message_level`) : succes par defaut (`role="status"`),
  erreur avec `level=error` (`.toast.error`, `role="alert"`, lisere rouge).
  Les gabarits de page ne rendent pas `message` eux-memes ; une page ajoute
  une notification propre via le bloc Jinja `toasts` ;
- un resultat qui arrive sans chargement de page (fin de la generation IA
  sur `/videos/{id}`) y ajoute sa notification cote client avec
  `window.showToast(message, level)` (`app.js`), meme rendu et meme duree ;
- fermeture par le bouton "×" ou automatique apres 8 s, erreurs comprises ;
- `app.js` (`initToasts`) retire de l'URL, des l'affichage, les parametres
  declencheurs listes dans `data-toast-param` (`message level`), pour qu'un
  rechargement ne reaffiche pas la notification ; `data-turbo-temporary`
  l'exclut du cache Turbo ;
- les messages d'etat propres a un bloc restent en place dans la page
  (`.notice`, `.async-form-status`) : absence de fichier `.vtt`, statut du
  dernier scan dans les parametres, erreur du panneau de recherche YouTube,
  erreur de recuperation des fiches d'une chaine, progression d'un
  traitement en file d'attente.

Les étoiles de notation (videos et chaines) enregistrent la note en `fetch`
et sont repeintes sur place : la page n'est pas rechargee et le defilement
ne bouge pas. Toutes les étoiles de la meme video ou chaine presentes sur la
page sont mises a jour ensemble ; en cas d'echec la note precedente est
reaffichee. Une liste triee ou filtree par note n'est pas reordonnee avant le
prochain chargement de la page.

Le prefetch au survol de Turbo 8 (declenche une vraie requete GET des
qu'un lien reste survole ~100ms, avant tout clic) est desactive globalement
via `<meta name="turbo-prefetch" content="false">` dans `<head>`. Sans ce
meta, survoler une carte video sur le dashboard declenchait un GET reel sur
`/videos/{id}`, qui effacait `is_new` (voir "Cloche de suivi quotidien" dans
[02 Fonctionnalites](02-fonctionnalites.md)) sans navigation reelle — le
label **Nouveau** disparaissait au simple survol (la fiche, elle, reste
affichee dans sa pile tant qu'il y a des videos a montrer — voir
"Nouveautes par chaine" plus bas). Verifie present dans le bundle vendorise
(`mouseenter`/`prefetch`/en-tete `Sec-Purpose`).

La page d'une chaine (`channel_videos.html`) declare
`<meta name="turbo-cache-control" content="no-preview">` (via le bloc
`head_extra` de `base.html`). Sans cela, une seconde visite affichait
l'apercu du cache Turbo, cartes figees en pleine animation d'entree
(`channel-card-in`), puis la page fraiche les remplacait et relancait
l'animation de zero : les videos apparaissaient deux fois.

Les pages `playlists.html` (index) et `playlist_detail.html` (detail)
declarent le meme meta, pour la meme raison : leurs cartes et lignes ont une
animation d'entree (`pl-card-in`) qui se rejouait entre l'apercu du cache et
la page fraiche, donnant l'impression que la page se chargeait deux fois.

`front/static/js/app.js` est charge en fin de `<body>` (pas dans `<head>`) :
Turbo Drive re-execute les scripts de body a chaque visite, donc tout le
fichier est enveloppe dans une IIFE (sinon les `const`/`let` de premier
niveau declenchent une `SyntaxError` des la deuxieme page visitee).

Navigation principale :

- Accueil `/` : pas d'onglet dans la barre du haut, on y accede par le
  logo **Raton** (la barre d'onglets mobile garde un onglet
  **Accueil**) ; sur telephone (<= 800 px) la barre du haut, donc le titre
  **Raton**, n'est pas affichee : seule la barre d'onglets reste
- Chaines `/channels`
- Playlists `/playlists`
- Bibliotheque : menu deroulant **Bibliotheque** avec Import `/videos/import`
  (en premier), Nouveautes `/dashboard/nouveautes`, Historique `/dashboard/historique`
  et Exploration `/videos` (quatre liens, ni sous-bibliotheques ni Indexation RAG).
  Le panneau passe au-dessus du contenu de la page (la barre du haut a un
  `z-index` superieur a celui des avatars et bannieres de chaine)
- Parametres `/settings`
- Logs `/logs` (sur telephone, sans barre du haut ni onglet : par le lien
  « Voir tous les logs » de `/settings`)

Bouton d'import (`.import-fab`, `base.html`, toutes les pages) : un bouton rond
de 44 px en verre liquide (classe `lg` + `data-glass-light`), trois points
verticaux, fixe en haut a droite — sur telephone aussi, ou la barre du haut est
masquee. Il ouvre un menu en verre (`details[data-import-fab]`, ferme par
Echap, un clic dehors ou le choix d'une entree) avec les trois imports :
**Ajouter une vidéo** (`/videos/import`), **Ajouter une playlist**
(`/playlists#pl-add`, le panneau Ajouter) et **Importer des abonnements**
(`/channels?import=abonnements`, qui deplie le menu « + Ajouter » et
l'import CSV). Il passe sous les notifications (`z-index` 60 contre 70).

Barre d'onglets mobile (`.mobile-tabbar`, `front/templates/base.html`, visible
sous 800 px) : cinq onglets avec icone SVG seule (pas de libelle visible ; le nom de la page
est dans `aria-label`) — Accueil `/`, Chaines `/channels`,
**Bibliotheque** `/dashboard/nouveautes` (au centre), Playlists `/playlists`,
Reglages `/settings`. Il n'y a pas d'onglet Recherche : le champ de recherche
est dans Exploration. L'onglet Bibliotheque est actif sur `/videos*` et
`/dashboard/*`. Chaque icone a
sa propre animation (rebond, antenne qui se dessine, livre
qui saute, lignes de playlist, curseurs qui glissent), jouee au clic
(classe `.play` ajoutee par `app.js`) et au chargement de la page pour
l'onglet actif (classe `.active`) ; desactivee avec
`prefers-reduced-motion: reduce`. Les icones viennent du design « Icônes
menu » (claude.ai).

La barre est une **pilule flottante** detachee des bords (12 px de marge
laterale, rayon 34 px, onglet actif en pastille teintee) en « liquid glass » :
fond blanc tres transparent (environ 12 %, pour ne pas former une barre
blanche), leger flou (8 px) et forte saturation de ce qui passe dessous
(`backdrop-filter`, pour que les couleurs des vignettes restent visibles),
liseré clair et reflet interne en haut. Sans
`backdrop-filter`, elle garde un fond blanc quasi opaque. Elle reste dans la
bande de 72 px + zone sure que les pages reservent en bas.

Quand un champ texte a le focus (clavier a l'ecran ouvert), la barre est
masquee (`body:has(textarea:focus, [contenteditable]:focus, input…:focus)`, doublee
par la classe `html.keyboard-open` que `app.js` pose quand un champ est actif ou
que le viewport visuel retrecit de plus de 120 px) : elle ne flotte pas par-dessus
le clavier, comme le composeur d'une application de messagerie native. Les 72 px
que la page et le composeur colle reservent pour la barre sont rendus en meme temps
(pas de vide entre le champ et le clavier). La barre
blanche ‹ › ✓ d'iOS (barre d'accessoires de formulaire) n'apparait que pour
`<input>`/`<textarea>` : le champ du composeur de discussion est donc un
`<div contenteditable="plaintext-only">` (`.chat-input`), un `<textarea hidden>`
portant le texte jusqu'au `FormData`.

Le meme verre habille les couches flottantes : menu Bibliotheque de la barre
du haut, notifications, feuille « Idees de Raton », bulle de l'exploration, bouton
de la replique de Raton, et le mini-lecteur audio (verre fume, reste sombre).
Chaque regle est sous `@supports (backdrop-filter)` et garde son fond opaque
sinon.

### Verre liquide

Les surfaces de verre partagent des variables posees sur `:root` de
`front/static/css/tailwind.input.css` : `--glass-fill` (barres et controles),
`--glass-fill-strong` (couches qui portent du texte), `--glass-rim`,
`--glass-highlight`, `--glass-blur`, `--glass-blur-layer`, `--glass-saturate`,
`--glass-fill-opaque` (feuilles qui doivent cacher ce qui est derriere) et
`--glass-smoke`, `--glass-smoke-rim`, `--glass-saturate-smoke` (mini-lecteur sombre).
Les reglages du composeur (`--glass-inertia`, `--glass-radius`…) restent portes
par `.chat-composer`.

- **Classe `.lg`** : la recette complete (fond translucide, flou et saturation,
  liseré, reflet interne, ombre chaude) pour un controle qui n'a pas de regle de
  verre propre. L'attribut `data-glass-light` y ajoute la lumiere qui suit le
  pointeur (`initGlassLight`, `--gx`, `--gy`, `--glow`). Sans `backdrop-filter`,
  la surface garde le fond translucide `--glass-fill-strong` (pas de flou).
  `.lg` ne pose ni `overflow` ni de `position`
  autre que `relative` a specificite nulle (`:where`), et la lumiere est liee
  aussi aux fragments `turbo-frame` charges apres coup.
- **Fond ambiant** : trois halos chauds (terracotta, ambre) fixes derriere toute
  la page (`body::before`, `position: fixed`, `z-index: -1`). Sans eux, le verre
  sur la creme uni se lit comme une simple carte blanche. Ils ne changent aucune
  mise en page, ne captent aucun clic et sont masques a l'impression et sur telephone.
- **Telephone (sous 800 px)** : pas de halos, le fond est la creme unie
  (`--color-bg`), et `<meta name="theme-color">` (`base.html`, limite aux
  telephones par `media="(max-width: 800px)"`) porte la meme couleur, ce que
  `tests/test_glass_css.py` verifie : la bande que Safari teinte en haut de l'iPhone (heure, batterie)
  et la page ne forment qu'une seule surface, sans raccord visible.
- **Limites** : pas de `backdrop-filter` sur chaque carte d'une longue liste (le
  flou se paie par element, voir « Temps de chargement des pages ») ; pas de
  verre imbrique (l'enfant ne floute que son parent) ; le texte sur verre est
  `--color-text` ou `--color-primary`, jamais `--color-text-muted`.
- **Controles en verre** (classe `lg` posee dans les templates, regles de
  cohabitation en fin de `tailwind.input.css`) :
  - la barre du haut (`.topbar`, bureau seulement) est une pilule flottante
    collante (`position: sticky`, `top: 12px`, marges de 28 px, rayon 22 px).
    Tant que le menu Bibliotheque est ouvert, la barre perd son flou
    (`:has(.nav-library-menu[open])`) : le menu a son propre verre, et un flou
    imbrique ne verrait que le fond de la barre ;
  - les pastilles de sous-navigation de la bibliotheque (`library_subnav` et les
    vues enregistrees de `/videos`) ; l'etat courant (`aria-current` ou
    `.active`) garde sa teinte chaude, plus de bleu plein ;
  - les liens-boutons `.button-link` (Retour, Precedent/Suivant, Cout LLM…) :
    texte `--color-primary` sur verre, plus de bleu ni d'ardoise.
- **Barre d'enregistrement des parametres** (`.settings-actions`, collante en
  bas) : verre, comme le composeur collant.
- **Cartes** : pas de `backdrop-filter` (le flou se paie par element). Les
  lignes d'historique (`.dashboard-media-row`) prennent un fond translucide, le
  liseré clair, le reflet interne et l'ombre chaude ; les paliers « vu » et
  « ecartee » gardent leur fond plat. Les vignettes de la grille (conteneur
  d'au moins 461 px) ont un liseré et une ombre chaude.
- **Panneaux et blocs de formulaire** (`.settings-card`, `.stats-card`,
  `.filters-form`, `.download-form`, `.filter-collapse`, `.log-list`,
  `.metrics div`…) : meme traitement que les cartes, sans flou ; la bordure garde
  sa couleur pour que le bord reste lisible sur la creme.
- **Palette** : plus de gris ardoise ni de bleu. Textes `--color-text`,
  `--color-text-soft` (descriptions), `--color-text-muted` ; bordures
  `--color-border` et `--color-border-strong` (zones pointillees, champs) ; etats
  actifs, liens et anneaux de focus en `--color-primary` / `--color-ring`. Seuls
  restent les metaux des paliers de notation (`.rating-tier-*`).
- **Jetons** : une couleur qui se repete porte un nom dans `:root`
  (`--color-white`, `--color-tint`, `--player-surface`…) ou dans `@theme`, et les
  rayons suivent l'echelle `--radius-xs` (6 px), `--radius-sm` (8), `--radius-10`,
  `--radius-md` (12), `--radius-14`, `--radius-16`, `--radius-lg` (18),
  `--radius-22`, `--radius-28`, `--radius-xl` (34), `--radius-pill` (999). Seuls
  `0`, `1px` a `5px`, `50%` et `inherit` restent ecrits en dur. `tests/test_glass_css.py` fixe un plafond au
  nombre de lignes qui ecrivent encore une couleur hexadecimale : il ne peut que
  baisser (metaux de notation, palettes des categories et des etiquettes, series
  des graphiques, lecteur).
- Test : `tests/test_glass_css.py`.

Bibliotheque = quatre vues reliees par une barre de sous-navigation commune
(macro `library_subnav` de `_macros.html`, `.library-subnav`) : **Import**
`/videos/import`, **Nouveautes**
`/dashboard/nouveautes`, **Historique** `/dashboard/historique`,
**Exploration** `/videos`.
- Toute date affichee dans l'interface utilise le format francais long
  `Lun. 20 juil. 2026` (jour abrege + point, jour, mois abrege + point,
  annee), et `Lun. 20 juil. 2026 14:32` quand une heure est jointe. Fonctions
  `format_french_date`/`format_french_datetime` (`front/pages.py`,
  exposees comme globals Jinja) ; ne pas utiliser `isoformat()`/`strftime()`
  bruts dans les templates. `created_at.isoformat()` reste utilise tel quel
  dans les reponses JSON de `/api` (pas concerne).

## Statistiques

Template : `stats.html`, route `GET /stats` (`front/routes/stats.py`),
agregations dans `back/services/videos/charts.py`. Page sans JavaScript : les
graphiques sont des barres CSS (largeurs/hauteurs en pourcentage calcule cote
serveur). Elle montre :

- stockage utilise, quota et repartition videos / shorts ;
- stockage par chaine (top 10, le reste regroupe dans "Autres (n)") ;
- fiches par chaine (meme regle) ; dans ces deux cartes, le nom d'une chaine
  est un lien vers `/videos?channel_id=<id>` (page de la chaine) ; les lignes
  "Autres (n)" et "Sans chaine" restent du texte simple (`channel_id` nul) ;
- fiches par format (video seule, audio seul, video + audio, sans media) ;
- fiches ajoutees par mois (une phrase de synthese, trois chiffres cles : mois
  en cours avec variation vs le mois precedent, rythme moyen par mois, volume
  de medias ajoute ce mois-ci ; la valeur est ecrite sur chaque barre, le mois
  en cours est mis en avant) et stockage cumule (courbe en aire SVG avec le
  total en grand) sur les 12 derniers mois. La page ecarte les premiers mois
  sans aucune fiche (`monthly_view`) ; `GET /api/stats/charts` garde la
  fenetre complete de 12 mois.

- medias supprimes automatiquement par mois (`purged_media_by_month`,
  `back/services/videos/charts.py`) : barres du nombre de videos dont la purge
  (`purge_watched_media`) a supprime les fichiers, comptees depuis les
  lignes `purged` de `download_jobs`, sur 12 mois sans les mois vides en tete ;
  total / mois en cours / moyenne en tete ; la carte est absente tant qu'aucune
  purge n'a eu lieu. Le poids libere n'est pas enregistre, donc pas affiche ;
- depenses en modele par mois (`llm_spend_by_month`, `back/services/llm/usage.py`) :
  barres empilees par groupe de jobs (notes et resumes, nettoyage de
  transcript, discussions, autres), cout total au-dessus de chaque barre,
  total / mois en cours / moyenne en tete. Cout reel des `llm_jobs` ayant un
  `cost_usd`, range par mois de creation, sur 12 mois sans les mois vides en
  tete ; la carte est absente tant qu'aucun cout n'est enregistre. Le detail
  par type et par modele reste dans `/settings`.

Les courbes dans le temps sont reconstruites depuis les fiches existantes
(`downloaded_at`, sinon `created_at`) : elles montrent ce qui est sur disque
aujourd'hui classe par date d'ajout, pas un historique reel de l'occupation
(les medias purges ne comptent plus). Il n'y a pas de table de
snapshots.

## Indexation RAG

Template : `rag_dashboard.html`, route `GET /rag` (`front/routes/stats.py`),
donnees dans `back/services/rag/dashboard.py` (`rag_dashboard_data`). Lien
"Indexation RAG" dans une carte de `/settings` (ancre `#rag`). Page de lecture sans JavaScript,
construite avec les cartes et barres CSS de `/stats` ; elle repond a "ou en
est l'indexation des notes et que va faire le passage de la nuit ?" et sert
aussi d'explication du fonctionnement (projet educatif). Elle montre, dans
l'ordre :

- quatre chiffres : videos indexees sur indexables, taille du prochain lot
  (sur le plafond de 100) et delai avant le passage de 5 h `Europe/Paris`,
  videos du lot en cours chez Anthropic, videos en attente apres lui avec le
  nombre de nuits et le cout estime pour tout vider ;
- l'etape de chaque video : une seule case parmi indexee, dans le lot en cours,
  en attente, sans transcript, short, label exclu, abandonnee (3 echecs).
  La classification reutilise `auto_notes.skip_reason`, donc le "prochain lot"
  est exactement celui que soumettrait le passage ; seuls des faits de base de
  donnees sont lus (jamais de fichier) : "en attente" est un maximum, la taille
  du transcript et le fichier de notes etant verifies a la soumission ;
- le passage de la nuit : etat, prochain et dernier passage, resume, identifiant
  et date du lot, echeance d'abandon (36 h), presence des cles Anthropic et
  Voyage, labels exclus ;
- le prochain lot (15 premieres videos, repartition par chaine) et les videos
  du lot en cours ;
- l'activite des 14 derniers jours (jobs appliques / en echec / en cours par
  jour de soumission), le cout reel et les tokens moyens par video ;
- le contenu de l'index : chunks, taille moyenne, poids des vecteurs, chunks
  par section et par video ;
- la couverture des 10 chaines les plus fournies et les 8 derniers echecs ;
- un bloc "Comment ca marche" : les etapes du transcript au vecteur, la
  cascade de recherche avec les chiffres reels et un lexique. Les parametres
  affiches (taille du lot, candidats, top-k, seuil, modeles) sont lus dans le
  code, pas recopies.

Le nombre de requetes SQL est constant (une requete pour classer toute la
bibliotheque, des agregats pour le reste) : `tests/test_rag_dashboard.py`.

## Accueil

Template : `dashboard.html`

La page `/` se lit de haut en bas :

1. **Raton** : dessin, replique, mention de limite atteinte et bouton eventuels,
   choisis par le moteur de scenarios (voir [18 Raton](18-raton-scenarios.md)).
2. **La barre de chat de la bibliotheque**, centree sous Raton (voir "Widget de
   chat" ci-dessous). Le menu de suggestions ("Idees de Raton") ne s'ouvre
   jamais quand on touche ou focus le champ : seul le bouton + l'ouvre. Le
   clavier se ferme et le menu monte comme une feuille collee au bas de l'ecran
   (poignee, bouton ✕ rond, titre, une ligne par idee) sur un voile sombre ; ✕,
   Echap, le voile ou le choix d'une idee le referment.

La page ne porte rien d'autre : ni Reprendre, ni Nouveautes, ni Suggestions de
Raton (les Nouveautes restent sur `/dashboard/nouveautes`, l'historique sur
`/dashboard/historique`). Le contenu tient donc sur un ecran : Raton se centre
dans l'espace libre et la barre de chat reste collee au bas (au-dessus de la
barre d'onglets sur telephone).

Des qu'une discussion est affichee (`data-chat-empty="false"`), Raton est
masque : il ne reste que la conversation. Ni metriques, ni
Historique complet, ni temps de lecture : ils sont dans Bibliotheque et
Parametres.

## Bibliotheque : Import, Nouveautes, Historique, Exploration

Les quatre vues partagent le titre `Bibliotheque` et la sous-navigation
`library_subnav`.

**Import** (`/videos/import`, `import_video.html`) : le formulaire de
telechargement manuel par URL, sur sa propre page (il n'est plus un tiroir de
`/videos`). Champs : URL YouTube, deux
tuiles a cocher **Video** (MP4) et **Audio** (M4A), qualite video (segment
`360p` a `4K`/`Max`, visible seulement quand « Video » est coche), categories
(presets + custom). Les metadonnees et le transcript sont **toujours**
importes : le formulaire poste `media_type=metadata` et
`download_transcript=true` en champs caches, sans case a cocher. Ne rien cocher
importe seulement la fiche (metadonnees + transcript, sans fichier media). Il n'y a **ni langue ni source
de sous-titres** : la piste est toujours choisie par `choose_subtitle_track`
(voir [07 YouTube et telechargements](07-youtube-et-telechargements.md),
« Sous-titres : jamais de traduction automatique »). Le formulaire poste vers
`POST /api/videos/import` en asynchrone (`POST /videos/download` sans JavaScript) ; au succes, la page se recharge avec le
message du job.

Sous le formulaire, une **zone de depot** (`.import-dropzone`,
`form[data-local-upload]`) accepte un fichier video ou audio local, par
glisser-deposer ou par selecteur de fichier (touche sur telephone). L'envoi part
des que le fichier est depose (`XMLHttpRequest`, barre de progression) vers
`POST /videos/upload` ; au succes, la page redirige vers la fiche creee, en cas
d'echec le message d'erreur remplace l'indication de la zone. Le fichier n'a ni
transcript ni metadonnees YouTube.

**Nouveautes** (`/dashboard/nouveautes`, `dashboard_new_videos.html`) : une
pile (`.video-stack`) par chaine suivie (cloche videos `auto_metadata_enabled`
ou cloche shorts `auto_shorts_enabled` active) — pas seulement les
fiches marquees `is_new` : une fiche deja visitee (label **Nouveau**
efface) reste affichee tant qu'elle fait partie des videos les plus
recentes de sa chaine. Chaque cloche filtre son type : les videos ne sont
listees que si la cloche videos est active, les shorts que si la cloche
shorts est active. Le filtre sur les cloches preserve l'exclusion des
videos importees via playlist (chaine auto-creee sans cloche — voir
[07 YouTube et telechargements](07-youtube-et-telechargements.md)). Chaque
pile montre jusqu'a `NOUVEAUTES_STACK_SIZE` (10) videos triees par date de
sortie, navigables une a la fois via des fleches precedent/suivant
(`.video-stack-carousel`, scroll-snap), sans compteur de position ("1 / 10")
entre les fleches ; chaque video reutilise la meme carte
(macro `video_card`, même vignette pleine hauteur, même note, sans
labels) que la page `/videos`. Les piles sont
paginees par chaine (`NOUVEAUTES_CHANNEL_PAGE_SIZE` = 10 chaines par
page, triees par recence de leur derniere video, `macros.pagination`) ; elles sont accolees,
sans espace vertical : `.video-stack-list` porte le cadre et chaque pile
n'est separee de la precedente que par un filet.

**Historique** (`/dashboard/historique`, `dashboard_history.html`) : activite
de lecture recente, paginee (50 par page), decoupee en un bloc
`details.dashboard-day-group` repliable par journee de lecture (macro
partagee `history_day_list` dans `_macros.html`) — regles ci-dessous. Le temps de lecture y figure
deux fois : le carrousel de cartes « Temps de lecture » (macro
`playback_time_cards`, memes chiffres que `/settings` et que la barre de limite
de Raton) en haut de page, et, dans l'en-tete de chaque journee, le temps total
regarde ce jour-la (« 1 h 12 de lecture »). Ce total compte toutes les lectures
de la journee, alors que la liste ne garde qu'une ligne par media ; il ne
depend donc pas de la pagination.

### Historique groupe par journee

La vue `Historique` ne liste pas les lectures a plat : elle les regroupe
par jour de lecture (`DownloadJob.created_at`, ramene au fuseau local du
serveur comme les stats de temps de lecture — voir `history_day_groups` dans
`front/cards.py`). Chaque journee est un bloc repliable a part entiere qui
porte, dans son en-tete, le libelle du jour et le nombre de medias. Le rendu
est la macro `history_day_list` (`_macros.html`).

- Les deux jours les plus recents sont libelles `Aujourd'hui` et `Hier` ; au
  dela, l'en-tete affiche la date complete (`Mar. 17 juin 2025`). Quand le
  libelle est relatif, la date complete est affichee a cote.
- Sur `/dashboard/historique`, tous les blocs de la page courante sont
  ouverts (on y va pour parcourir, pas pour survoler).
- Le groupement se fait apres la pagination : les blocs d'une page ne
  couvrent que les lectures de cette page.
- L'ordre reste antichronologique, aussi bien entre les journees qu'a
  l'interieur d'une journee.
- La deduplication de `dashboard_media_activity_logs` (une ligne par video)
  reste globale : une video reprise plusieurs jours de suite n'apparait que
  dans le bloc du jour le plus recent.

Comme le bloc de journee porte deja la date, la ligne d'activite ne repete ni
`Publie le` ni `Vu le` : elle garde le titre, les labels, la chaine, la
progression, puis une derniere ligne avec le poids du fichier a gauche et les
actions Vu/Ecartee + la notation a droite.

### Barre de progression de lecture

Une carte video (macro `video_card`) ou une ligne `Historique` (`media_row`)
affiche une barre de progression de lecture (position/duree) tant que la
derniere lecture connue (`DownloadJob` de statut `played`) n'est pas
terminee et que la video n'appartient pas a une categorie "sans barre de
progression" (reglable dans `/settings`, cle `no_progress_category_labels`,
defaut **amv**/**musique** — voir « Parametres » plus bas).

- Lecture terminee (`is_completed`, calcule dans `playback_activity_view`/
  `back/services/videos/playback.py` a partir de la position et de la duree de lecture) et video
  hors de ces categories : la barre disparait et la carte est grisee
  (classe `video-row-watched` sur `/videos`/dashboard, `dashboard-media-row-completed`
  pour `Historique`) pour signaler que le media a ete vu en entier.
- Video appartenant a une categorie "sans barre de progression"
  (`video_category_labels` intersecte le reglage) : la barre disparait
  toujours, meme si la lecture n'est pas terminee, mais la carte n'est pas
  grisee (ces categories sont vues comme rejouables, pas comme "a marquer
  vu").

**Exploration** (`/videos`) : la liste de la bibliotheque decrite plus bas
(recherche, filtres, vues enregistrees).

## Parametres : statistiques et temps de lecture

Les statistiques de la bibliotheque (fiches, transcripts, chaines, chaines
actives, videos, shorts, medias, stockage utilise / quota avec jauge) et le
carrousel "Temps de lecture" sont des cartes de `/settings` (ancres
`#library-stats` et `#playback-time`), calculees par `library_stats_context`
(`front/routes/settings.py`, compteurs dans `back/services/videos/stats.py`). La carte stockage renvoie vers `/stats` (bouton
"Voir les graphiques").

Le carrousel "Temps de lecture" (`.screen-time-carousel`, periodes
aujourd'hui/7 jours/30 jours) n'accepte le changement de periode que via les
boutons precedent/suivant ou le scroll-snap programme (`scrollTo`) ; le
glisser tactile horizontal est desactive (`touch-action: pan-y`) pour que,
comme dans une app iOS, le seul geste de glissement disponible sur la page
reste le defilement vertical.

## Widget de chat (composant partage)

Macro `chat_widget(widget_id, title, config, extra_class="")` dans
`front/templates/_macros.html`, utilisee a la fois par la barre de la page d'accueil
(portee bibliotheque uniquement) et par la section discussion de
`/videos/{id}` (portee video uniquement, placeholder "Discuter du
contenu"). `title` vide (cas des deux pages) ⇒ ni icone, ni titre, ni sous-titre. Le rendu
HTML est statique (aucun message ni bouton de bascule genere cote serveur
au-dela du marquage) ; tout le rendu dynamique (messages, citations,
bascule de portee, soumission/poll) est gere par `initChatWidget`
(`front/static/js/app.js`), instancie automatiquement sur chaque element
`[data-chat-widget]` au chargement de la page a partir du JSON dans son
attribut `data-chat-config` :

```json
{
  "defaultScope": "video",
  "llmProviderLabel": "...",
  "scopes": {
    "video": {"chatUrl": "/api/videos/{id}/chat", "messages": [...]},
    "library": {"chatUrl": "/api/chat", "placeholder": "...", "suggestions": [{"label": "...", "prompt": "..."}], "messages": [...], "coverageNote": "..."}
  }
}
```

- Un seul scope dans `config.scopes` ⇒ pas de bascule affichee (cas du
  dashboard : `library` seul ; `/videos/{id}` : `video` seul). Deux scopes ⇒
  bascule segmentee "Cette video"/"Toute la bibliotheque" (aucune page ne
  l'utilise aujourd'hui, le support reste dans la macro).
- Mise en page : en-tete (icone, titre, `llmProviderLabel` en sous-titre,
  bascule de portee, bouton "Effacer" affiche seulement quand la portee
  courante a des messages), conversation, ligne de statut, puis le composeur.
  La conversation **coule dans la page** (aucun cadre a defilement interne :
  il piege le balayage sur iPhone) ; `initChatWidget` la suit vers le bas
  pendant qu'une reponse s'ecrit (`scrollIntoView`, debut du dernier message :
  une reponse longue se lit depuis sa premiere ligne), pas au chargement. Le
  composeur est `position: sticky` en bas de l'ecran (au-dessus de la tab bar
  sous 800px, `72px + env(safe-area-inset-bottom)`, soit 6px d'ecart avec la
  barre : le composeur colle a la barre, comme l'accueil vide) tant qu'une discussion est
  affichee ; vide, il reste a sa place dans la page. Sur telephone, l'accueil
  remplit l'ecran (`100dvh` moins la reserve de la tab bar) et le composeur vide
  se pose donc aussi a 6px de la barre. Des que le clavier est ouvert
  (`html.keyboard-open`), la reserve de la tab bar (72px + safe-area) est retiree
  de cette hauteur : sinon elle laisse entre le composeur et le clavier un vide
  de la meme taille. Avec le mini lecteur affiche,
  le `padding-bottom` de `main` est conserve (le composeur reste au-dessus du
  lecteur) et `--home-mini-reserve` (180px) est retranche de la hauteur.
- Messages : la bulle de l'utilisateur est a droite, sombre (espresso) ; la
  reponse de l'assistant n'a pas de bulle — texte a meme la page precede d'une
  pastille « etincelle » en degrade orange (le libelle « Vous »/« Assistant »
  reste pour les lecteurs d'ecran). Texte de 16px minimum (sous 16px Safari
  zoome la page au focus du champ).
- Composeur : carte arrondie (28px) avec le champ en haut (contenteditable auto-agrandi, voir « Barre
  d'onglets mobile ») et, dessous, le bouton « + » (suggestions) a gauche et le
  bouton d'envoi rond (fleche vers le haut, degrade orange) a droite, tous deux
  de 40px. La carte et le bouton « + » sont en « liquid glass » (fond blanc
  translucide, flou + saturation, liseré clair, reflet interne ; solide sans
  `backdrop-filter`) ; la page garde son fond uni. Le verre est « liquide » :
  - Matiere : fond translucide, flou + saturation, liseré conique de 1px
    (clair en haut a gauche, plus sombre en bas a droite, efface au focus au
    profit du contour orange), reflet interne, ombre portee chaude a deux
    couches, reflets orange fixes sur les bords haut et bas, grain tres leger
    contre le banding.
  - Lumiere : deux halos (un principal, un plus large, plus faible et plus
    lent) suivent le pointeur avec de l'inertie (`initGlassComposer` dans
    `app.js`, variables `--mx`/`--my` des couches de `.chat-glass`) ; hors de
    la carte, ils se posent sur le point le plus proche et s'eteignent sur
    150px. Une tache lumineuse court sur la bordure sous le pointeur, le halo
    se deporte de 10 % vers le bouton le plus proche, et le reflet interne du
    bouton « + » suit le pointeur. Reglages : variables `--glass-*` de
    `.chat-composer` (inertie, rayon, intensite 0,6, fondu, magnetisme, grain).
  - Etats : au focus, contour orange, echelle 1,01 avec ressort et halo plus
    intense (fondu de sortie en 250 ms) ; a l'appui, echelle 0,985 puis
    rebond et onde partant du point de clic ; chaque frappe fait pulser le
    halo.
  - Performance : seules `transform` et `opacity` bougent ; `will-change`
    n'est pose que tant que la boucle d'animation tourne. La carte n'a aucune
    `transform` au repos ni quand la feuille de suggestions est ouverte (une
    `transform` ferait de la carte le bloc contenant de la feuille fixe).
  - Tactile ou `prefers-reduced-motion: reduce` : halo fixe, sans suivi du
    pointeur, sans inertie ni ressort ni onde ; la page defile normalement
    sous le doigt.
  `Entree` envoie, `Maj+Entree` insere un retour a la ligne, et le bouton
  d'envoi reste desactive tant que la question est vide.
- Bouton d'appel de Raton (`.raton-cta`, ex. « Voir l'historique ») : meme verre
  que le composeur (bande speculaire, liseré, relief) et meme lumiere qui suit
  le doigt (`initGlassLight`, `--gx`, `--gy`, `--glow`), le reflet passant
  sous le libelle ; il ne bloque pas le defilement de la page.
- Sans message, aucun etat vide n'est rendu : la zone d'historique est
  repliee (`.chat-messages:empty`). Le widget porte `data-chat-empty`
  (`"true"`/`"false"`, rendu cote serveur puis tenu a jour par
  `initChatWidget`). Sur le dashboard et `/videos/{id}` (`.chat-bar`), la barre vide
  se reduit au seul champ de saisie : ni carte, ni en-tete, ni aide clavier ;
  la carte, le bouton "Effacer" et `coverageNote` n'apparaissent qu'une fois
  la discussion entamee.
- `placeholder` (optionnel) remplace le texte d'invite du champ pour la
  portee courante ("Demander…" pour `library`).
- `suggestions` (optionnel) : liste des demandes que l'assistant sait
  traiter. Quand la portee courante en a, un bouton "+" a gauche du champ
  ouvre un menu (`role="menu"`, fleches haut/bas, `Echap` ou clic exterieur
  pour fermer) ; choisir une entree pre-remplit le champ avec son `prompt`
  ("Ajoute la chaine de ") et y place le curseur, sans envoyer. Pour
  `library` : trouver une chaine, trouver une video, interroger les notes,
  ajouter une chaine YouTube (`LIBRARY_CHAT_SUGGESTIONS`,
  `front/library_chat.py`).
- A la soumission, la question est affichee immediatement en bulle et
  suivie d'une bulle "en train d'ecrire" ; les deux sont remplacees par la
  liste de messages renvoyee par le serveur (ou retirees par un nouveau rendu
  si la requete echoue).
- Pendant l'attente d'une reponse `library`, chaque poll `pending` renvoie
  les appels d'outils deja faits (`tool_calls`, voir
  [09](09-transcript-et-discussion-llm.md)) : `initChatWidget` les affiche
  dans un bloc (`[data-chat-tool-steps]`) au-dessus de la bulle « en train
  d'ecrire », une ligne par appel (libelle, puis son resultat). Le nom du
  modele n'est pas affiche pendant l'attente. La bulle disparait avec la
  reponse, elle n'est pas conservee dans l'historique.
- Chaque message a la forme `{role, content}`, plus `channels: [{channel_id,
  name}]` et `citations: [{video_id, title}]` pour les messages `assistant`
  du scope `library` (absents/vides cote `video`, qui n'a pas besoin de se
  citer lui-meme). Les references sont **dans le texte** : `content` contient
  `[[chaine:ID|Nom]]` / `[[video:ID|Titre]]` (voir
  [09](09-transcript-et-discussion-llm.md)), que `buildMessageNode` rend en
  liens surlignes (`.chat-ref`) a l'endroit ou le modele cite l'element, vers
  `/videos?channel_id={channel_id}` ou `/videos/{video_id}`. Le texte du lien
  est le nom (`name` / `title`) renvoye par le serveur, pas le libelle ecrit
  par le modele, qui ne sert que si l'element n'est plus la. Seuls les ids
  encore presents dans `channels`/`citations` deviennent des liens (un
  element supprime reste du texte simple). Ce que le texte ne mentionne pas
  (reponses enregistrees avant ce format) est rendu en une rangee de puces
  defilante sous le message (`.chat-citations`, jamais la page) : les chaines
  d'abord, en puces pleines (`.chat-channel-chip`), puis les videos.
- `coverageNote` (scope `library` uniquement) affiche combien de videos sont
  actuellement indexees pour la recherche dans les notes (`"12/773 videos indexees..."`),
  calcule cote serveur (`library_chat_scope_config`, `front/library_chat.py`) a partir
  de `indexed_video_count`/`total_video_count` (voir
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)).
- Les messages initiaux sont pre-rendus dans la config au chargement de la
  page (pas de fetch initial) ; changer de portee ne fait donc pas d'appel
  reseau, seulement un nouveau rendu local.
- `initChatWidget` remplace l'ancienne implementation JS locale a
  `video_detail.html` (dupliquee entre elle et `app.js`
  avant cette unification) — l'autre implementation de polling
  reste separee (redirection pleine page pour les telechargements), son contrat etant different (patch DOM in-place ici).

## Chaines

Template : `channels.html`

Contenu :

- formulaire ajout chaine (avec categories) : une URL ou un `@handle` ajoute
  la chaine directement ; tout autre texte est un nom a chercher ;
- panneau "Chaines YouTube pour « nom »" quand `/channels` recoit
  `?youtube_q=<nom>` : une ligne par candidate (avatar, nom, handle, nombre
  d'abonnes, debut de description) avec un bouton "Ajouter" qui poste son URL
  et les categories choisies dans le formulaire (`youtube_categories`), ou un
  badge "Deja ajoutee" (lien vers la chaine) si elle est dans la
  bibliotheque. Pas de lien vers YouTube. Lien "Fermer" pour replier le
  panneau ; erreur de recherche et absence de resultat sont affichees dans le
  panneau. Comme `added_channel_id`, ces parametres ne sont pas repris dans
  les `next`/liens de pagination, pour ne pas relancer la recherche au retour
  d'une autre action ;
- notification flottante (voir "Notifications flottantes") apres l'ajout
  d'une chaine via ce formulaire : "Chaine
  <nom> ajoutee." + lien "Voir la chaine" vers `/videos?channel_id=<id>`.
  Affichee quand `/channels` recoit `?added_channel_id=<id>` et que l'id
  correspond a une chaine existante (nom et lien lus dans la DB, id inconnu ou
  non numerique ignore). Les `next`/liens de pagination de la page ne
  reprennent pas le parametre, pour qu'une autre action ne la reaffiche pas.
  Le formulaire redirige vers `/channels?sort=added` : la liste est triee
  par ajout recent (option « Ajoutees recemment » du menu de tri), la chaine
  ajoutee en tete. L'import CSV fait de meme avec `?message=...` (plusieurs
  chaines, pas de lien unique) ;
- zone de depot (drag & drop ou clic) pour importer un CSV d'abonnements
  YouTube (export Google Takeout) ; apres analyse, affiche la liste des
  chaines trouvees avec une case a cocher par chaine (decochee et grisee
  "Deja importee" pour celles existantes, cochee par defaut pour les
  nouvelles, decochables individuellement, boutons "Tout selectionner"/"Tout
  deselectionner"), puis bouton "Enregistrer" pour creer les chaines cochees ;
- grille de cartes (colonnes de 300 px minimum, une seule colonne sur
  telephone) ; chaque carte montre une bande de banniere de 84 px (la banniere
  de la chaine, ou le meme degrade de repli que la page de la chaine), l'avatar
  de 64 px qui la chevauche (ou, sans avatar, une pastille avec l'initiale du
  nom), le nom (lien vers la bibliotheque filtree), les categories, puis une
  ligne « N fiches » + « Derniere activite : date » ; la carte monte de 4 px au
  survol (coupe avec `prefers-reduced-motion`). Un pied de carte separe par un
  filet porte les deux cloches et les cinq etoiles de la note. Le nombre de
  fiches est calcule pour les chaines de la page courante seulement
  (`video_count` de chaque entree, `channels_context`). La description, les
  mots-cles et le bouton de rafraichissement du profil sont sur la page de la
  chaine, pas dans la liste. Les images sont servies par
  `/api/channels/{id}/avatar` et `/api/channels/{id}/banner` ; un parametre `v` (date
  de recuperation du profil) force le navigateur a les recharger apres un
  rafraichissement ;
- note sur 5 étoiles par chaine ;
- modification des categories d'une chaine ;
- deux cloches de suivi quotidien (memes boutons carres de 44 px que sur la
  page de la chaine : cloche pleine ou barree, pastille ▶ pour les videos,
  cadre portrait pour les shorts), desactivees par defaut et basculables
  independamment ;
- lien vers videos filtrees.

La suppression d'une chaine se fait depuis sa page, pas depuis cette liste (voir
[02 Fonctionnalites](02-fonctionnalites.md)).

La barre de recherche suit les regles de la section
[Recherche](#recherche-videos-et-chaines).

## Playlists

Templates : `playlists.html` (index), `playlist_detail.html` (detail). Styles
`.pl-*` (index) et `.pld-*` (detail) dans `tailwind.input.css`, script du
detail dans `front/static/js/playlist-player.js`.

### Index `/playlists`

Deux colonnes qui s'empilent sur ecran etroit : la grille des playlists a
gauche, le panneau **Ajouter** a droite (toujours visible, aucun menu a
ouvrir).

- Grille : une carte par playlist — vignette 16:9 de la premiere video (ou
  degrade neutre s'il n'y en a pas) posee sur deux couches decalees (effet de
  pile), pastille de source (`Manuelle`, `URL YouTube`, `CSV Takeout`) en haut
  a gauche, badge du nombre de videos en bas a droite, titre sur deux lignes.
  Toute la carte mene au detail. Un menu `⋯` (`<details>`) propose Ouvrir,
  Dupliquer et Supprimer (confirmation `data-turbo-confirm`) ; il n'apparait
  qu'au survol ou au focus sur les pointeurs qui survolent, et reste visible
  sur ecran tactile. Un champ de recherche filtre les cartes par titre cote
  client.
- Animations : entree des cartes en 260 ms, echelonnee sur les 7 premieres ;
  au survol la carte monte de 4 px et les deux couches s'ecartent ; les trois
  formulaires du panneau arrivent l'un apres l'autre. Tout est coupe avec
  `prefers-reduced-motion`.
- Panneau Ajouter, trois formulaires independants : creation manuelle (titre
  seul) ; import par URL YouTube (`data-async-job`, meme contrat fetch/poll que
  l'import metadata de chaine, precede d'une etape d'apercu : le bouton
  **Prévisualiser** (ou Entree dans le champ) appelle `POST /api/playlists/preview`
  et deplie une carte — titre, chaine, nombre de videos, duree, deja en
  bibliotheque, notes (indisponibles, sans duree, plafond), premiers titres —
  avec **Importer** (soumet le formulaire) et **Annuler** ; modifier l'URL
  referme la carte) ; import par CSV Google Takeout
  (`data-async-job`, un fichier a la fois). Le CSV se depose dans une zone en
  pointilles qui est le `<input type="file">` lui-meme ; le champ titre est
  pre-rempli en JS depuis le nom du fichier, editable avant l'envoi (pas de
  zone partagee avec l'import CSV de chaine, qui soumet des qu'un fichier est
  choisi).

### Detail `/playlists/{id}`

Deux colonnes : panneau lecteur a gauche, file de lecture a droite.

- **Lecteur** (`playlist-player.js`) : bascule **Vidéo / Audio**, retenue dans
  `localStorage`. Le lecteur enchaine les videos de la file dans l'ordre
  affiche ; une video sans fichier du format choisi est **ignoree** (badge
  « Ignorée » sur sa vignette et mention sous son titre). Commandes : aleatoire,
  precedent, lecture/pause, suivant, boucle (aleatoire et boucle portent
  `aria-pressed`). En mode Audio la piste est une pochette carree (la vignette
  recadree) ; en mode Video, un `<video>` 16:9. Les deux modes partagent le meme
  element media (`/api/videos/{id}/audio` ou `/api/videos/{id}/video`). La lecture
  journalise l'activite via `POST /api/videos/{id}/activity` (comme la page d'une
  video), sauf en **ecoute libre**.
- **Infos et options** sous le lecteur : titre, labels de categories, source,
  duree totale et nombre de vues ; « Télécharger l'audio / la vidéo de tout » (formulaires POST ;
  bulle « Sans fichier …, une vidéo est ignorée par le lecteur ») ; interrupteur
  **Mode écoute libre** (`role="switch"`, `playlists.free_listening`) : le
  lecteur n'enregistre aucune activite, aucune video n'est marquee vue, et le
  compteur « N vues sur M » ainsi que les coches ✓ disparaissent. Pense pour la
  musique et les podcasts.
- **File de lecture** : filtre par titre (client), menus **Ordre** (trier par
  date d'ajout, duree, titre ; inverser) et **Gérer** (renommer, labels
  categories, rafraichir depuis YouTube pour une playlist `url`, dupliquer,
  exporter en CSV, supprimer avec confirmation). « Labels catégories » ouvre
  le meme editeur que la page d'une chaine (pastilles predefinies + champ
  libre) ; les vidéos sans label recoivent ceux de la playlist. Sur telephone
  (≤ 640 px) le panneau de **Gérer** s'etale sur la largeur de l'en-tete de la
  file au lieu d'etre aligne sur son bouton, qui le faisait deborder a gauche. Un tri reecrit les positions : il n'y a pas de « mode de
  tri » persistant, l'ordre manuel est simplement l'ordre courant.
- **Lignes** : un clic (ou un toucher) n'importe ou sur la ligne lit la piste ;
  il n'y a ni numero ni bouton lecture. Elle contient : poignee `⋮⋮` (desktop :
  glisser au pointeur, ou fleches haut/bas au clavier une fois la poignee
  focalisee ; l'ordre est enregistre par `PUT /api/playlists/{id}/order`),
  vignette (badge « Ignorée » en haut a gauche, duree en bas a droite, `✓` en
  bas a gauche pour une video deja vue hors ecoute libre), titre
  (lien vers la page de la video sur desktop), deux boutons de telechargement
  audio/video (plein = fichier present, vide = clic pour le telecharger via
  `POST /api/videos/{id}/media/{audio|video}/download`, avec suivi du job) et `✕`.
  La piste en cours a la ligne teintee ; le compteur « N vues sur M » de
  l'en-tete reste. Un clic sur le remplissage du menu ou sur une ligne en
  attente de confirmation de retrait ne lit rien.
  `✕` ne retire pas directement : la ligne passe en rouge pale et demande
  « Retirer « titre » de la playlist ? » avec Annuler / Retirer ; la video reste
  dans la bibliotheque.
- **Lignes sur telephone (≤ 640 px)** : une seule ligne de 64 px de haut
  (vignette 88 px, titre sur 2 lignes, chaine) ; la poignee disparait et
  l'ordre se change par **appui long** (≈ 450 ms) sur la ligne puis glisser
  (le defilement de la page est bloque pendant le glissement ; un mouvement
  de plus de 8 px avant la fin de l'appui est un simple defilement ; un second
  doigt ne demarre pas un second glissement). Le toucher sur le titre lit la
  piste (le lien reste pour le clavier). Les actions sont dans un menu « ⋯ » a
  droite, ferme par Echap : Fiche de la vidéo, Monter, Descendre (reordonner
  sans la poignee, au clavier ou sans appui long), Audio, Vidéo, Retirer de la
  playlist.
- Chaque ligne porte, apres le nom de la chaine, la meme fleche discrete que
  la page d'une chaine (`.pld-youtube-link`, nouvel onglet, `noopener
  noreferrer`) vers la page YouTube de la video (`videos.url`) ; un clic dessus
  ne lit pas la piste.
- Bulles : les boutons peu courants (aleatoire, boucle, precedent/suivant,
  Ordre, Gerer, poignee, ✕, telechargements, ecoute libre) portent
  `data-tip`, affiche en bulle au survol et au focus clavier.

Voir [07 YouTube et telechargements](07-youtube-et-telechargements.md) et
[13 Jobs, logs et planification](13-jobs-logs-planification.md) pour le
detail des deux flux d'import (metadonnees seules, pas de re-synchronisation
periodique).

## Recherche (videos et chaines)

Les pages `/videos` et `/channels` ont chacune un champ `q` dans leur
formulaire de filtres. La recherche s'ajoute aux filtres actifs (chaine,
types de fichier, categories, "Notees"...) : elle ne les remplace pas.

Correspondance (`search_rank` dans `back/services/common/search.py`) :

- la requete est decoupee en mots ; **tous** les mots doivent etre presents,
  dans n'importe quel ordre et dans n'importe quel champ (`python tuto`
  trouve "Tuto Python") ;
- chaque mot est cherche en sous-chaine, sans tenir compte de la casse ni des
  accents (`ecole` trouve "École") ;
- pas de tolerance aux fautes de frappe ;
- champs d'une video : titre, nom de chaine, labels de categories, note
  personnelle,
  URL, ID YouTube, URL de la chaine. La description et le transcript ne sont
  pas couverts ;
- champs d'une chaine : nom, labels de categories, URL, ID YouTube.

Execution : la liste `/videos` (filtres, tri, pagination et compteurs) est
calculee en SQL ; seule la recherche classe les candidats en Python, car le
matching est insensible aux accents et par mots. Les conditions SQL
(`video_filters_condition`) et leur jumeau Python (`video_matches_filters`)
doivent rester equivalents (`tests/test_videos_sql_filters.py`).

Classement : quand une requete est saisie, les resultats sont regroupes par
pertinence, puis le tri choisi s'applique a l'interieur de chaque groupe.
Videos : (1) tous les mots dans le titre, (2) dans titre + chaine + labels,
(3) le reste. Chaines : (1) nom, (2) nom + labels, (3) le reste.

Recherche instantanee : pendant la frappe (delai de 200 ms), `app.js`
recharge uniquement le `<turbo-frame>` de resultats (`library-results` sur
`/videos`, `channel-results` sur `/channels`), designe par l'attribut
`data-live-search` du formulaire. Le champ garde le focus, l'URL est mise a
jour (`history.replaceState`) et la pagination revient a la page 1. Le frame
contient tout ce qui depend de `q` : pastilles de filtres actifs, compteur,
liste, pagination. Entree soumet le formulaire normalement (rechargement
complet) ; sans JavaScript la recherche fonctionne donc toujours. Le champ
affiche la requete telle que saisie. Sans resultat : "Aucun resultat pour
« ... »".

## Videos

Templates : `videos.html` (bibliotheque globale `/videos`) et
`channel_videos.html` (page d'une chaine, `/videos?channel_id={id}` quand la
chaine existe — voir [Page d'une chaine](#page-dune-chaine)). La route est la
meme (`videos_page`) ; elle choisit le template selon la chaine.

Contenu :

- barre de recherche (voir [Recherche](#recherche-videos-et-chaines)) ;
- filtre chaine ;
- tri (import recent / publication recente / les plus vues / les mieux notees : note
  decroissante, puis date de publication) ;
- actions metadata page ;
- cartes videos ;
- aucun label sur la carte (hors page d'une chaine, qui affiche la pastille
  **Nouveau**) : ni labels techniques (**Nouveau**, **Notes**,
  **Manuelle**, Audio/Video/Metadonnees/Transcript), ni labels de
  categories ; les labels restent visibles sur la fiche video ;
- vignette pleine hauteur : elle occupe toute la hauteur de la carte, bord a
  bord (colonne de 168px), en 16/9 au minimum puis etiree avec recadrage
  `cover` si la carte est plus haute ; en conteneur etroit (telephone, moins
  de 460px) la colonne passe a 176px et la vignette occupe toujours toute la
  hauteur de la carte ;
- sur mobile (moins de 800px), les listes de cartes (`.video-row-list`,
  `.video-stack-list`) occupent toute la largeur de l'ecran : elles sortent
  des marges de page et perdent leur cadre lateral et leurs coins arrondis
  (marges negatives uniquement, jamais de `width: 100vw` : une largeur fixe
  elargit toute la page du dashboard sous Safari iOS) ;
- carte en conteneur etroit : meme disposition dans toutes les listes
  (`/videos`, detail d'une playlist, piles de Nouveautes) — titre limite a 2
  lignes, chaine et date sur la meme ligne, puis les actions dans la colonne
  de droite, sous le titre et la date (jamais en barre pleine largeur sous la
  vignette) : Audio/Video (qui servent aussi a supprimer le fichier), puis la
  notation, avec retour a la ligne si la colonne est trop etroite ; avec les vignettes masquees, la colonne de vignette disparait
  (seule une carte "audio seule" garde la largeur de son bouton play) ;
- sur ecran tactile (`hover: none` et `pointer: coarse`), les boutons
  Vu/Ecartee ne sont affiches dans aucune liste, Historique compris : ils sont
  remplaces par le glissement de la carte, vers la droite pour Vu, vers la
  gauche pour Ecartee (le bloc reste dans le DOM, masque en CSS, car le
  glissement lit son etat). Le glissement peut commencer n'importe ou sur la
  carte, y compris sur un lien ou un bouton (vignette, titre, Audio/Video,
  etoiles) : un simple appui garde son effet normal, et le clic qui suivrait
  un glissement confirme est annule. Seuls les champs de formulaire en sont
  exclus ;
- carte dans une pile de Nouveautes (`.video-stack`) : seules differences
  avec les autres listes, le nom de chaine n'est pas repete sous le titre (il
  est deja dans l'en-tete de la pile) et les boutons Vu/Ecartee n'y sont
  affiches sur aucun ecran ;
- aucune page ne doit defiler horizontalement sur mobile (verifie a 390px,
  largeur d'un iPhone) : les grilles qui contiennent un carrousel, un
  `select` ou un titre long declarent une colonne `minmax(0, 1fr)` (grille
  du dashboard, formulaire de filtres, `.settings-layout`,
  `.settings-sections`, `.settings-card`, `.settings-form label`,
  `.video-detail-card`), car une colonne `1fr` ou implicite prend la largeur
  du contenu ; un `select` est plafonne a `max-width: 100%` et le titre de la
  page video coupe les mots sans espace (`overflow-wrap: anywhere`) ;
- popover thumbnail au survol du titre ;
- pagination.

### Page d'une chaine

Template : `channel_videos.html`. La barre de sous-bibliotheques
(`library_views`) n'existe que sur la bibliotheque globale. Le formulaire
d'import par URL non plus. Tout le CSS de la page est prefixe `.channel-*` (et
`.video-row-channel` pour les cartes) : les autres listes gardent leur
rendu. Les animations (cascade des cartes, sonnerie des cloches, reflet des
etoiles...) sont desactivees par `prefers-reduced-motion`.
La cascade d'entree des cartes reste courte (260 ms, decalage plafonne a 7
cartes) pour ne pas ressembler a un chargement lent. Sur telephone, la ligne
d'actions d'une carte (etat de lecture, etoiles) se place juste sous le titre,
qu'il tienne sur une ou deux lignes, et non au bas de la vignette.

**Chaine sans fiche** : quand la liste est vide et qu'aucune recherche n'est
active, la zone de resultats affiche un raton laveur
(`static/img/raccoon-empty.png`, decoratif : `alt=""`) et, dessous, un message
tire au hasard dans `CHANNEL_EMPTY_MESSAGES` (`front/pages.py`) a chaque
rendu — donc un nouveau message a chaque rafraichissement de la page. Une
recherche sans resultat garde le texte « Aucun resultat pour « q ». ».

**En-tete** (`.channel-hero`), de haut en bas :

- la banniere (si enregistree ; sinon un degrade terracotta) et, qui la
  chevauche, l'avatar (ou la pastille d'initiale) a gauche du nom. Le **nom de
  la chaine est le lien vers YouTube** (`.channel-youtube-link`, nouvel
  onglet, `noopener noreferrer`, fleche discrete qui s'eclaircit au survol) ;
  il n'y a plus de ligne de statistiques ni de lien "YouTube ↗" separe ;
- les actions, alignees a droite (sur toute la largeur, sous le nom, sur
  telephone) : deux cloches de suivi quotidien (formulaires `POST
  /channels/{id}/auto-metadata`, un par section ; la pastille ▶ designe les
  videos, la pastille portrait les shorts ; allumee elle est pleine et
  orange, eteinte elle est barree — `aria-pressed` porte l'etat). Une cloche
  qu'on vient d'allumer sonne apres la redirection (`.is-ringing`, pose par
  `app.js` via `sessionStorage`). Puis la note de la chaine (memes etoiles que
  les cartes, un reflet les traverse quand la note change) et le menu « ⋯ » ;
- le menu « ⋯ » (`details.channel-menu`, popover sur ordinateur, feuille
  basse sur telephone) contient, dans l'ordre : les statistiques (videos
  telechargees, shorts telecharges, fiches, periodicite — "~3,5/sem" ou
  "~1,3/mois", `Pas assez de donnees` sinon), les labels de categories de la
  chaine (formulaire existant, deplie), « Rafraichir le profil » (`POST
  /channels/{id}/refresh-profile`) et « Supprimer la chaine » (avertissement
  detaille puis confirmation, comme avant) ;
- la description tronquee a 2 lignes avec "Voir plus"/"Voir moins" (case a
  cocher CSS, proposee uniquement au-dela de 200 caracteres) ;
- les mots-cles en etiquettes : au-dela de 5, les suivants sont caches derriere
  une pastille « +N » (case a cocher CSS) qui devient « Moins ».

Une partie vide du profil n'est pas affichee.

**Barre d'outils** (`.channel-toolbar`) : un formulaire GET (`data-auto-submit-filter`,
recherche en direct dans `<turbo-frame id="library-results">`) puis, hors
formulaire, le bouton `↻`.

- bascule **Vidéos / Shorts** (boutons radio `section`) ; sans `section` dans
  l'URL, la page s'ouvre sur Shorts quand la cloche shorts de la chaine est
  active et la cloche videos ne l'est pas, sur Videos sinon ;
- recherche `q` ;
- **tri** (popover `details[data-pop]`, boutons radio `sort`) : import recent,
  publication recente (defaut sur une chaine), les plus vues, les mieux notees ;
  le bouton affiche le tri courant ;
- **Filtres** (popover, feuille basse sur telephone) : types de fichier et
  categories en pastilles a trois etats (inclure / exclure / neutre, macro
  `filter_chip3`) avec leurs modes « Au moins un / Tous », « ★ Notées »,
  « Masquer les écartées » et « Sans catégorie » (voir plus bas), le nombre de
  fiches correspondantes et un bouton
  « Fermer ». Chaque changement recharge la page ; `app.js` memorise dans
  `sessionStorage` que le panneau etait ouvert et le rouvre. Le bouton affiche
  un badge avec le nombre de filtres actifs. Par defaut une chaine selectionne
  tous les types de fichier : c'est « pas de filtre », donc ni pastille ni
  badge ;
- les filtres actifs (hors defaut) sont repetes en pastilles retirables sous
  la barre d'outils, avec « Tout effacer » ;
- `↻` : `POST /channels/{id}/import-metadata` page 1 de la section courante
  (job asynchrone `data-async-job`, l'icone tourne pendant le traitement). Il
  remplace les anciens boutons « Chercher les fiches » / « Chercher les
  shorts ».

Les popovers sont des `<details data-pop>` : un seul reste ouvert, un clic a
l'exterieur ou Echap les ferme. Il n'y a plus de bloc de statistiques ni de
titre de section sur la page.

**Resultats** (`.channel-video-grid`, dans un conteneur `.channel-results`
dont la largeur choisit la mise en page ; cartes = macro `video_card` en
`channel_mode`) :

- **Videos, conteneur d'au moins 461px** : grille de cartes (colonnes d'au
  moins 250px), vignette 16/9 arrondie puis titre sur 2 lignes et date de
  publication en petit dessous — ni chaine, ni vues. La duree est en bas a droite de la vignette, la progression
  de lecture est une barre de 4px collee au bord bas (plus de texte
  « position / duree »), la pastille « Nouveau » (fiche `is_new`) est en haut
  a gauche. Au survol, la carte se souleve et les boutons Vu/Ecartee
  apparaissent en haut a droite. **Note** : au repos un petit point de la
  couleur du palier (`.rating-dot`, absent sans note) est en bas a gauche ; au
  survol il s'ouvre en cinq etoiles cliquables (memes formulaires
  `rating-control` et memes paliers que partout, la note courante effacee en
  recliquant dessus). Le palier 5 ("Noir") est acier fonce cerne de blanc sur
  la pastille sombre, et un reflet de lumiere traverse la vignette des videos
  notees 5 toutes les quatre secondes. Sur ecran tactile (`hover: none`) les
  etoiles sont toujours affichees ;
- **Videos, conteneur de moins de 461px (telephone)** : meme liste de lignes
  que partout (vignette pleine hauteur de 176px, titre sur 2 lignes, actions
  sous le titre, glissement vu/ecartee), avec en plus la pastille « Nouveau » et
  la barre de progression sur la vignette, la date de publication sous le
  titre et sans nom de chaine ;
- **Shorts** (`.channel-video-grid-shorts`) : mosaique de tuiles portrait
  (colonnes d'au moins 150px et lignes de 300px sur ordinateur, ecart de 10px,
  3 colonnes sur telephone, flux `dense`). Un short nouveau (`is_new`) ou note 5
  (`.video-row-feature`) occupe une grande tuile 2×2 avec son titre en
  surimpression. Les grandes tuiles sont choisies par `shorts_feature_flags`
  (`front/library.py`) : d'abord les nouveaux et les notes 5, dans
  l'ordre de la page, puis une tuile sur 7 (la premiere, la huitieme…) pour que
  la mosaique ne soit jamais plate. Deux grandes tuiles commencent toujours a
  au moins 6 positions d'ecart : un short prioritaire trop proche d'une grande
  tuile reste petit (il garde sa pastille et ses etoiles) ;
  les autres ne
  montrent que leur duree, la pastille « Nouveau » et, s'ils sont notes, un
  badge d'etoiles pleines en bas a gauche (le titre n'y est que pour les
  lecteurs d'ecran et l'infobulle) ;
  au survol, toutes les etoiles apparaissent avec, a leur droite, un lien
  (`.short-tile-detail`, toujours visible sur ecran tactile) vers la page
  detail de la video (description, etc.). La vignette d'une tuile est la
  vignette d'origine, sans `srcset` (les copies 320/640 px sont floues une fois
  recadrees en portrait). **Cliquer sur la tuile d'un short
  sans fichier local telecharge directement la video en 1080p** (ou la
  meilleure qualite en dessous), sans ouvrir la page detail : la tuile est un
  formulaire `data-async-job` vers `POST /videos/{id}/media/video/download`
  (`video_quality=1080`, `next` = la page courante), son etat de progression
  recouvre la vignette. Un short deja telecharge garde le lien vers la page
  detail sur toute la tuile ;
- les cartes arrivent en cascade (`--i` : indice de la carte, delai plafonne) ;
- sous la grille : pagination numerotee (macro `numbered_pagination` :
  « ‹ 1 2 3 … N ›, page courante en orange), puis le bouton **Explorer la
  suite** (`POST /channels/{id}/import-metadata` a la page suivante a importer,
  hors du `turbo-frame`) avec la mention « Récupère les 25 fiches suivantes
  depuis YouTube » : il remplace « Chercher les 25 suivantes ». Quand la chaine
  n'a aucune fiche (et qu'aucune recherche n'est active), le bouton devient
  **Commencer l'exploration** et la mention « Récupère les 25 premières fiches
  depuis YouTube ». La mention disparait au clic sur le bouton.
  **Pendant l'import** (formulaire `data-explore`, pas un `data-async-job`) :
  Raton (`#explorer-raton`, element `data-turbo-permanent` de `base.html`,
  image `laptop.webp`) apparait fixe en bas de la page avec la bulle
  « Je m'en occupe ! » puis le compteur « n/25 ». Le script interroge
  `GET /api/jobs/{id}` : pour un job d'import de chaine, la reponse porte aussi
  `videos` (`id`, `title` des fiches deja importees, posterieures a la ligne de
  file du job) ; les cartes correspondantes sont recuperees en HTML par
  `GET /videos/cards?ids=…&section=…` (gabarit `_video_cards.html`, macro
  `video_card`) et ajoutees a la grille des qu'elles existent. A la fin, la
  page est rechargee sans bruit (Turbo `replace`) pour retrouver tri,
  pagination, compteur et libelle du bouton.
  **Si on quitte la page** : l'etat vit sur `window`, le suivi continue d'une
  page a l'autre (navigation Turbo) mais Raton n'est affiche que sur la page de
  la chaine explorée. La page ne bouge pas quand une carte arrive
  (`overflow-anchor: none` + position de scroll restauree). La bulle porte un
  bouton **×** : `POST /api/jobs/{id}/cancel` passe le job en `cancelled`, l'import
  s'arrete avant la fiche suivante et ce qui est deja importe reste. Un
  rechargement de la page reprend le suivi (etat dans `sessionStorage`, 30 min
  max) ; les cartes deja affichees (`data-video-id`) ne sont pas dupliquees. Pas de notification
  par fiche : **une seule** a la fin (« n fiches recuperees »), en toast avec
  lien quand on est sur une autre page, et en notification systeme
  (API `Notification`, autorisation demandee au clic) quand l'onglet est masque.
  Fermer l'onglet n'est pas couvert (pas de Web Push). L'etat vide (raton laveur) ne doit pas etre rogne par les
  hauteurs de rangee fixes de la mosaique de shorts.

Les cartes doivent eviter les liens YouTube visibles.

Une carte "audio seule" (`audio_path` sans `video_path`) affiche en plus un
bouton play en superposition sur la vignette, qui lance la piste dans le
mini-lecteur persistant sans quitter la page (voir
[08 Medias et lecteurs](08-medias-et-lecteurs.md)) — meme comportement dans
la page Nouveautes, qui reutilise la meme macro `video_card`.

Chaque carte video expose aussi deux boutons **Vu** et **Écartée**, rendus par
la macro partagee `list_state_actions` (`_macros.html`). Elle est appelee
depuis `video_card` (donc `/videos`,
`/dashboard/nouveautes` et le detail d'une playlist) **et** depuis `media_row`
(`/dashboard/historique`), qui n'affiche
les boutons que lorsque la ligne d'activite est bien rattachee a une video
(`job.video`). Une ligne dont la video a ete supprimee depuis (`video_id` remis
a NULL) affiche, sans lien, le titre enregistre dans le job au moment de la
lecture, et n'apparait qu'une fois par titre et par chaine ; le libelle
`Lecture`/`Reprise` + `audio`/`vidéo` ne sert de titre que si le job n'en a
enregistre aucun. Les deux paliers de grisage n'y portent pas les memes noms de
classe que sur une carte de liste (`dashboard-media-row-completed` et
`dashboard-media-row-hidden`) : la macro les passe en
`data-row-watched-class`/`data-row-hidden-class` sur le conteneur, ce qui
permet au JS de repeindre la ligne sans rien savoir du template. "Historique"
n'a pas de filtre "Masquer les ecartees" — une video ecartee y reste visible,
simplement grisee au palier fort. Les deux paliers y sont obtenus en teintant
le texte, alors qu'une carte de liste baisse son `opacity` : la ligne
d'historique est posee sur le fond deja creme d'un bloc de journee, ou un
voile d'opacite rendait le titre illisible. Ce sont des pastilles
sans libelle visible, portant une icone SVG inline en trait (`.list-state-icon`,
14 px) : un œil pour **Vu**, le meme œil barre pour **Écartée** — la meme icone
une fois rayee, qui dit visuellement que "ecartee" est un "vu" renforce. Les
tracés utilisent `stroke="currentColor"`, donc l'icone se teinte avec le
bouton quand il passe actif. Faute de libelle visible, chaque bouton porte un
`aria-label` en plus du `title` (le `title` seul n'est accessible ni au
tactile ni au lecteur d'ecran). Ils griment la ligne en
deux paliers : **Vu** applique le grisage existant (`.video-row-watched`),
**Écartée** une teinte de noir nettement plus forte (`.video-row-hidden`), avec
la vignette desaturee. Les deux ecrivent `videos.list_state` (voir
[05 Modele de donnees](05-modele-de-donnees.md)) via
`PUT /api/videos/{id}/list-state` en `fetch`, sans rechargement : la ligne et les
deux boutons sont repeints immediatement.

Une carte de la liste ne change jamais de couleur au survol ni au toucher
(souris, defilement ou tap) : seuls les etats Vu et Ecartee la grisent, sinon un
simple survol ferait croire que la video est vue.

Une ligne vue ou ecartee n'affiche pas sa barre de progression. Le serveur omet
deja le markup au rendu ; quatre regles CSS (`.video-row-watched
.video-card-progress` et ses trois equivalents) couvrent en plus la bascule au
clic, ou la ligne change de classe sans rechargement. Seul cas non couvert sans
rechargement : une ligne deja vue a l'arrivee sur la page n'a pas de markup de
progression du tout, donc la repasser en non-vue ne fait pas reapparaitre la
barre avant le prochain rendu.

Le grisage automatique existant (derniere lecture terminee) est conserve et
sert d'etat par defaut. Le bouton **Vu** s'affiche donc deja allume sur une
video terminee ; cliquer dessus ecrit `unwatched` et annule ce grisage.
Cliquer **Écartée** sur une video deja ecartee la remet a l'etat automatique —
la macro expose cet etat automatique dans `data-list-state-auto` pour que le
client sache quoi repeindre sans recharger. Cliquer **Vu** sur une video
ecartee la fait redescendre au palier "vu".

Le nuage de chips de `/videos` porte une case **Masquer les ecartees**
(`hide_hidden=1`), a cote de **★ Notées** : elle exclut de la liste les seules
videos dont `list_state` vaut `hidden`, jamais celles grisees uniquement par
leur progression de lecture.

Le facet **Categories** (sur `/videos` comme sur la page d'une chaine) porte
aussi une case **Sans categorie** (`uncategorized=1`) : elle ne garde que les
videos sans aucun label, ni les leurs ni ceux de leur chaine (une video sans
label propre affiche ceux de sa chaine, voir `video_category_condition`). Elle
sert a reperer ce qu'il reste a etiqueter. C'est une condition en plus des
autres filtres, pas une valeur de categorie : combinee a une categorie
incluse, elle donne une liste vide. Elle compte dans le badge du facet et
dans les pastilles actives, et « Tout effacer » la retire ; elle n'est pas
memorisee dans les vues enregistrees.

Les cartes video n'exposent aucun bouton Audio/Video : le telechargement et la
suppression d'un format se font depuis la page detail video
(`video_detail.html`, macro `format_actions`). Cote client (`front/static/js/app.js`),
une file traite ces telechargements en arriere-plan **sequentiellement** (un
seul a la fois) ; `POST /api/videos/{id}/media/{type}/download` reutilise la meme
file de jobs et le meme `GET /api/jobs/{id}` que le formulaire de
telechargement manuel.

## Detail video

Template : `video_detail.html`

Contenu ordonne :

1. lien de retour vers la page d'origine (`next`, sinon `/videos`), libelle
   selon cette page : "Retour a la playlist" (detail d'une playlist),
   "Retour a la chaine" (bibliotheque filtree sur une chaine), sinon
   "Retour a la bibliotheque" ; sous 800 px, ce lien partage sa ligne avec un
   bouton « ⋮ » en verre (`details.video-more[data-pop]`) qui ouvre un panneau
   « Description » (description et tags), « Segments » (liste + bouton
   « Rechercher les segments sponsors ») et « Transcription » (bouton
   « Recuperer la transcription » quand `video.transcript_path` est vide, qui
   relaie son clic vers `#transcript-retry-button` par `data-click-proxy`) ;
   sous 800 px, les onglets « Plus d'informations » et « Segments » et le bouton
   de recuperation de la barre d'actions sont masques par CSS (leurs panneaux
   et leurs ids restent), le panneau « ⋮ » prend leur place ; une ancre
   `#segments-sponsors` ouvre alors ce panneau, un clic sur un segment le
   ferme, et le statut de la recuperation y est repete
   (`data-retry-status-mirror`, bouton desactive pendant la requete) ;
   au-dessus de 800 px il est absent ;
2. labels — labels techniques (`asset-labels`) puis labels categories
   (`category-labels`) ; ces derniers se terminent par un bouton discret
   "+ Categories" (style pointille, identique a celui du bouton "+ Custom"
   dans l'editeur qu'il controle) qui affiche/masque l'editeur de categories
   (cases a cocher presets + "+ Custom" pour un label libre) juste en dessous
   de l'entete, masque par defaut ; un clic bascule le texte du bouton en
   "− Categories" et affiche l'editeur, un second clic le recache (etat non
   persiste, redevient masque au rechargement de la page) ; juste en dessous,
   un second groupe de labels suit exactement le meme motif pour les
   playlists ("+ Playlists"/"− Playlists") : liste les playlists contenant
   deja cette video (avec un lien "Retirer" par playlist), un select vers une
   playlist existante et un champ texte pour en creer une nouvelle a la volee
   (meme convention "presets + champ libre" que l'editeur de categories) ;
3. titre ;
4. chaine ;
5. note sur 5 étoiles ;
6. lecteur video ;
7. lecteur audio — natif si `video_path` et `audio_path` coexistent, sinon
   bouton "Ecouter" vers le mini-lecteur persistant si la video est audio
   seule (voir [08 Medias et lecteurs](08-medias-et-lecteurs.md)). Sous
   800 px les points 6 et 7 deviennent un carrousel a deux volets glissable
   (Video, Audio), place en tete de la page sous le lien de retour, pleine
   largeur de l'ecran en 16:9 et sans le cadre blanc de la fiche
   (`.video-detail-card` sans fond ni bordure), avec un bouton de
   telechargement par volet, un selecteur a deux icones juste dessous et sans
   les boutons Audio/Video de la barre d'actions (voir « Carrousel video / audio » dans
   [08 Medias et lecteurs](08-medias-et-lecteurs.md)) ;
8. faits ;
9. actions formats manquants — meme ligne (`.video-detail-action-bar`) que le
    bouton robot IA qui declenche la generation notes/résumé (icone
    seule, infobulle au survol decrivant ce qu'il produit ; voir
    [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md),
    section "Bouton robot (generation IA)") ; un bouton texte "Recuperer la
    transcription" apparait dans la meme barre quand `video.transcript_path`
    est vide (transcript manquant ou en echec) — voir "Recuperation manuelle
    du transcript" dans
    [07 YouTube et telechargements](07-youtube-et-telechargements.md) ;
10. transcript — barre d'onglets unique (pas de titre `<h2>` au-dessus) : liste
    des onglets, ancres et comportement dans
    [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md),
    section « Section transcript ». A l'arrivee sur la page aucun onglet n'est
    ouvert sauf si l'URL porte une ancre ; l'onglet **Segments** est decrit
    dans [08 Medias et lecteurs](08-medias-et-lecteurs.md).;
11. discussion (widget de chat partage, portee "cette video" par defaut,
    bascule possible vers "toute la bibliotheque" — voir "Widget de chat"
    ci-dessus).

La page detail a une largeur maximale de `1180px`.

Le formulaire "Telecharger video" (action formats manquants) affiche, a la
difference de la carte, un select de qualite visible en permanence a cote du
bouton (defaut `1080p`) : contrairement a la carte, l'espace disponible sur
cette page permet un controle persistant plutot qu'ephemere.

## Parametres

Template : `settings.html`

Meme langage visuel que la page Logs (cartes arrondies a filets, orange reserve
a l'etat actif). De haut en bas :

- titre "Parametres" et lien "Voir tous les logs" vers `/logs` (a droite du
  titre) ;
- resume en quatre tuiles : quota global, cout LLM cumule, date du dernier
  scan automatique ("Jamais" sinon), nombre de categories et de
  sous-bibliotheques ;
- navigation par ancres (`data-settings-nav`) : colonne a gauche sur grand
  ecran, barre de pilules defilante sous 800px ;
- cartes de reglages. Les blocs peu consultes sont replies dans un `<details>` :
  "Categories sans barre de progression", "Notes automatiques" et "Segments sponsorises" (resume du
  nombre de cases cochees dans l'en-tete ; les cases d'un bloc replie sont
  quand meme envoyees), et le detail des tableaux de "Couts LLM" (le total
  reste visible) ;
- barre d'enregistrement collante en bas de la page (au-dessus de la tab bar
  sous 800px).

Les champs, noms de formulaire et attributs `data-*` des editeurs sont
inchanges.

Permet de modifier :

- media root ;
- quota global ;
- styles des categories de video ;
- categories sans barre de progression (voir la
  section "Barre de progression de lecture" plus haut) : une case a cocher par label de categorie connu, plus les
  labels deja retenus dans ce reglage mais pas (ou plus) enregistres parmi les
  categories video (affiches sans couleur, pour ne pas les perdre silencieusement
  a l'enregistrement) ;
- notes automatiques (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md),
  section "Notes automatiques") : une case pour activer le lot nocturne
  (`auto_notes_enabled`), une case par label de categorie dont les videos sont
  exclues (`auto_notes_excluded_categories` ; meme presentation que les
  categories sans barre de progression), et la date et le bilan du dernier
  passage ;
- segments sponsorises : une case par categorie (`sponsor_segment_categories`,
  toutes cochees par defaut) et la case « Sauter automatiquement les segments
  detectes » (`sponsor_skip_enabled`, cochee par defaut) — comportement dans
  [08 Medias et lecteurs](08-medias-et-lecteurs.md) ;
- vues sauvegardees de la bibliotheque video ;
- limites de temps d'ecran par type (`video`/`short`/`podcast`/`music`) et par
  periode (`today`/`week`/`month`) ;
- carte "Raton" : simple lien vers la page `/raton/variations` (toutes les
  repliques de Raton), voir [18 Raton](18-raton-scenarios.md).

Affiche aussi, en lecture seule (section "Couts LLM", pas de champ de
formulaire) : le cout reel cumule par type de job LLM, calcule a partir des
tokens effectivement factures par le fournisseur — voir "Cout reel des jobs
LLM" dans [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).

Affiche aussi, en lecture seule (section "Suivi automatique") : la date du
dernier scan planifie (cloche) et son resultat (nombre de fiches importees,
ou motif d'echec/skip) — voir "Dernier scan automatique" dans
[13 Jobs, logs et planification](13-jobs-logs-planification.md).

Un bouton "Lancer le scan maintenant" (hors du bouton Enregistrer : il n'envoie
pas le formulaire) declenche le scan a la demande et affiche sa progression en
notifications — voir "Scan a la demande et evenements" dans
[13 Jobs, logs et planification](13-jobs-logs-planification.md). Les
notifications visibles sont limitees aux 5 plus recentes.

Il n'y a pas de champ "intervalle scan" : le scan automatique tourne a heure
fixe (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md)).

## Logs

Template : `logs.html`. Helpers : `front/logs.py`. Route : `GET /logs` dans
`front/routes/settings.py`.

Meme langage visuel que la page d'une chaine (barre d'outils en pilules de 44px,
cartes arrondies a filets, orange reserve aux etats actifs). Elements, de haut en
bas :

- titre « Logs » et nombre de jobs correspondant aux filtres ;
- resume en trois tuiles : erreurs (`failed`) et avertissements (`warning` +
  `skipped`) des dernieres 24 h, jobs en cours ou en file (`queued` + `running`,
  toute la table) ;
- barre d'outils : bascule segmentee de statut (Tout, Erreurs, Avertissements,
  En cours) avec le nombre de jobs de chaque famille, et champ de recherche
  (`q`) sur le message, le titre de la video et le nom de la chaine
  (insensible a la casse). Le formulaire est `data-auto-submit-filter` et la
  recherche rafraichit seule la `turbo-frame` `logs-results` ;
- jobs groupes par jour (« Aujourd’hui », « Hier », puis la date), du plus recent
  au plus ancien, dans une carte par jour. Une ligne montre l'heure, le badge de
  statut, le titre (la video, lien vers `/videos/{id}`, sinon la chaine, lien
  vers `/videos?channel_id=`, sinon « Tâche système »), la chaine en contexte
  quand la video est connue, et le message ;
- un message de plus de 160 caracteres ou de plusieurs lignes se replie : la
  premiere ligne (tronquee) reste visible, « Voir le détail » deplie le texte
  complet en police monospace ;
- pagination numerotee (50 jobs par page, `page`), a la place de l'ancienne
  coupure a 200 lignes.

Chaque statut s'affiche en badge francais avec une icone et une famille de
couleur (jamais la couleur seule) : `queued` En file, `running` En cours
(info) ; `downloaded` Telecharge, `metadata` Metadonnees (reussi) ; `failed`
Echec (erreur) ; `warning` Avertissement, `skipped` Ignore (alerte) ; `scheduled`
Programmee (premiere pas encore sortie), `cancelled` Arrete, `purged`
Purge, `played` Lecture, `prompt` Question IA (neutre). Un statut inconnu s'affiche
tel quel en neutre. Les jobs `played` et `prompt` restent listes ici (ils ne
sont masques qu'au dashboard).

Sur telephone (conteneur de moins de 560px) chaque ligne s'empile : badge et
heure, puis titre, contexte et message ; les filtres de statut defilent
horizontalement.


---
title: "08 Medias et lecteurs"
---
# 08 Medias et lecteurs

## Routes media

### Thumbnail

`GET /api/videos/{id}/thumbnail`

- sert `thumbnail_path` ;
- valide que le fichier existe ;
- valide que le fichier est sous `folder_path` ;
- repond `404` sinon ;
- ajoute `Cache-Control: public, max-age=86400`.

Parametre `w` (`320` ou `640`) : sert la copie reduite stockee
(`thumbs/<w>.jpg` dans le dossier de la video, voir
[06 Stockage fichiers](06-stockage-fichiers.md)) si elle existe, la vignette
d'origine sinon. Toute autre valeur de `w` est ignoree (vignette d'origine) : la
route ne genere rien. Les cartes de liste utilisent `?w=320` et `?w=640` ; le
lecteur, la page detail et les tuiles portrait des shorts gardent la vignette
d'origine (une tuile portrait ne montre qu'un tiers de la largeur 16:9 : les
copies reduites y sont floues sur telephone).

### Audio

`GET /api/videos/{id}/audio`

- sert `audio_path` ;
- valide que le fichier existe ;
- valide que le fichier est sous `folder_path` ;
- supporte `Range` ;
- repond `206 Partial Content` pour les requetes range ;
- ajoute `Accept-Ranges: bytes` ;
- detecte `Content-Type` via `mimetypes`, typiquement `audio/mp4` (`.m4a`) ou `audio/mpeg` (anciens `.mp3`).

### Video

`GET /api/videos/{id}/video`

- sert `video_path` ;
- valide que le fichier existe ;
- valide que le fichier est sous `folder_path` ;
- supporte `Range` ;
- repond `206 Partial Content` pour les requetes range ;
- ajoute `Accept-Ranges: bytes` ;
- detecte `Content-Type`, par exemple `video/mp4` ou `video/webm`.

## Lecteur video

Sur `/videos/{id}`, si `video_path` existe :

```html
<video controls preload="metadata" poster="/api/videos/{id}/thumbnail">
  <source src="/api/videos/{id}/video">
  <track kind="subtitles" src="/api/videos/{id}/subtitles" label="Sous-titres">
</video>
```

Le `poster` est present seulement si `thumbnail_path` existe, la piste
`<track>` seulement si `subtitle_path` existe.

La piste de sous-titres ne porte **pas** l'attribut `default` : il reactivait
l'affichage a chaque chargement de page, y compris quand l'utilisateur avait
desactive les sous-titres dans le lecteur natif (constate sur iPhone, ou le
menu indiquait "Desactive" alors que le texte restait affiche). Les
sous-titres sont donc **eteints par defaut** et s'activent depuis le menu du
lecteur natif ; l'app ne memorise pas ce choix elle-meme.

La page ne doit pas afficher la vignette comme image autonome. Le player video
est l'emplacement de la vignette.

## Lecteur audio

Sur `/videos/{id}`, si `audio_path` existe **et** `video_path` n'existe pas
(video "audio seule", typiquement un podcast) : pas de balise `<audio>`
inline. La section affiche un bouton `data-play-track` ("Ecouter") qui charge
la piste dans le mini-lecteur persistant (voir ci-dessous) plutot que de
demarrer une lecture locale a la page.

Si `audio_path` **et** `video_path` existent tous les deux (cas rare, formats
combines), le lecteur audio inline reste inchange :

```html
<audio controls preload="metadata" src="/api/videos/{id}/audio"></audio>
```

Le lecteur video (toujours natif, `<video controls>`) n'est pas concerne par
le mini-lecteur et n'est jamais affecte par ce changement.

### Carrousel video / audio (telephone)

Sous 800 px, `/videos/{id}` regroupe les lecteurs dans un carrousel a deux
volets (`.media-pager`, CSS `scroll-snap`, glissement natif) : **Video** a
gauche, **Audio** a droite. Une video audio seule s'ouvre sur le volet Audio, de
meme qu'une URL en `#audio` (lien du mini-lecteur), qui l'emporte sur le volet
memorise (le rechargement apres telechargement retire le `#`).
Sous le carrousel, un petit selecteur a deux icones (camera a gauche, ondes
a droite, `.media-pager-dots`) indique le volet actif et sert aussi de
boutons ; ses boutons restent `data-media-dot`. Chaque volet fait la meme
hauteur (16:9 sur toute la largeur de l'ecran, sans cadre ni ombre) : passer de
la video a l'audio ne deplace donc rien dans le reste de la page. Le volet
Audio y loge une pochette carree a gauche et la lecture (barre, ±15 s) a
droite. Au-dela de 800 px le carrousel est transparent : les sections
historiques (`.video-player-panel`, `.audio-player-panel`) restent empilees et
le choix Audio/Video se fait avec les boutons de la barre d'actions.

Chaque volet porte un `data-state` : `idle` (fichier absent), `busy`
(telechargement en cours), `ok` (termine), `ready` (fichier present). Le
bouton de telechargement d'un volet ne telecharge rien lui-meme : il pilote le
bouton Audio/Video correspondant de la barre d'actions (masquee sur telephone),
si bien que la file de telechargement, le suivi du job et la suppression
restent ceux decrits plus haut. L'etat du volet se deduit des classes du
bouton (`format-toggle-loading`, `-active`, `-error`).

- **Volet video** : pas de bouton play ni de saut ±15 s, le lecteur reste le
  `<video controls>` natif. Sans fichier, la vignette occupe tout le volet
  (`object-fit: cover`) et le bouton « Telecharger la video » est pose par-dessus,
  en bas, sur un degrade sombre ; un clic ouvre le choix de qualite (memes valeurs
  que le popover de la barre d'actions). Une fois le telechargement termine, la
  coche s'affiche 1,4 s puis la page est rechargee (visite Turbo `replace`) pour
  faire apparaitre le lecteur.
  Le rechargement attend la fin d'un telechargement en cours sur l'autre volet
  et rouvre le carrousel sur le volet que le lecteur regardait.
- **Volet audio** : sans fichier, un bouton « Telecharger l'audio » (copie de la piste du fichier video quand il existe et que la piste n'est pas degradee, sinon yt-dlp : voir `07-youtube-et-telechargements.md`). Une fois
  l'audio present (au chargement ou apres telechargement), les commandes
  reculer 15 s / lecture-pause / avancer 15 s, le curseur de temps et les durees
  s'affichent. Le curseur (`.media-seek`, `role="slider"`) suit le design commun des barres
  de progression (voir « Barre de progression commune ») : piste de 6 px avec
  couche tampon et remplissage orange, curseur vertical de 4 x 22 px, hauteur tactile de 80 px,
  `touch-action: none` pour que le glissement ne fasse pas defiler le carrousel
  (`pan-y` laisserait le navigateur annuler le pointeur des que le doigt devie
  verticalement). Pendant le glissement une bulle affiche le temps vise et le temps
  courant suit la poignee ; la position n'est appliquee qu'au relachement
  (`seekTo`). Les fleches du clavier avancent/reculent de 5 s, PageUp/PageDown de 30 s,
  Home/End vont au debut/a la fin. Le curseur n'agit
  que lorsque cette video est la piste chargee dans le mini-lecteur et que sa
  duree est connue (avant la premiere lecture il reste inerte et attenue, `.is-inert`). Les commandes
  pilotent le mini-lecteur persistant (`window.ratonMiniPlayer`,
  methodes `load`, `toggle`, `skip`, `seekTo`, `audioElement`), jamais une balise
  `<audio>` locale. Apres un telechargement, la coche devient le bouton lecture
  et les commandes se deploient (animation `is-revealing`, desactivee avec
  `prefers-reduced-motion`).
- **Suppression** : (uniquement si la barre d'actions autorise la suppression) un bouton « Supprimer » (avec `confirm`) apparait dans
  l'en-tete d'un volet `ready` et declenche la suppression existante.

## Reprise de la position de lecture

Les trois lecteurs (`<video>`, `<audio>` inline, mini-lecteur) reprennent la
lecture la ou elle s'etait arretee (`front/static/js/app.js`,
`bindResumableMedia` et `initMiniPlayer`, helpers partages
`readStoredResume`/`writeStoredResume`/`resolveResumePosition`).

La position est connue a deux endroits :

- **`localStorage`**, cle `raton:media-position:{id}:{video|audio}`,
  ecrite toutes les 5 s de lecture, a la pause et a la sortie de page. Une
  cle soeur `...:at` porte l'horodatage (ms) de la derniere ecriture ;
- **serveur** : le journal d'activite (`POST /api/videos/{id}/activity`, jobs
  `played`) contient deja `position_seconds`. `latest_playback_positions`
  (`back/services/videos/playback.py`) en extrait la derniere position par type de media, et
  `/videos/{id}` l'expose sur le lecteur via `data-resume-server-position` /
  `data-resume-server-at` (et `data-track-resume-server-*` sur le bouton
  "Ecouter").

**La plus recente des deux gagne.** Le `localStorage` seul ne suffit pas : il
est propre a chaque appareil (une video commencee sur l'ordinateur repartait de
zero sur l'iPhone), et Safari iOS purge le stockage d'un site apres 7 jours
sans visite. Une position locale sans horodatage (ecrite avant ce mecanisme)
est consideree plus ancienne que celle du serveur.

Regles :

- pas de reprise en dessous de 3 s, ni dans les 5 dernieres secondes (la
  video est consideree terminee) ;
- en fin de lecture (`ended`), la position locale est remise a `0` horodate
  plutot que supprimee, pour qu'une position serveur plus ancienne ne
  reprenne pas la main ;
- la reprise est appliquee des que les metadonnees sont disponibles — y
  compris si elles l'etaient **avant** l'execution de `app.js` (charge en fin
  de `<body>` : `loadedmetadata` a alors deja eu lieu et ne se redeclenche
  pas, d'ou le test de `readyState`) ;
- elle reste **en attente** tant que la lecture n'a pas effectivement demarre
  au bon endroit : Safari iOS peut ignorer un `currentTime` pose avant que le
  media soit jouable. Le seek est donc repose sur `canplay`, sur `play`, et
  au premier `timeupdate` si la lecture a demarre a 0. Tant qu'elle est en
  attente, aucune position n'est ecrite — sans quoi 5 s de lecture depuis le
  debut ecrasaient la position enregistree ;
- un geste explicite annule la reprise en attente : seek manuel au-dela de
  3 s ailleurs qu'a la position de reprise, ou clic sur un timestamp
  (`data-seek-time`, evenement `raton:user-seek`).

Limite connue : les boutons play des **cartes** (listes, dashboard) ne
portent pas la position serveur ; le mini-lecteur lance depuis une carte ne
reprend que depuis le `localStorage` de l'appareil.

## Mini-lecteur persistant (audio seul)

Barre fixe en bas de l'ecran (`#mini-player`, `front/templates/base.html`),
presente sur toutes les pages, masquee tant qu'aucune piste
audio-seule n'a ete lancee. Elle contient un unique element natif `<audio>`
partage entre toutes les pages : `data-turbo-permanent` (Turbo Drive) fait
que ce noeud DOM n'est jamais detruit lors d'une navigation, donc la lecture
continue pendant que l'utilisateur parcourt d'autres pages — c'est ce mecanisme,
et non un lecteur JS reimplemente, qui remplace la contrainte "toujours natif"
ci-dessus : l'element reste un vrai `<audio>` (Range HTTP, decodage natif,
compatibilite Safari/iPhone identiques), seule l'UI de controle (barre du
bas, play/pause, +/-30s, seek) est custom pour pouvoir survivre a la
navigation.

Points d'entree (`data-play-track` + attributs `data-track-*` : id, title,
channel, src, thumb, resume-key, activity-url, detail-url) :

- le bouton "Ecouter" sur `/videos/{id}` pour une video audio-seule ;
- un bouton play en superposition sur la vignette de chaque carte
  audio-seule dans `video_card` (`front/templates/_macros.html`), utilise a la
  fois par `/videos`, la section Nouveautes du dashboard, et
  `/dashboard/nouveautes` (`dashboard_new_videos.html`).

Sous 800 px le mini-lecteur est une seule rangee : la zone pochette + titre +
« Chaine · 12:34 / 48:30 » (`a[data-mini-player-open]`) ouvre la page de la
video **sur le volet Audio** (lien `/videos/{id}#audio` ; le carrousel honore
`#audio`, et si la page est deja ouverte l'evenement
`raton:show-audio-slide` fait defiler vers le volet Audio), puis
lecture-pause (56 px) et fermer (44 px). La barre de temps et les sauts ±30 s
y sont masques — le curseur du volet Audio les remplace. Au-dela de 800 px la
barre de progression et les sauts ±30 s restent affiches.

### Barre de progression commune

Les trois barres (volet Audio de `/videos/{id}`, mini-lecteur, lecteur de
playlist) partagent le meme design : piste de 6 px, couche « tampon » (plage
deja chargee, `media.buffered`), remplissage orange, curseur vertical de 4 px
(20 px de haut, 22 px sur le volet Audio). Le mini-lecteur et la playlist
restent des `<input type="range">` (accessibilite clavier native) entierement
habilles en CSS ; JS pose `--seek-progress` et `--seek-buffered` (0-100) sur
l'element (`paintSeekRange` dans `app.js`, appele aussi par
`playlist-player.js`). Le `<video controls>` de `/videos/{id}` garde les
controles natifs du navigateur.

Cliquer un point d'entree deja en cours de lecture bascule play/pause au lieu
de relancer la piste depuis le debut. Reprise de position (voir "Reprise de
la position de lecture" ci-dessus, cle
`raton:media-position:{id}:audio`) et log d'activite (`POST /api/videos/{id}/activity`) fonctionnent comme
pour les lecteurs video/audio classiques (`front/static/js/app.js`,
`initMiniPlayer`).

## Video vue et fichiers retires

Le seuil de 90 % de lecture est evalue cote serveur par
`POST /api/videos/{id}/activity` (`record_playback_activity`, qui appelle
`mark_watched_if_complete`, `back/services/videos/playback.py`) : la premiere fois que
`position_seconds / duration_seconds >= 0.9`, `videos.watched_at` est pose une
seule fois. Sa remise a `NULL` et la purge des fichiers 7 jours plus tard sont
decrites dans [06 Stockage fichiers](06-stockage-fichiers.md).

Sur `/videos/{id}`, le message « Fichiers retirés automatiquement du serveur
après visionnage. Vous pouvez les retélécharger. » s'affiche quand
`watched_at` est pose, que `video_path` et `audio_path` sont tous deux absents
et que `rating < 4`. Le bouton de telechargement manuel existant permet de
retelecharger.

## Segments sponsorisés

Sur `/videos/{id}`, la liste des segments détectés s'affiche dans son propre
onglet **Segments** (`front/templates/video_detail.html`,
`data-tab="segments"`/`data-tab-panel="segments"`, bloc `#segments-sponsors`)
— voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)
pour la place de cet onglet dans la barre.

L'onglet est **toujours visible**, sans condition `hidden`, contrairement aux
onglets Transcript/Notes qui se masquent quand leur contenu est
absent : c'est le seul point d'entrée du bouton "Rechercher les segments
sponsors", il doit rester atteignable quand la vidéo n'a encore aucun segment.
Son libellé porte le nombre de segments affichés entre parenthèses
(`Segments (3)`) ; sans segment, il affiche simplement `Segments`.

**Source unique : SponsorBlock.** Il n'y a pas de détection par IA. L'onglet
n'a qu'une action, "Rechercher les segments sponsors"
(`POST /videos/{id}/sponsors/fetch`), toujours affichée, qui interroge l'API
publique SponsorBlock ; les segments n'affichent pas de badge de source.

Le bloc "Segments détectés" (titre, bouton, puis la liste ou le message
"Aucun segment détecté pour l'instant.") n'a **aucune condition d'affichage
supplémentaire**.

La liste affichée est filtrée par les catégories actuellement activées dans
`/settings` (`sponsor_segment_categories`, voir
[11 Interface HTML](11-interface-html.md)) — pas seulement au moment de la
recherche : un segment déjà dans la DB dont la catégorie a été décochée depuis
disparaît de l'affichage sans être supprimé, et réapparaît si la catégorie est
recochée. Le même filtre gouverne le saut automatique décrit ci-dessous : une
catégorie cochée est recherchée, affichée **et** sautée ; décochée, elle ne
l'est pour rien. Il n'y a volontairement pas de seconde liste de catégories
dédiée au saut.

Chaque segment affiché est listé avec sa plage horaire et le libellé de sa
catégorie. La plage horaire est un bouton cliquable
(`data-seek-time="{{ segment.start_seconds }}"`, `front/static/js/app.js`) qui
déplace la tête de lecture à cet instant et relance la lecture — un seek
manuel au clic, indépendant du saut automatique. Deux cas selon le type de
lecteur présent sur la page :

- lecteur vidéo ou lecteur audio inline (`document.querySelector("[data-resumable-media]")`
  existe) : seek direct sur cet élément ;
- vidéo audio-seule (mini-lecteur persistant, voir plus haut, pas de
  `[data-resumable-media]` sur la page) : si la piste de cette vidéo est déjà
  celle chargée dans le mini-lecteur (même `data-track-id`), seek direct sur
  `[data-mini-player-audio]` ; sinon, le clic déclenche d'abord le bouton
  `[data-play-track]` de la page pour charger la piste, puis applique le seek
  dès l'évènement `loadedmetadata` du mini-lecteur.

Recherche SponsorBlock automatique : un téléchargement manuel réussi
(`back/services/ingest/manual_download.py:download_manual_media`) déclenche automatiquement
la même recherche SponsorBlock que le bouton, sur les catégories activées
dans `/settings` — best-effort, une erreur (réseau, API indisponible) est
avalée silencieusement sans faire échouer le téléchargement ; le bouton
"Rechercher les segments sponsors" permet de relancer la recherche
manuellement à tout moment (par exemple si SponsorBlock n'avait pas encore
de données au moment du téléchargement).

### Saut automatique

Quand le réglage `sponsor_skip_enabled` de `/settings` ("Sauter
automatiquement les segments détectés", **coché par défaut**, voir
[11 Interface HTML](11-interface-html.md)) est actif, la lecture saute
par-dessus les segments détectés. Le saut est armé sur les **trois** lecteurs
de l'app : le `<video>` et le `<audio>` de `/videos/{id}`, et le mini-lecteur
persistant. Le moteur est une fonction unique partagée,
`bindSponsorSkip(media, { visual })` (`front/static/js/app.js`), idempotente :
un lecteur déjà armé n'est jamais réarmé, seule sa liste de segments est
remplacée.

Les segments envoyés aux lecteurs sont ceux, déjà filtrés par catégories
activées, que `normalize_skip_segments` a triés, fusionnés et filtrés côté
serveur (voir [05 Modèle de données](05-modele-de-donnees.md)) : le JS ne fait
que comparer des bornes. Deux chemins d'alimentation, parce que les cycles de
vie diffèrent :

- **page détail** : le payload `{"enabled", "segments"}` est sérialisé
  directement dans la page (`<script type="application/json"
  data-sponsor-skip>`), la vue disposant déjà des segments ; aucune requête
  réseau ;
- **mini-lecteur persistant** : il se lance depuis n'importe quelle liste, où
  les segments ne sont pas dans le DOM. À chaque changement de piste, il
  désarme les segments de la précédente puis appelle
  `GET /api/videos/{id}/sponsor-segments` (voir
  [12 API et routes](12-api-et-routes.md)). Un échec réseau est avalé
  silencieusement — l'absence de segments ne doit jamais bloquer la lecture —
  et une réponse arrivée après un changement de piste est ignorée.

Séquence d'un saut :

1. **détection** sur `timeupdate` : un segment tel que
   `start <= currentTime < end`, non désarmé, alors qu'aucun saut n'est déjà
   en cours ;
2. **fondu sortant** de 250 ms du volume courant vers 0. La cible mémorisée
   est **le volume réglé par l'utilisateur**, jamais `1.0` : remonter à `1.0`
   au fondu entrant augmenterait le son à chaque saut. Sur le `<video>`
   uniquement, la classe `sponsor-skip-fading` déclenche en parallèle un fondu
   d'opacité de même durée (`front/static/css/tailwind.input.css`) ;
3. **revalidation** avant le seek : le fondu a duré au moins 250 ms, pendant
   lesquelles l'utilisateur a pu chercher ailleurs ou changer de piste. Si la
   tête de lecture n'est plus dans ce même segment, le volume est restauré
   directement et aucun seek n'a lieu ;
4. **seek** à la fin du segment, marqué comme interne pour ne pas être pris
   pour un rembobinage manuel (voir ci-dessous) ;
5. **fondu entrant** de 250 ms déclenché par l'évènement `seeked`, pas par un
   minuteur : sur un média mal bufferisé, un délai fixe rendrait le son à
   plein volume sur une image encore figée ;
6. **garde-fou** de 2 s armé en parallèle : si `seeked` ne vient jamais
   (fichier corrompu, coupure réseau), il restaure le volume, retire le fondu
   visuel et libère le moteur. Sans lui, la lecture resterait muette et
   l'écran noir indéfiniment.

Cas particuliers :

- **Désarmement au rembobinage manuel.** Il n'y a pas de bandeau "Segment
  sauté — Annuler" : le saut est silencieux. Le recours est ailleurs — un seek
  **non interne** qui atterrit dans un segment désarme ce segment pour la
  session (jusqu'au rechargement de la page, ou pour le mini-lecteur jusqu'au
  chargement d'une autre piste). C'est ce qui évite le piège du saut
  silencieux : sans lui, rembobiner dans un segment le ferait resauter
  immédiatement, en boucle. Le désarmement est réservé à un geste **délibéré**
  de l'utilisateur : la reprise automatique de la position enregistrée
  (`loadedmetadata`, sur les deux lecteurs) est donc marquée comme seek interne
  avant d'écrire `currentTime` : sinon une position enregistrée dans un
  segment le désarmerait avant le début de la lecture, à chaque rechargement.
- **Fermeture du mini-lecteur** : comme un changement de piste, elle désarme les
  segments et vide la liste — l'élément `<audio>` survit à la fermeture, ses
  segments ne doivent pas lui survivre.
- **Segment qui va jusqu'à la fin du média** : sauté comme n'importe quel
  autre. La lecture atteint alors sa fin naturelle et l'`ended` qui suit est
  légitime — la vidéo est terminée, la position enregistrée doit bien être
  vidée. Pas d'exception pour un segment qui touche la fin : comme
  `normalize_skip_segments` fusionne un sponsor et l'outro qui le touche en un
  seul bloc, une exception annulerait le saut du sponsor entier.
- **Réglage décoché** : aucun segment n'est armé, sur aucun lecteur (la page
  détail n'arme rien du tout, le mini-lecteur ignore la réponse de l'API dès
  que `skip_enabled` est faux). Les segments restent détectés, affichés, et
  leurs timestamps cliquables.
- **Aucun segment** : rien n'est armé.
- La durée du fondu (250 ms) n'est pas réglable.

Deux limites connues, l'une et l'autre assumées :

- **iOS / iPadOS.** Safari mobile ignore les écritures sur `media.volume` : le
  fondu audio y est un no-op silencieux et le saut devient une coupure sèche.
  Le seek et le fondu visuel du `<video>`, eux, fonctionnent normalement.
  **Non contourné volontairement** : seule la Web Audio API le permettrait, au
  prix d'un `AudioContext` par lecteur et d'un geste utilisateur préalable —
  disproportionné pour une app LAN mono-utilisateur.
- **Onglet masqué.** `requestAnimationFrame` est suspendu dans un onglet
  masqué alors que le média continue de jouer — or l'écoute en arrière-plan
  via le mini-lecteur est un usage normal, pas un cas limite. Le fondu s'y
  réduit donc à un changement de volume instantané, à l'entrée comme en cours
  de rampe, et le saut a bien lieu au bon moment. Sans ce traitement, un fondu
  laissé en attente bloquerait le volume à mi-course et le moteur avec lui
  jusqu'au retour de l'utilisateur.

Le lecteur reste natif : **aucun marqueur de segment n'est dessiné sur la
barre de progression**, ce qui supposerait un lecteur custom.

## Styles

- Le player video est responsive 16:9.
- La page detail est plus large que les formulaires standards :
  `max-width: 1180px`.
- Le player audio occupe toute la largeur disponible.

## Compatibilite Safari/iPhone

Les lecteurs natifs exigent le support HTTP Range pour :

- demarrage rapide ;
- seek ;
- reprise ;
- comportement mobile/iOS correct.


## Lecteur de playlist

La page `/playlists/{id}` embarque son propre lecteur (voir
[11 Interface HTML](11-interface-html.md), section "Playlists"), distinct du
mini-lecteur persistant : un seul element `<video>` sert aux deux formats,
masque en mode Audio. Il enchaine les videos de la file, ignore celles qui n'ont
pas de fichier du format choisi, et ne repond pas au mini-lecteur (la lecture
s'arrete quand on quitte la page). Il journalise l'activite comme la page d'une
video, sauf pour une playlist en ecoute libre (`playlists.free_listening`).

## Plein ecran du lecteur de playlist

En mode Video, un bouton « Plein ecran » (`[data-fullscreen]`, coin bas droit
de la scene) ouvre la video dans le lecteur natif de Safari
(`webkitEnterFullscreen()`, seule voie sur iPhone) avec repli sur
`requestFullscreen()`. Il est masque en mode Audio.

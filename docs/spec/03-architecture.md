---
title: "03 Architecture"
---
# 03 Architecture

## Stack

- Python 3.14
- FastAPI
- Jinja2 templates
- SQLAlchemy ORM
- Alembic migrations
- PostgreSQL 16 en Docker Compose
- yt-dlp pour YouTube
- ffmpeg dans l'image Docker
- APScheduler pour scans planifies
- API Anthropic pour generation des documents et chat

## Modules applicatifs

### `app/main.py`

Contient uniquement :

- composition FastAPI ;
- lifespan ;
- inclusion des routers API et Web ;
- montage des fichiers statiques.

`app/main.py` ne doit recevoir ni route ni helper : une nouvelle route va
dans le module `app/web/routes/` correspondant (a creer s'il n'existe pas),
un helper dans `app/web/` ou `app/services/`.

L'ordre des `include_router` est l'ordre de resolution des routes : API,
media, parametres, playlists, puis tableau de bord, chaines, videos,
transcript et chat bibliotheque.

### `app/templates/_macros.html`

Macro Jinja partagee `video_card(card, next_path, category_style_map, no_progress_categories=[],
channel_mode=False, feature=False, index=0)` : rend une carte video (vignette
pleine hauteur, titre, meta, progression de lecture, notation — sans labels
techniques ni categories). Utilisee par `videos.html`, `channel_videos.html`,
`dashboard.html` (section Nouveautes) et `dashboard_new_videos.html` pour
garantir un rendu identique. `channel_mode` est reserve a la page d'une chaine
(`channel_videos.html`) : pastille « Nouveau », progression sur la vignette,
point de note, pas de ligne chaine/date ; `feature` marque les grandes
tuiles de la mosaique des shorts et `index` echelonne l'animation d'entree.
Macro `numbered_pagination(current_page, total_pages, page_href)` :
pagination numerotee de la page d'une chaine (la pagination « Precedent /
Suivant » reste celle des autres pages).

Macro Jinja partagee `video_stack_list(stacks, next_path, category_style_map,
no_progress_categories=[])` : rend la section Nouveautes — une pile
(`.video-stack`) par chaine, chacune enveloppant ses cartes `video_card`
dans un carrousel navigable aux fleches (`.video-stack-carousel`). Utilisee
par `dashboard.html` et `dashboard_new_videos.html`.

Macro Jinja partagee `media_row(job, category_style_map,
no_progress_categories=[])` : rend une ligne d'activite "Historique"
(reprise de lecture). Utilisee par `dashboard.html` et `dashboard_history.html`.

La ligne affiche le titre, les labels techniques et categories, la chaine, la
progression de lecture, puis une derniere ligne qui porte le poids du fichier
a gauche et les actions Vu/Ecartee + la notation a droite. Elle ne repete ni la
date de publication ni la date de lecture : le bloc de journee qui la contient
donne deja le jour (voir [02 Fonctionnalites](02-fonctionnalites.md)).

### `app/web/shared.py`

Contient les helpers web communs :

- instance Jinja2 partagee ;
- redirections `303` ;
- validation des chemins de retour internes ;
- parsing/serialisation des categories pour formulaires ;
- pagination (`paginate`, `page_href_builder`) et chemin de la requete
  courante ;
- lecture de `metadata.json` (`video_metadata`) et labels techniques d'une
  video ;
- globals Jinja partages.

`app/web/shared.py` ne depend d'aucun autre module de `app/web/` : les
modules ci-dessous l'importent, jamais l'inverse.

### `app/web/formatting.py`

Formatage pour l'affichage : durees longues, tailles de stockage et de fichier,
nombre de vues, periodicite de publication d'une chaine. Enregistre les
globals Jinja de formatage. Les durees `m:ss` et leur lecture
(`format_duration`, `format_compact_duration`, `parse_duration_label`) sont
dans `app/services/common/durations.py`, car le service de lecture les utilise.

### `app/web/playback.py`

Affichage de l'activite de lecture : couleur et pourcentage des anneaux de
temps d'ecran (`playback_time_dashboard`), regroupement de l'historique par
jour (`history_day_groups`). Le calcul est dans `app/services/videos/playback.py`.

### `app/web/video_library.py`

Helpers HTTP de la bibliotheque video : lecture des filtres/tri/recherche
depuis la requete (`library_filters_from_request`, qui ajoute les defauts de
la page : types de fichiers preselectionnes, `filter_mode`, mode `and` des
Notees), liens des vues sauvegardees, pastilles de filtres actifs, mosaique
des shorts. Les regles de validation des filtres sont dans
`library_filters` (`app/services/videos/library_view.py`), partagees avec
`GET /api/library`.

Ce que la page montre pour un jeu de filtres (chaine et section, page de
fiches, compteurs, cartes, vues enregistrees actives) est calcule sans HTTP
par `app/services/videos/library_view.py` : la route ne fait que lire la
requete, appeler ces fonctions et construire les liens. Un autre client
(`/api`, un autre front) appelle les memes fonctions avec un
`LibraryFilters`. Les filtres eux-memes (en Python et en SQL) et l'etat de
liste Vu/Ecartee sont dans `app/services/videos/`.

### `app/web/video_detail.py`

Contexte du template de la page d'une fiche : libelles (durees, nombres de
vues, categories de segments sponsors), lien et libelle de retour, config du
widget de discussion. Les donnees elles-memes (documents, sous-titres,
metadonnees, segments, positions de reprise) viennent brutes de
`app/services/videos/detail_view.py`, qui sert aussi tout autre client de
la fiche.

### `app/web/routes/dashboard.py`

Tableau de bord (`/`), pages `/dashboard/nouveautes` et
`/dashboard/historique`, et leur contexte (`dashboard_context`, piles
Nouveautes).

### `app/web/routes/channels.py`

Page `/channels`, ajout, import CSV d'abonnements, notation, categories,
cloche (`auto-metadata`), import de metadonnees et suppression d'une chaine.

### `app/web/routes/videos.py`

Bibliotheque `/videos`, page detail `/videos/{id}`, categories, note,
titre, segments sponsors, telechargements manuels et
leurs statuts de job, activite de lecture, etat de liste et notation.

### `app/web/routes/transcript.py`

Routes `/videos/{id}/transcript/*` : generation des documents,
discussion par video, statut des jobs LLM,
ainsi que les payloads JSON associes et les estimations de duree/cout.

### `app/web/routes/library_chat.py`

Routes `/chat*` de la discussion sur toute la bibliotheque et leur payload.

### `app/web/routes/media.py`

Contient les routes de fichiers locaux :

- vignettes ;
- sous-titres ;
- streaming audio/video avec `Range` ;
- suppression audio/video.

Les routes media ne doivent servir que des fichiers situes sous
`video.folder_path`.

### `app/web/routes/settings.py`

Contient :

- page parametres ;
- formulaire parametres ;
- page logs.

### `app/api/`

L'API interne sous `/api` : `routes.py` pour les chaines, fiches,
statistiques et parametres, `library.py` pour `GET /api/library`.

### `app/services/`

Les regles metier, rangees en paquets par domaine (`common`, `youtube`,
`llm`, `media`, `channels`, `ingest`, `playlists`, `videos`, `raton`, `rag`,
`library_chat`, `jobs`) : role de chaque paquet et de chaque module,
dependances autorisees et regles de structure dans
[10 Services](10-services.md).

## Flux de donnees

```text
YouTube -> yt-dlp -> staging folder -> Video DB + media folder -> UI locale
```

Pour le transcript :

```text
YouTube subtitles -> .vtt/.srt/.json3 -> transcript.txt -> clean/notes/chat via LLM
```

Pour les players :

```text
Browser <video>/<audio> -> /videos/{id}/video|audio -> StreamingResponse Range -> media file
```

## Contraintes d'architecture

- Les telechargements ecrivent d'abord dans un dossier staging cache.
- Les fichiers ne doivent etre deplaces vers le dossier final qu'apres succes.
- Ajouter un format a une fiche existante doit merger les fichiers staging dans
  le dossier final sans supprimer l'autre format.
- Les routes media restent isolees dans `app/web/routes/media.py`.
- Les templates restent server-rendered, sans framework frontend. Turbo Drive
  (`app/static/js/vendor/`) accelere la navigation entre pages deja rendues
  cote serveur (voir [11 Interface HTML](11-interface-html.md)) mais ne
  change pas ce modele : pas de composants, pas d'etat client, pas d'etape de
  build.

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

Formatage pour l'affichage : durees, tailles de stockage et de fichier,
nombre de vues, periodicite de publication d'une chaine. Enregistre les
globals Jinja de formatage.

### `app/web/playback.py`

Activite de lecture : vue d'un job `played`/`prompt`
(`playback_activity_view`), dernieres positions de lecture, statistiques de
temps d'ecran, regroupement de l'historique par jour, journal d'activite du
tableau de bord.

### `app/web/video_library.py`

Helpers de la bibliotheque video : lecture des filtres/tri/recherche depuis
la requete, correspondance d'une video ou d'une chaine avec ces filtres, etat
de liste Vu/Ecartee (`video_list_state`), vues sauvegardees, pastilles de
filtres actifs, construction d'une carte video (`downloaded_video_card`).

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

### `app/services/background_jobs.py`

Fonctions executees via `BackgroundTasks` dans le processus web, chacune avec
sa propre session DB : `run_manual_download_job`, `run_transcript_retry_job`,
`run_channel_metadata_import_job`, `run_llm_job`. Contient aussi
`enqueue_llm_job` (creation d'un `LlmJob` `queued`).

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

### `app/api/routes.py`

Expose l'API interne sous `/api`.

### `app/services/` : organisation par domaine

Les services sont rangés en six paquets, un par sujet :

| Paquet | Contenu |
|---|---|
| `youtube/` | Tout ce qui parle à YouTube : `yt`, `sponsorblock`, `sponsor_segments`, `url_guard`, `view_counts` |
| `media/` | Fichiers sur disque : `media_storage`, `storage`, `thumbnails`, `audio_extract`, `local_upload` |
| `channels/` | Chaînes et scan : `scanner`, `scan_events`, `lookup`, `profile`, `subscriptions` |
| `playlists/` | Import de playlists : `imports` |
| `llm/` | Appels Anthropic : `provider`, `usage` |
| `rag/` | Notes, recherche et chat bibliothèque : `embeddings`, `indexing`, `retrieval`, `dashboard`, `library_chat_tools`, `auto_notes`, `transcript_backfill` |

À la racine de `app/services/` restent : les modules d'orchestration
`background_jobs` et `scheduler`, et les modules transverses `settings`,
`search`, `files`, `job_log`, `logs_digest` et `library_charts`.

Les dépendances entre paquets vont dans un seul sens :
`youtube` et `llm` ne dépendent d'aucun autre paquet, `media` dépend de
`youtube`, `channels` de `media` et `youtube`, `playlists` de `channels` et
`youtube`, `rag` de `channels`, `llm` et `youtube`. `background_jobs` et
`scheduler` appellent les paquets et personne ne les importe en retour.
`tests/test_code_structure.py` fait respecter ces règles. Les données de démo
(`demo_seed`) ne sont pas un service : elles sont dans `scripts/demo_seed.py`.

### `app/services/youtube/yt.py`

Responsable de :

- extraction chaine ;
- comptage/listing videos de chaine ;
- extraction metadata video ;
- telechargement audio/video ;
- telechargement sous-titres ;
- detection des fichiers telecharges ;
- ecriture metadata et transcript.

### `app/services/channels/scanner.py`

Responsable de :

- scan automatique ;
- import metadata ;
- telechargement manuel ;
- staged folders ;
- merge de fichiers lorsqu'on ajoute audio ou video.

L'écriture d'une ligne de journal de jobs (`log_job`) est dans
`app/services/job_log.py`, partagé par tous les paquets.

### `app/services/media/media_storage.py`

Responsable de :

- detection des 90 % de lecture (`mark_watched_if_complete`) ;
- purge quotidienne des fichiers media des videos vues (`purge_watched_media`) ;
- suppression d'un seul format (`delete_video_media_asset`), partagee avec la
  route media ;
- type de media d'une video d'apres ses chemins (`media_type_for_paths`).

### `app/services/media/storage.py`

Responsable de :

- calcul d'espace utilise ;
- marge restante sous le quota global pour les telechargements automatiques.

### `app/services/llm/provider.py`

Responsable de :

- interface `LLMProvider` et implementation `AnthropicProvider` appelant
  directement l'API Anthropic (`LLM_PROVIDER`) ;
- boucle d'appels d'outils (`AnthropicProvider.complete_with_tools`) pour le
  chat cross-video ;
- question/reponse sur transcript ;
- lecture/ecriture historique chat.

### `app/services/rag/library_chat_tools.py`

Outils que le modele appelle pendant le chat cross-video (recherche de
chaines, de videos, recherche semantique dans les notes) et extraction des
chaines/videos citees par sa reponse. Voir
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).

### `app/services/search.py`

Recherche textuelle par mots, insensible a la casse et aux accents, et
classement par pertinence des videos et des chaines. Partagee par les champs
de recherche de `/videos` et `/channels` et par les outils du chat
cross-video.

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

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
depuis la requete, liens des vues sauvegardees, pastilles de filtres actifs,
construction d'une carte video (`downloaded_video_card`), mosaique des shorts.
Les filtres eux-memes (en Python et en SQL) et l'etat de liste Vu/Ecartee sont
dans `app/services/videos/`.

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

### `app/services/jobs/`

Fonctions executees via `BackgroundTasks` dans le processus web, chacune avec
sa propre session DB :

- `downloads.py` : telechargement manuel, relance du transcript, import de
  metadonnees d'une chaine ;
- `llm_jobs.py` : creation (`enqueue_llm_job`) et execution (`run_llm_job`)
  d'un `LlmJob` ;
- `backfills.py` : rattrapages (profils de chaines, nombres de vues,
  transcripts, index des notes, miniatures) ;
- `scheduler.py` : le planificateur APScheduler qui lance les jobs quotidiens.

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

Chaque service est dans un paquet, un par sujet ; aucun module ne reste a la
racine de `app/services/` :

| Paquet | Contenu |
|---|---|
| `common/` | Bases partagees par tous les paquets : reglages (`settings`), categories (`categories`), vues enregistrees (`library_views`), note en etoiles (`ratings`), durees (`durations`), recherche par mots (`search`), outils de fichiers (`files`), journal des jobs (`job_log`) |
| `youtube/` | Tout ce qui parle a YouTube : `yt`, `channel_info`, `downloads`, `sponsorblock`, `sponsor_segments`, `url_guard`, `view_counts` |
| `media/` | Fichiers sur disque : `media_storage`, `storage`, `thumbnails`, `audio_extract` |
| `channels/` | Les chaines elles-memes : `manage`, `listing`, `lookup`, `profile`, `subscriptions` |
| `ingest/` | Ingestion : tout ce qui fait entrer une fiche dans la bibliotheque (voir [20 Glossaire](20-glossaire.md)) : `scanner`, `media_import`, `staging`, `identity`, `throttle`, `scan_events`, `local_upload`, `transcript_backfill` |
| `playlists/` | Import de playlists (`imports`) et edition d'une playlist et de ses elements (`editing`) |
| `llm/` | Appels Anthropic : `provider`, `prompts`, `chat_history`, `usage` |
| `videos/` | Fiches : filtres et conditions SQL de la bibliotheque (`filters`, dont le filtre des Nouveautes), etat Vu/Ecartee (`list_state`), activite et temps de lecture (`playback`), compteurs de la bibliotheque (`stats`), donnees de la page `/stats` (`charts`), liste paginee de `/videos` (`library_query`), modifications d'une fiche (`editing`), options d'un telechargement manuel (`download_options`) |
| `rag/` | Notes, recherche et chat bibliotheque : `embeddings`, `indexing`, `retrieval`, `dashboard`, `library_chat_tools`, `auto_notes` |
| `jobs/` | Orchestration : taches de fond (`downloads`, `llm_jobs`, `backfills`) et planificateur (`scheduler`) |

Les dependances entre paquets vont dans un seul sens : `common` ne depend
d'aucun paquet ; `youtube`, `llm` et `media` dependent de `common` ; `channels`
de `common` et `youtube` ; `ingest` de `common`, `media` et `youtube` ;
`playlists` de `common`, `ingest` et `youtube` ; `videos` de `common` et
`media` ; `rag` de `channels`, `common`, `llm`, `videos` et `youtube`. `jobs`
appelle les autres paquets et aucun ne l'importe en retour. Aucun service
n'importe `app/web/` : les routes appellent les services, jamais l'inverse.
`tests/test_code_structure.py` fait respecter ces regles.

Hors de `app/services/` : le resume du journal applicatif (`logs_digest`) est
dans `app/core/`, a cote de `app/core/logging.py` qui ecrit ce journal ; les
donnees de demo (`demo_seed`) ne sont pas un service, elles sont dans
`scripts/demo_seed.py`.

Une regle metier ne s'ecrit qu'une fois, dans `app/services/` : les routes HTML
et `/api` l'appellent et ne font que lire la requete, traduire ses erreurs en
reponse HTTP, lancer les taches de fond et rendre la page. Les ecritures dans la
DB encore faites par la couche web sont listees dans
`tests/test_code_structure.py` (`WEB_DB_WRITES_LEFT`) : cette liste ne peut que
raccourcir.

### `app/services/youtube/`

- `yt.py` : appel yt-dlp journalise (`ytdlp_call`), detection des erreurs
  429 et des premieres pas encore disponibles, extraction metadata video ;
- `channel_info.py` : resolution et recherche de chaine, profil, comptage et
  listing des videos d'une chaine ;
- `downloads.py` : telechargement audio/video, sous-titres et miniature,
  detection des fichiers telecharges, ecriture metadata et transcript.

### `app/services/channels/`

- `manage.py` : ajout et suppression d'une chaine (partages par les pages HTML
  et `/api`), categories, cloches ;
- `listing.py` : liste de `/channels` (tri, filtre Notees, recherche, nombre de
  fiches) ;
- `lookup.py` : chaine de la bibliotheque correspondant a une URL ou un
  identifiant YouTube ;
- `profile.py` : avatar, banniere et description d'une chaine ;
- `subscriptions.py` : apercu et import du CSV d'abonnements YouTube.

### `app/services/ingest/`

- `scanner.py` : scan automatique des chaines suivies ;
- `media_import.py` : import de metadonnees, telechargement manuel, relance du
  transcript ;
- `staging.py` : staged folders, merge de fichiers lorsqu'on ajoute audio ou
  video ;
- `identity.py` : chaine d'une video, URL canonique ;
- `throttle.py` : pauses entre requetes YouTube et `RateLimitedError` ;
- `scan_events.py` : etat du scan en cours, lu par la page des parametres ;
- `local_upload.py` : import d'un fichier video ou audio depose depuis
  l'appareil ;
- `transcript_backfill.py` : rattrapage des transcripts manquants.

### `app/services/common/`

- `ratings.py` : la note en etoiles d'une chaine ou d'une fiche ;
- `job_log.py` : une ligne de journal de jobs (`log_job`), l'activite de
  lecture (`record_playback_activity`), l'arret et la progression d'une
  exploration de chaine.

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

### `app/services/llm/`

- `provider.py` : interface `LLMProvider` et implementation
  `AnthropicProvider` appelant directement l'API Anthropic (`LLM_PROVIDER`),
  dont la boucle d'appels d'outils (`AnthropicProvider.complete_with_tools`)
  du chat cross-video ;
- `prompts.py` : construction des prompts (notes, resume, analyse video,
  question/reponse sur transcript, chat bibliotheque) et decoupage des
  reponses ;
- `chat_history.py` : lecture/ecriture historique chat.

### `app/services/rag/library_chat_tools.py`

Outils que le modele appelle pendant le chat cross-video (recherche de
chaines, de videos, recherche semantique dans les notes) et extraction des
chaines/videos citees par sa reponse. Voir
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).

### `app/services/common/search.py`

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

---
title: "10 Services"
---
# 10 Services

Les règles métier de Raton vivent dans `back/services/`, rangées en paquets, un
par domaine. Les routes HTML (`front/`) et `/api` (`back/api/`) les appellent :
elles lisent la requête, traduisent les erreurs en réponse HTTP, lancent les
tâches de fond et rendent la page, sans écrire elles-mêmes dans la DB.

Le reste de l'architecture (routes, templates, flux de données) est décrit dans
[03 Architecture](03-architecture.md). Le vocabulaire (fiche, cloche, Vu,
purge...) est celui de [20 Glossaire](20-glossaire.md).

## Vue d'ensemble

Les paquets sont classés du socle vers l'orchestration : un paquet n'importe
que des paquets situés plus haut dans ce tableau.

| Paquet | Rôle | Dépend de |
|---|---|---|
| `common/` | Socle partagé : utilisateurs et leur état sur les fiches et les chaînes, réglages, catégories, vues enregistrées, notes en étoiles, durées, recherche par mots, fichiers, journal des jobs | — |
| `youtube/` | Tout ce qui parle à YouTube (yt-dlp, SponsorBlock), sans toucher aux fiches | `common` |
| `llm/` | Appels à l'API Anthropic : fournisseur, prompts, coût des jobs | `common` |
| `media/` | Fichiers média sur disque : purge, quota, miniatures, extraction audio | `common` |
| `channels/` | Les chaînes : ajout, suppression, liste, profil, import des abonnements | `common`, `youtube` |
| `ingest/` | Ingestion : tout ce qui fait entrer une fiche ou un fichier dans la bibliothèque | `common`, `media`, `youtube` |
| `playlists/` | Playlists : aperçu et import, édition d'une playlist et de ses éléments | `common`, `ingest`, `youtube` |
| `videos/` | Les fiches : filtres, Vu/Indésirée, lecture, statistiques, modifications, documents, données des pages bibliothèque et fiche | `common`, `media`, `youtube` |
| `raton/` | La mascotte de l'accueil : scénarios, choix de la réplique, visites | `common`, `videos` |
| `rag/` | Notes structurées et recherche sémantique, page `/rag` | `common`, `llm`, `videos` |
| `library_chat/` | Chat bibliothèque : outils du modèle et discussions enregistrées | `channels`, `common`, `rag`, `videos`, `youtube` |
| `jobs/` | Orchestration : tâches de fond et planificateur | `channels`, `common`, `ingest`, `library_chat`, `llm`, `media`, `playlists`, `rag`, `videos`, `youtube` |

## Règles

| Règle | Pourquoi |
|---|---|
| Les dépendances entre paquets suivent la colonne « Dépend de » ; aucun paquet n'importe `jobs`. | Pas de cycle : chaque paquet se comprend et se teste avec ceux dont il dépend. |
| Aucun service n'importe `front/`. | Un service sert aussi `/api` et les jobs, qui n'ont pas de requête HTTP. |
| Rien sous `front/` ni `back/api/` n'écrit dans la DB. | Une règle métier ne s'écrit qu'une fois, dans un service. |
| Seul `jobs/` ouvre une session DB (`SessionLocal`). | Les autres services travaillent dans la session qu'on leur passe : une requête ou un job valide une seule unité de travail. |
| Aucun modèle (`back/models/`) n'importe un service. | Les services s'appuient sur les modèles ; une constante qui dimensionne une colonne est définie à côté de la colonne. |
| Chaque module est dans un paquet ; aucun ne reste à la racine de `back/services/`. | Le paquet dit à quel domaine appartient le module. |

`tests/test_code_structure.py` fait respecter ces règles ; la table des
dépendances y est `SERVICE_PACKAGE_DEPENDENCIES`.

Hors de `back/services/` : le résumé du journal applicatif (`logs_digest`) est
dans `back/core/`, à côté de `back/core/logging.py` qui écrit ce journal ; les
données de démo (`demo_seed`) ne sont pas un service, elles sont dans
`scripts/demo_seed.py`.

## Modules par paquet

### `common/`

| Module | Responsabilité |
|---|---|
| `users` | Les utilisateurs : liste, ajout, renommage, suppression (avec tout ce qui leur est propre), utilisateur par défaut et celui pour qui agit une requête (`current_user`) |
| `user_state` | État propre à un utilisateur sur une fiche (`user_videos`) ou une chaîne (`user_channels`) : lecture par lot avec valeurs par défaut, création à l'écriture, jointures SQL d'un utilisateur, abonnés d'une section (`channel_followers`), Nouveau des abonnés (`mark_new_for`) |
| `settings` | Réglages stockés en DB : ceux de la bibliothèque (`app_settings`) et ceux d'un utilisateur (`user_settings`), lecture avec valeur par défaut, enregistrement du formulaire `/settings` partagé avec `/api` |
| `categories` | Catégories des chaînes, fiches et playlists et leurs couleurs : normalisation, lecture, écriture |
| `library_views` | Vues enregistrées de la bibliothèque : forme stockée, lecture, normalisation ; types de fichiers filtrables (`VIDEO_ASSET_KINDS`) |
| `ratings` | Note en étoiles (0 à 5) qu'un utilisateur donne à une chaîne ou une fiche |
| `durations` | Durées `m:ss` / `h:mm:ss` et leur lecture, partagées par les services et les templates |
| `search` | Recherche par mots, insensible à la casse et aux accents, et classement par pertinence ; nettoyage de la saisie (`normalized_search_query`) ; utilisée par `/videos`, `/channels` et le chat bibliothèque |
| `files` | Outils de fichiers : nom de fichier sûr, taille et suppression d'un dossier, déplacement |
| `curfew` | Couvre-feu : heures stockées, état à un instant donné, routes `/api` qu'il laisse ouvertes (`ensure_open`) |
| `job_log` | Une ligne du journal des jobs (`log_job`), les dernières lignes (`GET /api/jobs`) et les statuts après lesquels un job ne change plus |

### `youtube/`

| Module | Responsabilité |
|---|---|
| `yt` | Appel yt-dlp journalisé, détection des erreurs 429 et des premières pas encore disponibles, métadonnées d'une vidéo ; échec d'une recherche YouTube (`YoutubeSearchError`) |
| `channel_info` | Ce que yt-dlp dit d'une chaîne : résolution d'une URL ou d'un handle, profil, liste des vidéos |
| `video_search` | Recherche de vidéos sur YouTube (`search_videos`), sans regarder la bibliothèque |
| `downloads` | Téléchargement du média, des sous-titres et de la miniature, fichiers écrits à côté (`metadata.json`, transcript) |
| `sponsorblock` | Appel à l'API SponsorBlock |
| `subtitles` | Lecture d'un fichier `.vtt` en lignes de transcript horodatées (`read_transcript_lines`), partagée par l'écriture de `transcript.txt` et la page de la fiche |
| `sponsor_segments` | Segments sponsors d'une fiche : récupération, enregistrement, segments actifs ; recherche à la demande avec son message d'échec (`refresh_sponsor_segments`) |
| `url_guard` | Refus des URL qui visent la machine locale ou un réseau privé (SSRF) |
| `view_counts` | Nombre de vues et durée d'une fiche, lus depuis `metadata.json` |

### `llm/`

| Module | Responsabilité |
|---|---|
| `provider` | Interface `LLMProvider` et `AnthropicProvider` (API Anthropic directe), dont la boucle d'appels d'outils du chat bibliothèque |
| `prompts` | Construction des prompts (notes, résumé, analyse vidéo, question sur un transcript, chat bibliothèque) et découpage des réponses |
| `usage` | Coût réel d'un job LLM d'après les jetons comptés par le fournisseur, totaux et dépense par mois |

### `media/`

| Module | Responsabilité |
|---|---|
| `media_storage` | Purge quotidienne des fichiers des fiches Vu (sauf celles qu'un utilisateur a notées 4+ : `is_archived`), suppression d'un seul format, type de média d'après les chemins |
| `storage` | Espace utilisé et marge restante sous le quota global pour les téléchargements automatiques |
| `thumbnails` | Copies réduites de la miniature de chaque fiche |
| `audio_extract` | Audio tiré d'une vidéo déjà téléchargée, sans nouveau téléchargement |

### `channels/`

| Module | Responsabilité |
|---|---|
| `manage` | Ajout et suppression d'une chaîne, catégories, cloches (`set_channel_bell` dit si la cloche vient de passer à active) |
| `listing` | Liste de `/channels` et de `GET /api/channels` : tri, filtre Notées, recherche, page (`channel_page`), nombre de fiches |
| `lookup` | Chaîne de la bibliothèque qui correspond à une URL ou un identifiant YouTube |
| `profile` | Avatar, bannière et description d'une chaîne |
| `subscriptions` | Aperçu et import du CSV d'abonnements YouTube |

### `ingest/`

| Module | Responsabilité |
|---|---|
| `scanner` | Scan des chaînes suivies (cloches actives) |
| `metadata_import` | Import de métadonnées d'une vidéo : fiche, miniature et transcript, sans fichier média ; appelé par le scan, les imports de playlist, l'exploration de chaîne et le formulaire d'import |
| `manual_download` | Téléchargement manuel du média (vidéo ou audio), fusionné dans la fiche existante s'il y en a une |
| `transcript_retry` | Nouvelle tentative de téléchargement des sous-titres d'une fiche |
| `transcript_backfill` | Rattrapage des transcripts manquants quand une piste originale existe |
| `local_upload` | Import d'un fichier vidéo ou audio déposé depuis l'appareil |
| `channel_exploration` | Arrêt et progression d'une exploration de chaîne (import de métadonnées de toute une chaîne) |
| `staging` | Dossier de staging : les fichiers y arrivent, puis rejoignent le dossier final en une fois |
| `identity` | Chaîne d'une vidéo et URL canonique |
| `throttle` | Pauses entre requêtes YouTube et `RateLimitedError` |
| `scan_events` | État du scan en cours, lu par la page des paramètres |

### `playlists/`

| Module | Responsabilité |
|---|---|
| `imports` | Aperçu d'une playlist YouTube, lecture du CSV Google Takeout, ajout d'une entrée à la playlist, export CSV |
| `editing` | Édition d'une playlist et de ses éléments ; recherche d'une playlist ou d'un élément (`find_playlist`, `find_playlist_item`), titre obligatoire (`playlist_title`) |
| `listing` | Données des pages `/playlists` et `/playlists/{id}` et de leurs jumelles `/api`, en valeurs brutes : liste avec couvertures, détail chargé d'avance, lignes et compteurs, export CSV (`playlist_csv_export`) |

### `videos/`

| Module | Responsabilité |
|---|---|
| `filters` | Filtres de la bibliothèque, en Python et en SQL, dont le filtre des Nouveautés ; ce que contient une fiche (`video_badges`) |
| `library_query` | Liste paginée de `/videos`, de la page d'une chaîne et de `GET /api/videos`, calculée en SQL |
| `library_view` | Ce que montre la bibliothèque pour un jeu de filtres (`LibraryFilters`, construit et validé par `library_filters`), sans HTTP : chaîne et section, page de fiches, compteurs, cartes, vues enregistrées actives ; sert `/videos` et `GET /api/library` |
| `list_state` | État Vu/Indésirée d'une carte : choix enregistré, sinon déduit de la lecture ; catégories sans barre de progression (`card_list_states`) |
| `playback` | Activité de lecture : enregistrement (et passage en Vu à 90 %, type `video` ou `audio` seulement), positions, temps d'écran, historique |
| `editing` | Modifications d'une fiche : catégories, commentaire, titre, Vu/Indésirée |
| `documents` | Fichiers écrits à côté d'une fiche : `metadata.json`, et à côté du transcript les notes, résumés, questions, discussion par vidéo |
| `detail_view` | Ce que montre la page d'une fiche (`/videos/{id}` et `GET /api/videos/{id}`), sans HTTP et en valeurs brutes : documents, transcript horodaté, métadonnées, segments sponsors, positions de reprise ; lecture seule (`video_detail`), sauf l'ouverture de la page (`open_video_detail`) qui sort la fiche des Nouveautés |
| `download_options` | Validation des options d'un téléchargement manuel (formats, sous-titres, qualité) |
| `stats` | Compteurs de la bibliothèque pour `/settings` et `GET /api/stats` |
| `charts` | Données de la page `/stats` et de `GET /api/stats/charts` (`library_stats` : graphiques, parts par type et par format, purges, jauge du quota) |
| `nouveautes` | Les Nouveautés (`GET /api/nouveautes`) : une pile des fiches les plus récentes par chaîne suivie, paginée par chaîne |
| `youtube_search` | La section Recherche (`GET /api/youtube/videos`) : vidéos trouvées sur YouTube, chacune avec sa fiche si la bibliothèque l'a déjà (`youtube_video_candidates`) |
| `history` | L'Historique (`GET /api/historique`) : une ligne par média et par jour local (temps regardé additionné, Revu), et le temps de lecture de chaque jour de la page |

### `raton/`

| Module | Responsabilité |
|---|---|
| `scenarios` | Catalogue des scénarios de Raton (voir [18 Raton](18-raton-scenarios.md)) |
| `picker` | Choix de la réplique affichée à un chargement de page |
| `visits` | Dernière visite, répliques déjà dites, contexte d'un chargement de page |

### `rag/`

| Module | Responsabilité |
|---|---|
| `embeddings` | Embeddings et reranking par l'API Voyage AI |
| `indexing` | Découpage et embedding des notes d'une fiche en `video_note_chunks`, rattrapages d'indexation |
| `retrieval` | Recherche des passages de notes les plus pertinents pour une question |
| `auto_notes` | Génération nocturne des notes et du résumé court des fiches qui n'en ont pas |
| `dashboard`, `dashboard_stats` | Données de la page `/rag` et de `GET /api/rag` : état de l'indexation, coûts, historique, échecs, couverture |

Voir [19 Indexation et recherche dans les notes](19-indexation-et-recherche-notes.md).

### `library_chat/`

| Module | Responsabilité |
|---|---|
| `schema` | Outils que le modèle peut appeler (noms, descriptions, schémas d'entrée) et leurs bornes |
| `tools` | Exécution de ces outils (recherche de chaînes, de vidéos, de notes ; ajout d'une chaîne) et références citées par la réponse |
| `history` | Discussions (`library_chat_conversations`) et leurs messages (`library_chat_messages`) : ouverture, liste, lecture, ajout d'un échange, suppression |

Voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).

### `jobs/`

Fonctions exécutées en tâche de fond (`BackgroundTasks`) dans le processus
web ; chacune ouvre sa propre session DB.

| Module | Responsabilité |
|---|---|
| `downloads` | Tâches de fond : téléchargement manuel, relance du transcript, import de métadonnées d'une chaîne |
| `download_requests` | Côté requête de ces tâches, partagé par les formulaires et `/api` : validation et mise en file depuis la page d'import (`queue_manual_download`), une fiche (`queue_media_download`, `queue_transcript_retry`), une chaîne (`queue_channel_metadata_import`, `queue_channel_catalog_sync`) ou les formats manquants d'une playlist (`queue_playlist_downloads`) ; import synchrone du partage iOS (`import_shared_video`) ; état (`job_status`) et arrêt (`cancel_job`) d'un job |
| `playlists` | Import d'une playlist depuis son URL ou un CSV Google Takeout ; création de la playlist et mise en file (`queue_playlist_url_import`, `queue_playlist_csv_import`, `queue_playlist_refresh`) |
| `llm_jobs` | Création (`enqueue_llm_job`) et exécution (`run_llm_job`) d'un `LlmJob`, indexation des notes qu'un `generate` vient d'écrire |
| `llm_requests` | Une demande au LLM (notes d'une fiche, question sur une fiche, question au chat bibliothèque) : prompt et mise en file (`queue_*`), puis état du job et écriture de son résultat au premier poll (`resolve_llm_job`), appelés par `/api` (et par le repli sans JavaScript de la génération des notes) |
| `backfills` | Rattrapages : profils de chaînes, nombres de vues, transcripts, index des notes, miniatures |
| `scheduler` | Planificateur APScheduler : scan, purge des médias, notes automatiques ; scan lancé à la main depuis `/settings` |

Voir [13 Jobs, logs et planification](13-jobs-logs-planification.md).

---
title: "12 API et routes"
---
# 12 API et routes

## Routes HTML principales

Chaines :

- `GET /channels` : page chaines. `?sort=` accepte `activity` (defaut, dernier
  media joue), `rating`, `alpha` (A-Z) et `added` (ajoutees recemment : date
  de creation de la chaine, la plus recente d'abord).
- `GET /channels` accepte `?added_channel_id=<id>` : affiche la notification
  "chaine ajoutee" avec un lien vers la chaine (voir
  [11 Interface HTML](11-interface-html.md)).
- `GET /channels` accepte `?youtube_q=<nom>` (et `youtube_categories`) :
  lance la recherche de chaines YouTube et affiche les candidates.
- `POST /channels` : avec une URL ou un `@handle`, ajouter la chaine puis
  redirection vers `/channels?sort=added&added_channel_id=<id>` (ou vers `/channels`
  avec un message d'erreur si elle est deja dans la bibliotheque). Avec un
  nom libre, rien n'est ajoute : redirection vers
  `/channels?youtube_q=<nom>&youtube_categories=<labels>`. L'ajout lance en
  arriere-plan le job de rattrapage du profil (description, mots-cles,
  avatar, banniere).
- `POST /channels/import-csv` : upload d'un CSV d'abonnements YouTube (export
  Google Takeout, en-tetes `ID des chaines,URL des chaines,Titres des
  chaines`) ; parse le fichier et re-affiche la page chaines avec un apercu
  des chaines trouvees (deja importees vs nouvelles), sans rien ecrire en
  base.
- `POST /channels/import-csv/confirm` : cree les chaines cochees dans
  l'apercu (celles non deja presentes dans la DB, dedupliquees par
  `yt_channel_id`/`url`) ; ne fait aucun appel yt-dlp pendant la requete, les
  infos viennent directement du CSV. Si au moins une chaine est creee, le job
  de rattrapage du profil est lance en arriere-plan.
- `POST /channels/{id}/rating` : note de 0 à 5, redirige (303) vers `next`.
  Repli sans JavaScript : les étoiles appellent `PUT /api/channels/{id}/rating`
  sans rechargement de page.
- `POST /channels/{id}/categories` : modifier les categories de la chaine.
- `POST /channels/{id}/auto-metadata` : bascule une cloche de suivi quotidien
  selon le champ de formulaire `section` — `videos` (defaut,
  `auto_metadata_enabled`) ou `shorts` (`auto_shorts_enabled`) ; l'activation
  declenche un import metadata de cette section en arriere-plan.
- `POST /channels/{id}/import-metadata` : importer une page de metadata.
- `POST /channels/{id}/refresh-profile` : relance en arriere-plan la
  recuperation du profil de la chaine (`run_channel_profile_refresh_job`),
  redirige (303) vers `next` avec un message (`404` si la chaine n'existe
  pas).
- `GET /channels/{id}/avatar` et `GET /channels/{id}/banner` : servent l'image
  de profil (`Cache-Control: public, max-age=86400`) ; `404` si la chaine ou
  l'image n'existe pas, ou si le chemin stocke sort de `_channels/` (garde
  `is_relative_to`, comme les routes media des videos).
- `POST /channels/{id}/delete` : supprimer la chaine et ses fiches (cascade en
  base ; les fichiers des videos sur disque ne sont pas effaces, seul le
  dossier de profil `_channels/<yt_channel_id>/` l'est). Declenchee depuis la page
  de la chaine apres l'avertissement de confirmation.

Playlists :

- `GET /playlists` : page playlists (grille de cartes + panneau d'ajout a trois formulaires).
- `POST /playlists` : creation manuelle (titre seul).
- `POST /playlists/import-url` : import depuis une URL de playlist YouTube ;
  cree la playlist tout de suite (resolution synchrone) puis lance
  l'import des videos (metadonnees seules) en arriere-plan, puis redirige vers
  la playlist. Repli sans JavaScript de `POST /api/playlists/import-url`, que le
  formulaire appelle pour suivre le job dans la page.
- `POST /playlists/import-csv` : import depuis un CSV Google Takeout (un
  fichier `Vidéos de <Titre>.csv` a la fois, champ `file`) ; meme contrat que
  l'import par URL, repli de `POST /api/playlists/import-csv`. Pas d'etape de previsualisation/confirmation
  (contrairement a `/channels/import-csv`).
- `GET /playlists/{id}` : detail playlist (lecteur video/audio, file de
  lecture ordonnee, retrait/reordonnancement).
- `POST /playlists/{id}/rename` : renommer (`title`).
- `POST /playlists/{id}/categories` : remplace les labels de la playlist
  (`preset_categories`, `custom_categories`, comme `POST /channels/{id}/categories`)
  et les copie sur ses videos qui n'ont aucun label ;
- `POST /playlists/{id}/free-listening` : active/desactive l'ecoute libre
  (`enabled=1|0`) puis redirige ; le lecteur appelle
  `PUT /api/playlists/{id}/free-listening`. Le glisser-deposer de la file
  appelle `PUT /api/playlists/{id}/order` (il n'y a pas de route HTML).
- `POST /playlists/{id}/sort` : trie et reecrit les positions
  (`by=added|duration|title|reverse`).
- `POST /playlists/{id}/duplicate` : copie en playlist manuelle
  (`<titre> (copie)`).
- `GET /playlists/{id}/export.csv` : export au format Takeout par playlist,
  relisible par l'import CSV.
- `POST /playlists/{id}/refresh` : relance l'import par URL (playlist `url`
  seulement) ; ajoute les nouvelles videos sans toucher a l'ordre existant.
- `POST /playlists/{id}/download/{audio|video}` : met en file un telechargement
  par video de la playlist qui n'a pas encore ce fichier (les autres sont
  ignorees).
- `POST /playlists/{id}/delete` : supprimer la playlist (ne supprime jamais
  les videos qu'elle contenait).
- `POST /playlists/{id}/items/{item_id}/remove` : retirer une video de la
  playlist.
- `POST /playlists/{id}/items/{item_id}/move` : monter/descendre une video
  dans l'ordre de la playlist (`direction=up|down`).
- `POST /videos/{id}/playlists` : depuis la page detail d'une video, ajouter
  cette video a une playlist existante (`playlist_id`) ou a une nouvelle
  playlist creee a la volee (`new_playlist_title`).

Videos :

- `GET /` : accueil (barre de chat de la bibliotheque seule).
- `GET /dashboard/nouveautes?page=N` : page complete, une pile de videos recentes par chaine suivie (cloche videos ou shorts active, chaque cloche ne listant que son type), paginee par chaine (10 chaines/page, `page`=chaines et non videos).
- `GET /dashboard/historique?page=N` : page complete paginee (50/page) de l'activite "Historique".
- `GET /dashboard/reprises?page=N` : ancienne URL de la page ci-dessus, conservee en redirection 302 (temporaire, pour ne pas figer un 301 dans le cache des navigateurs) vers `/dashboard/historique`, `page` preservee.
- `GET /stats` : page de graphiques (stockage et fiches par chaine, par format, par mois) ; voir [11 Interface HTML](11-interface-html.md).
- `GET /rag` : tableau de bord de l'indexation des notes (etape de chaque
  video, prochain lot, lot en cours, activite, cout, index, echecs, lexique) ;
  lecture seule, aucune route d'ecriture ; voir [11 Interface HTML](11-interface-html.md)
  section "Indexation RAG". Les memes donnees en JSON : `GET /api/rag`.
- `GET /videos` : liste videos. Parametre `sort` : `imported`, `published`
  (defaut sur une chaine), `views` ou `rated` (note decroissante). Avec
  `channel_id` d'une chaine existante, rend `channel_videos.html` (page
  d'une chaine) au lieu de `videos.html`.
- `POST /videos/{id}/categories` : modifier les categories de la video.
- `POST /videos/{id}/comment` : commentaire libre (texte, champ `comment`).
- `POST /videos/{id}/rating` : note de 0 à 5, redirige (303) vers `next`.
  Repli sans JavaScript : les étoiles appellent `PUT /api/videos/{id}/rating`.
  Les boutons **Vu** / **Écartée** appellent `PUT /api/videos/{id}/list-state`
  et la lecture est rapportee par `POST /api/videos/{id}/activity` : ni l'un ni
  l'autre n'a de route HTML.
- `GET /videos/{id}` : detail video.
- `GET /videos/{id}/thumbnail` : vignette.
- `GET /videos/{id}/subtitles` : sous-titres bruts.
- `GET /videos/{id}/audio` : stream audio.
- `GET /videos/{id}/video` : stream video.
- `POST /videos/{id}/media/{media_type}/delete` : supprimer un format local
  (`audio` ou `video`) ; utilisee uniquement depuis la page detail video.
- `POST /videos/{id}/media/{media_type}/download` : telecharger le format
  manquant (`audio` ou `video`) pour une fiche existante, sans passer par
  l'URL cote client (elle est relue depuis `video.url` dans la DB). Cree un
  `DownloadJob` et le lance en arriere-plan comme `/videos/download`, puis
  redirige vers `next` (chemin interne) ; `video_quality` vaut 1080 par
  defaut. Repli sans JavaScript : la barre d'actions de la page detail video,
  la file de telechargement des playlists et le clic sur une tuile de short
  sans fichier local appellent `POST /api/videos/{id}/media/{kind}/download`
  et suivent le job par `GET /api/jobs/{id}`.
- `GET /videos/cards?ids=…&section=…` : HTML des cartes (`_video_cards.html`)
  des fiches indiquees, pour l'exploration d'une chaine (voir « Page d'une
  chaine » dans [11 Interface HTML](11-interface-html.md)).
- `GET /raton/variations` : toutes les repliques de Raton, sans condition
  (voir [18 Raton](18-raton-scenarios.md)).
- `GET /videos/{id}/transcript` : redirection vers detail ancre transcript.
- `POST /videos/{id}/transcript/generate` : generer les notes structurees, le resume (+ resume court + questions suggerees) en un seul appel LLM, a partir de `transcript.txt` — voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).
- `POST /videos/{id}/transcript/chat` : poser question.
- `POST /videos/{id}/transcript/chat/clear` : effacer chat.
- `GET /videos/{id}/transcript/jobs/{job_id}` : statut/resolution d'un job LLM asynchrone, tous fournisseurs confondus (traite en tache de fond dans le process web) ; pour un job `generate` en cours, renvoie aussi le résumé court deja ecrit (`partial_short_summary`).
- `POST /videos/{id}/sponsors/fetch` : rechercher les segments sponsorises via l'API publique SponsorBlock — **seule source** — pour les categories activees (`/settings`) ; remplace uniquement les lignes `source="sponsorblock"` de la video. Repond en JSON (`{status, message}`) si l'appel porte l'en-tete `X-Requested-With: fetch`, sinon redirige vers `/videos/{id}?message=...#segments-sponsors` (l'ancre ouvre l'onglet Segments ; `level=error` en cas d'echec) — voir [08 Medias et lecteurs](08-medias-et-lecteurs.md). Il n'existe plus de route de detection par IA : `POST /videos/{id}/sponsors/detect` a ete supprimee.
- `POST /chat` : chat cross-video (le modele cherche chaines, videos et notes via des outils), voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).
- `POST /chat/clear` : effacer le fil du chat cross-video (`library_chat_messages`, fil unique).
- `GET /chat/jobs/{job_id}` : statut/resolution d'un job `kind="library_chat"` (equivalent cross-video de `GET /videos/{id}/transcript/jobs/{job_id}`) ; `pending` porte aussi `tool_calls` (appels d'outils deja faits).
- `GET /videos/import` : page du formulaire de telechargement manuel (entree Import du menu Bibliotheque).
- `POST /videos/download` : telechargement manuel ; `subtitle_language` vide (defaut, le formulaire n'en envoie plus) laisse `choose_subtitle_track` choisir la piste originale.
- `POST /videos/upload` : import d'un fichier video ou audio depose sur la page d'import (champ multipart `file`). Extensions acceptees : celles de `VIDEO_EXTENSIONS`/`AUDIO_EXTENSIONS` (`app/services/youtube/downloads.py`), sinon 400. Le fichier va dans `Local/<YYYY-MM-DD> - <nom>/`, la video est rattachee a la chaine `Fichiers locaux` (`url` `local://files`, cloches desactivees) avec `yt_video_id` = `local:<sha1 du contenu>` (un meme contenu n'est pas importe deux fois). Redirige vers la fiche ; repli sans JavaScript de `POST /api/videos/upload`, qu'appelle la page d'import. Pas de transcript ni de metadonnees YouTube.
- `POST /videos/share-import` : point d'entree du raccourci iOS de la feuille de
  partage (Safari/YouTube). Champ de formulaire `url` ; seuls les liens
  YouTube (`youtube.com`, `m.`/`music.`, `youtu.be`) sont acceptes (400 JSON
  sinon). Meme import que le formulaire par defaut (metadonnees + transcript,
  aucun fichier media), mais **synchrone** : la requete attend la fin de
  l'import pour que le raccourci puisse ouvrir la fiche. Succes : JSON
  `job_id`, `status`, `message`, `video_id`, `video_url` (absolue, construite
  avec l'hote utilise par l'appelant). Echec de l'import : 502 JSON avec
  `message`. Jamais de redirection. Sans authentification : reseau local /
  WireGuard uniquement.
- `POST /videos/import-metadata` : import metadata video.

Parametres et divers :

- `GET /settings` : page parametres.
- `POST /settings` : mise a jour parametres.
- `POST /settings/scan` : lance le scan des chaines suivies a la demande (meme
  traitement que le cron de 3h, via `scheduled_scan`) en tache de fond. Repond
  toujours en JSON : `{status: "started", message, after}` (`after` = dernier
  identifiant d'evenement deja emis), ou `409 {status: "already_running"}` si un
  scan tourne.
- `GET /settings/scan/events?after=N` : evenements du scan emis apres `N`,
  `{events: [{id, level, message, final}], last_id, running}`. Flux en memoire du
  processus (`app/services/ingest/scan_events.py`), pas une table.
- `GET /logs` : logs jobs, filtres `status` (`all`, `errors`, `warnings`, `running`), `q` (recherche) et `page` (voir [11 Interface HTML](11-interface-html.md), section Logs).

Le scan des chaines n'a pas de route dans `/api` : il est declenche par le
scheduler ou par `POST /settings/scan` (voir
[13 Jobs, logs et planification](13-jobs-logs-planification.md)).

## API interne `/api`

Conventions communes : une modification envoie un corps JSON (`PUT` pour
fixer une valeur) et repond l'etat modifiable de ce qu'elle a change ; les
categories d'une chaine, d'une fiche ou d'une playlist se lisent toujours
`categories`, une liste de libelles normalises (la colonne `category_labels`
ne sort pas de l'API).

Erreurs : toute erreur de `/api` repond `{"detail": "<message en francais>"}`
(`ErrorRead`, `app/api/errors.py`). Un refus metier porte le message du
service (`400`, `404`, `409`, `502`) ; une requete invalide repond `422` avec
un `detail` lisible (`Requête invalide : state : champ obligatoire.`) et
`errors`, la liste `{field, message}` des champs en cause (les routes HTML
gardent la reponse `422` par defaut de FastAPI). Chaque route declare dans le
schema OpenAPI les codes d'erreur qu'elle peut repondre, et toutes ses
reponses sont typees ; le schema (`/docs`) ne decrit que `/api`.
`tests/test_api_contract.py` verifie ces regles.

- `GET /api/channels?sort=…&rated=true|false&q=…&page=N` : une page de 50
  chaines, memes tris (`activity` par defaut, `rating`, `alpha`, `added` ; un
  tri inconnu donne `activity`), meme recherche et meme filtre Notees que
  `/channels` (`channel_page`). Contrairement a la page, toutes les chaines
  sont listees sauf `rated=true`. Repond `{items, sort, page, total_pages,
  total}` ; chaque chaine `{id, url, name, yt_channel_id, rating,
  categories, auto_metadata_enabled, auto_shorts_enabled, created_at,
  video_count, last_played_at}` (`last_played_at` : derniere lecture d'une de
  ses fiches, `null` sinon). Le nombre de requetes ne depend pas du nombre de
  chaines affichees.
- `GET /api/channels/{id}` : la chaine plus son profil : `description`,
  `keywords` (liste), `avatar_url` et `banner_url` (`/channels/{id}/avatar`,
  `/channels/{id}/banner`, `null` sans image), `metadata_fetched_at`,
  `last_scanned_at`, `video_count`.
- `POST /api/channels` `{url, rating}` (`rating` facultatif, `1`) : lance aussi
  le rattrapage du profil en arriere-plan ; `409` si la chaine est deja dans
  la bibliotheque, reconnue par son identifiant YouTube quelle que soit l'URL
  donnee (meme regle que le formulaire de `/channels`) ; `400 La note doit
  être comprise entre 0 et 5.` pour une note hors bornes.
- `PUT /api/channels/{id}/rating` `{rating}` : note de 0 a 5, repond l'etat de
  la chaine (voir Actions sur une chaine) ; `400` avec le meme message sinon.
- `DELETE /api/channels/{id}` : supprime aussi le dossier de profil de la chaine
- `GET /api/videos?channel_id=<id>&page=N` : fiches les plus recemment
  importees d'abord, 50 par page (meme taille et meme requete SQL que la
  liste `/videos`). Repond `{items: [...], page, total_pages, total}` ; une
  `page` au-dela de la derniere renvoie la derniere, `page=0` donne `422`.
- `GET /api/videos/{id}` : ce que montre la page de la fiche, en valeurs
  brutes (meme service `detail_view` que `GET /videos/{id}`) : les champs de
  `GET /api/videos`, plus `is_new`, `list_state` (choix enregistre, pas
  l'etat deduit de la lecture), `comment`, `duration_seconds`, `watched_at`,
  `media_urls` (`video`, `audio`, `thumbnail`, `subtitles` : la route qui sert
  le fichier, `null` si la fiche n'a pas ce fichier), `metadata` (champs de
  `metadata.json` : `description`, `tags`, `chapters` `{title,
  start_seconds}`, `duration_seconds`, `view_count`, `like_count`,
  `comment_count`, `uploader` ; un nombre illisible vaut `null`),
  `documents` (`transcript`, `notes`, `short_summary`, `suggested_questions`,
  `chat_messages`), `sponsor_segments` (segments actifs), `skip_segments` et
  `sponsor_skip_enabled` (comme `GET /api/videos/{id}/sponsor-segments`),
  `resume_positions` (`{video|audio: {position_seconds, at_ms}}`) et
  `playlists` (`{playlist_id, title, item_id}`). Lecture seule :
  contrairement a la page, ne sort pas la fiche des Nouveautes. `404` si la
  fiche n'existe pas.
- `GET /api/library` : la liste de la bibliotheque (ou la page d'une chaine)
  en JSON, calculee par le meme service que `/videos` (`library_view`), 50
  fiches par page. Memes noms de parametres que `/videos` : `channel_id`,
  `section`, `sort`, `asset`, `category`, `exclude_asset`,
  `exclude_category` (repetables), `rated`, `hide_hidden`, `uncategorized`,
  `asset_filter_mode`, `category_filter_mode`, `q`, `page`. Memes regles de
  validation (`library_filters`) : un type de fichier, un tri, une section ou
  un mode inconnu est ignore ou remplace par son defaut, les categories sont
  normalisees. Seule difference : sans `asset`, aucun filtre de type de
  fichier (la page, elle, preselectionne Video et Audio, ou tous les types
  sur une chaine). Repond `{filters, channel, section, page, total_pages,
  total, counts, items, saved_views}` : `filters` les filtres reellement
  appliques, `counts` les compteurs de la page d'une chaine, `items` les
  cartes (champs de `GET /api/videos` plus `channel_name`,
  `duration_seconds`, `view_count`, `is_new`, `list_state`, `has_video`,
  `has_audio`, `has_thumbnail`, `playback` `{position_seconds,
  duration_seconds, progress_percent, is_completed}` ou `null`),
  `saved_views` les vues enregistrees avec `active`. `404` si `channel_id`
  ne designe aucune chaine. Le nombre de requetes SQL ne depend pas de la
  taille de la bibliotheque.
- `PUT /api/videos/{id}/rating` `{rating}` : note de 0 a 5, repond l'etat de
  la fiche (voir Actions sur une fiche) ; `400 La note doit être comprise
  entre 0 et 5.` sinon.
- `GET /api/videos/{id}/sponsor-segments` : segments a sauter pour cette video,
  au service du mini-lecteur persistant (qui se lance depuis n'importe quelle
  liste et n'a donc pas les segments dans le DOM de la page courante).
  Repond `{"skip_enabled": bool, "segments": [{"start": float, "end": float}]}`,
  `404` si la video n'existe pas. Applique le meme filtrage par categories
  activees et la meme normalisation (tri/fusion/rejet des segments < 1 s) que
  la page detail — voir [05 Modele de donnees](05-modele-de-donnees.md) et
  [08 Medias et lecteurs](08-medias-et-lecteurs.md).
- `GET /api/stats` : `{channels, videos, used_bytes, quota_bytes}`, memes
  compteurs que la page `/settings`.
- `GET /api/stats/charts` : memes donnees que la page `/stats` (stockage et
  fiches par chaine, par format, par mois) — voir
  [11 Interface HTML](11-interface-html.md). Chaque type de stockage et chaque
  format porte sa part (`percent`) ; plus `purged` (fiches purgees par mois),
  `spend` (depense LLM par mois), `quota_bytes` et `quota_percent`. `monthly`
  garde toute la fenetre de 12 mois : la page, elle, en retire les premiers
  mois vides et en tire son dessin (`monthly_view`).
- `GET /api/rag` : ce que montre `/rag` (`rag_dashboard_data`) : `buckets`
  (etape de chaque fiche), `pipeline` (etat du balayage, lot en cours,
  prochain passage), `next_batch`, `in_flight_videos`, `jobs`, `history`,
  `chunks`, `channels`, `failures`, `parameters`. Dates en ISO 8601,
  `pipeline.next_sweep_in` en duree ISO 8601 (`PT17H35M…`) ; les libelles et
  `family` (couleur) des etapes sont ceux de la page.
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/jobs?status=…` : les 100 derniers jobs du journal
  (`download_jobs`, comme `/logs`), le plus recent d'abord : `{id, status,
  message, channel_id, video_id, created_at, done}` ; `status` (repetable)
  ne garde que ces statuts. Remplace `GET /api/errors`, qui listait deja tous
  les statuts.

### Actions sur une chaine

Corps en JSON, memes services que les formulaires de `/channels` ;
`404 Chaîne introuvable` si la chaine n'existe pas. Les routes qui modifient
la chaine repondent son etat modifiable : `{id, name, rating, categories,
auto_metadata_enabled, auto_shorts_enabled}`. La liste, l'ajout, la note et
la suppression sont plus haut.

- `PUT /api/channels/{id}/categories` `{categories: [...]}` : remplace les
  categories de la chaine (normalisees).
- `PUT /api/channels/{id}/bells/{videos|shorts}` `{enabled}` : regle une
  cloche (idempotent, contrairement au formulaire qui bascule). Repond
  `{channel, job}` : `job` est l'import du catalogue existant lance quand la
  cloche vient de passer a active (sans marquer les fiches comme
  Nouveautes), `null` sinon. Une autre section donne `422`.
- `POST /api/channels/{id}/import-metadata` `{page, section}` (facultatif :
  `1`, `videos`) : importe une page des videos ou des shorts de la chaine
  (metadonnees seules), `202 {job_id, status, message, status_url}`.
- `POST /api/channels/{id}/refresh-profile` : relance la recuperation du
  profil (avatar, banniere, description) en arriere-plan, `202 {status,
  message}`.
- `POST /api/channels/import-csv` (multipart, champ `file`) : lit un CSV
  d'abonnements Google Takeout sans rien ecrire, comme `POST
  /channels/import-csv`. Repond `{rows, new_count, existing_count}` ; chaque
  ligne `{channel_id, url, name, already_imported, token}`. `400` avec le
  message du formulaire si le fichier n'est pas un export d'abonnements.
- `POST /api/channels/import-csv/confirm` `{tokens: [...]}` : ajoute les
  chaines des `token` de l'apercu qui ne sont pas deja dans la bibliotheque,
  `{added}` ; lance le rattrapage des profils si au moins une est ajoutee.

### Playlists

Corps en JSON, memes services que les pages `/playlists` ; `404 Playlist
introuvable` si la playlist n'existe pas. Une playlist se lit `{id, title,
source, source_url, yt_playlist_id, categories, free_listening,
created_at}`.

- `GET /api/playlists` : toutes les playlists, la plus recente d'abord, plus
  `item_count` et `cover_video_id` (premiere fiche, `null` si vide). Nombre de
  requetes constant.
- `POST /api/playlists` `{title}` : creation manuelle, `201` ; `400 Le titre
  est obligatoire.` pour un titre vide.
- `GET /api/playlists/{id}` : la playlist plus `stats` `{count,
  total_duration_seconds, seen_count, missing_audio, missing_video}` et
  `items` dans l'ordre (`{item_id, position, added_at, video_id, title,
  channel_name, duration_seconds, has_audio, has_video, seen}`).
- `GET /api/playlists/{id}/export.csv` : meme fichier que `GET
  /playlists/{id}/export.csv` (`playlist-<id>.csv`, format Takeout par
  playlist, relisible par `POST /api/playlists/import-csv`).
- `DELETE /api/playlists/{id}` : `204`, ne supprime jamais les fiches.
- `PUT /api/playlists/{id}/title` `{title}`, `PUT .../free-listening`
  `{enabled}` : repondent la playlist.
- `PUT /api/playlists/{id}/categories` `{categories}` : remplace les labels
  et les copie sur ses fiches qui n'en ont aucun ; repond `{playlist,
  labelled_count}`.
- `PUT /api/playlists/{id}/order` `{item_ids}` : tous les elements, dans le
  nouvel ordre ; `409` si la playlist a change entre-temps. `POST
  .../sort` `{by}` (`added`, `duration`, `title`, `reverse` ; `400` sinon),
  `POST .../items/{item_id}/move` `{direction: up|down}` : repondent le
  detail.
- `POST /api/playlists/{id}/items` `{video_id}` : ajoute la fiche a la fin,
  une seule fois (`201`, detail) ; `404 Vidéo introuvable`. `DELETE
  .../items/{item_id}` : retire l'element (jamais la fiche) et renumerote,
  `204` ; `404 Élément introuvable` si l'element n'est pas dans cette
  playlist.
- `POST /api/playlists/{id}/duplicate` : copie manuelle, `201`.
- `POST /api/playlists/preview` `{url}` : apercu d'une URL de playlist, rien
  n'est ecrit : `{title, channel_name, video_count, unavailable_count,
  duration_seconds, unknown_duration_count, known_in_library_count,
  sample_titles, truncated}` ; `404` si introuvable. Il n'y a pas de route
  HTML : le bouton **Prévisualiser** de `/playlists` l'appelle.
- `POST /api/playlists/import-url` `{url, title}` et `POST
  /api/playlists/import-csv` (multipart : `file`, `title` facultatif) : creent
  la playlist tout de suite et importent ses videos (metadonnees seules) en
  arriere-plan ; `202 {playlist, job}`. Sans titre : celui de YouTube, ou le
  nom du fichier (`Vidéos de X.csv` donne `X`). `404` pour une URL
  introuvable, `400` pour un CSV refuse.
- `POST /api/playlists/{id}/refresh` : relance l'import par URL (nouvelles
  videos ajoutees a la fin), `202` + job ; `400` si la playlist ne vient pas
  d'une URL.
- `POST /api/playlists/{id}/download/{audio|video}` : un telechargement par
  fiche qui n'a pas encore ce format, `202 {jobs: [...]}` (vide si rien ne
  manque) ; `400` pour un autre format.

### Demandes au LLM

Memes services que les routes HTML de
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md) ; corps
en JSON. Une demande repond `202 {job_id, status, status_url}` et tourne en
arriere-plan ; le client interroge `status_url` (`GET /api/llm-jobs/{id}`).

- `POST /api/videos/{id}/notes/generate` : notes structurees, resume court et
  questions suggerees depuis le transcript, en un appel ; `400` si la fiche
  n'a pas de transcript (`Génération impossible : …`).
- `POST /api/videos/{id}/chat` `{question}` : question sur le transcript de
  la fiche, a la suite de sa discussion ; `400 La question est vide.`.
  `DELETE /api/videos/{id}/chat` efface la discussion (`204`). La discussion
  elle-meme se lit dans `GET /api/videos/{id}` (`documents.chat_messages`).
- `GET /api/chat` : la conversation du chat bibliotheque (`messages`, chaque
  reponse avec les `channels` et `citations` qu'elle cite) et
  `indexed_video_count`/`total_video_count`. `POST /api/chat` `{question}` :
  pose une question (`202`) ; `DELETE /api/chat` efface la conversation
  (`204`).
- `GET /api/llm-jobs/{id}` : `{id, kind, video_id, status}` avec `status`
  `pending`, `done` ou `failed`. En attente : `partial_short_summary` (job
  `generate`, le resume deja ecrit) ou `tool_calls` (job `library_chat`).
  Le premier poll apres la fin ecrit le resultat (une seule fois, comme le
  poll de la page) et repond `documents` (`generate`, avec les nouvelles
  notes), `chat_messages` (`chat`) ou `library_chat` (`library_chat`) ;
  apres une generation, l'indexation des notes part en arriere-plan. Un job
  echoue repond `200` avec `status: failed` et `message` (`Génération
  impossible : …`, `Réponse impossible : …`). `404 Tâche introuvable`.

### Actions sur une fiche

Corps en JSON. Chaque route appelle le meme service que son formulaire HTML
(meme validation, memes messages d'erreur) ; `404 Vidéo introuvable` si la
fiche n'existe pas. Les routes qui modifient la fiche repondent son etat
modifiable : `{id, is_new, list_state, rating, categories, comment,
watched_at}`.

- `POST /api/videos/{id}/open` : ce que fait l'ouverture de sa page, la
  sort des Nouveautes (`GET /api/videos/{id}`, lui, ne change rien).
- `PUT /api/videos/{id}/list-state` `{state}` : `watched`, `unwatched`,
  `hidden`, ou `clear` pour revenir a l'etat deduit de la lecture ; `400`
  sinon. Appelee par les boutons **Vu** / **Écartée**.
- `PUT /api/videos/{id}/categories` `{categories: [...]}` : remplace les
  categories de la fiche (normalisees, ajoutees a la liste des categories).
- `PUT /api/videos/{id}/comment` `{comment}` : une chaine vide efface le
  commentaire.
- `POST /api/videos/{id}/activity` `{media_type, position_seconds,
  duration_seconds, watched_seconds}` : rapport de lecture d'un lecteur, peut
  passer la fiche en Vu ; `media_type` vaut `video` ou `audio` (`400`
  sinon). Appelee par les lecteurs de la fiche, des playlists et des shorts.
- `POST /api/videos/{id}/media/{audio|video}/download` `{video_quality}`
  (facultatif, `1080` par defaut) : `202 {job_id, status, message,
  status_url}`, le telechargement tourne en arriere-plan ; `400` pour un
  autre format ou une qualite inconnue.
- `DELETE /api/videos/{id}/media/{audio|video}` : `204` ; `400` si le
  format est refuse (meme regle que `POST /videos/{id}/media/{type}/delete`).
- `POST /api/videos/{id}/transcript/download` : nouvelle tentative de
  recuperation du transcript (FR en priorite, repli EN) d'une fiche dont le
  transcript est manquant ou en echec, `202` comme un telechargement ; voir
  "Recuperation manuelle du transcript" dans
  [07 YouTube et telechargements](07-youtube-et-telechargements.md). Il n'y a
  pas de route HTML : le bouton de la page detail l'appelle.
- `POST /api/videos/{id}/sponsor-segments/fetch` : interroge SponsorBlock et
  remplace les segments `sponsorblock` de la fiche ; repond `{count,
  skip_enabled, segments}` (comme `GET /api/videos/{id}/sponsor-segments`),
  `502` si SponsorBlock ou l'enregistrement echoue.
- `GET /api/jobs/{id}` : etat d'un job lance par ces actions, a interroger
  jusqu'a `done` : `{id, status, message, video_id, done}`, plus `videos`
  (fiches deja importees) pour une exploration de chaine ; `404 Job
  introuvable`. `GET /api/jobs?status=…` liste les jobs recents (les erreurs
  de la bulle de Raton). `POST /api/jobs/{id}/cancel` passe un job d'import de
  chaine en `cancelled` (bouton × de la bulle) : l'import s'arrete avant la
  fiche suivante ; repond l'etat du job.

### Import de fiches

- `POST /api/videos/import` `{url, media_types, download_transcript,
  video_quality, categories}` (facultatifs : `["metadata"]`, `true`,
  `1080`, `[]`) : telechargement manuel d'une URL, comme le formulaire de
  `/videos/import` ; `202 {job_id, status, message, status_url}`, `400` pour
  une URL ou une option refusee.
- `POST /api/videos/upload` (multipart, champ `file`) : importe un fichier
  video ou audio comme `POST /videos/upload` ; `201 {video_id, created}`
  (`created` vaut `false` si le meme contenu etait deja importe), `400` pour
  une extension refusee.

Les messages d'erreur de `/api` (champ `detail`) sont en francais, comme
ceux des pages HTML : une erreur levee par un service renvoie son propre
message (`Chaîne introuvable pour …`, `… est déjà dans la bibliothèque.`),
un identifiant inconnu donne `Chaîne introuvable` ou `Vidéo introuvable`.

## Redirections

Le helper `redirect()` utilise `303 See Other`.

Les retours utilisateur doivent etre des chemins internes :

- accepter seulement les chemins commencant par `/` ;
- refuser `//...` ;
- fallback `/videos`.

## Reponses media

Pour audio/video :

- `200 OK` sans header Range ;
- `206 Partial Content` avec Range valide ;
- `416` avec `Content-Range: bytes */{file_size}` si Range invalide ;
- `404` si video, fichier ou chemin invalide.

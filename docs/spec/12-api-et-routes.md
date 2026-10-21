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
- `POST /channels/{id}/rating` : note de 0 à 5. Redirige (303) vers `next` ;
  avec l'en-tete `X-Requested-With: fetch`, repond en JSON `{"rating": N}`
  (`404` si la chaine n'existe pas). Appelee en `fetch` par les étoiles, sans
  rechargement de page.
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
- `POST /playlists/preview` : apercu d'une URL de playlist avant import
  (formulaire `url`) ; lecture `yt-dlp` seule, **rien n'est cree dans la DB**.
  Repond en JSON `{status, title, channel_name, video_count,
  unavailable_count, duration_seconds, duration_label,
  unknown_duration_count, known_in_library_count, sample_titles,
  truncated}`, ou 404 `{status: "failed", message}` si la playlist est
  introuvable.
- `POST /playlists/import-url` : import depuis une URL de playlist YouTube ;
  cree la playlist tout de suite (resolution synchrone) puis lance
  l'import des videos (metadonnees seules) en arriere-plan. Repond en JSON
  (`{job_id, status, message, status_url, return_to}`) si l'appel porte
  l'en-tete `X-Requested-With: fetch`, sinon redirige.
- `POST /playlists/import-csv` : import depuis un CSV Google Takeout (un
  fichier `Vidéos de <Titre>.csv` a la fois) ; meme contrat synchrone/JSON que
  l'import par URL. Pas d'etape de previsualisation/confirmation
  (contrairement a `/channels/import-csv`).
- `GET /playlists/{id}` : detail playlist (lecteur video/audio, file de
  lecture ordonnee, retrait/reordonnancement).
- `POST /playlists/{id}/rename` : renommer (`title`).
- `POST /playlists/{id}/categories` : remplace les labels de la playlist
  (`preset_categories`, `custom_categories`, comme `POST /channels/{id}/categories`)
  et les copie sur ses videos qui n'ont aucun label ;
- `POST /playlists/{id}/free-listening` : active/desactive l'ecoute libre
  (`enabled=1|0`) ; repond en JSON avec `X-Requested-With: fetch`.
- `POST /playlists/{id}/reorder` : applique un nouvel ordre
  (`item_ids=1,2,3`, tous les items de la playlist exactement) ; `409`
  (`{"status":"stale"}`) si la liste a change entre-temps.
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
  section "Indexation RAG".
- `GET /videos` : liste videos. Parametre `sort` : `imported`, `published`
  (defaut sur une chaine), `views` ou `rated` (note decroissante). Avec
  `channel_id` d'une chaine existante, rend `channel_videos.html` (page
  d'une chaine) au lieu de `videos.html`.
- `POST /videos/{id}/categories` : modifier les categories de la video.
- `POST /videos/{id}/comment` : commentaire libre (texte, champ `comment`).
- `POST /videos/{id}/rating` : note de 0 à 5. Redirige (303) vers `next` ;
  avec l'en-tete `X-Requested-With: fetch`, repond en JSON `{"rating": N}`
  (`404` si la video n'existe pas). Appelee en `fetch` par les étoiles, sans
  rechargement de page.
- `POST /videos/{id}/list-state` : etat de grisage de la carte dans les listes.
  Champ `state` valant `watched`, `unwatched`, `hidden` ou `clear` (retour a la
  detection automatique). Repond en JSON `{"state": <valeur stockee ou null>}`,
  `400` si `state` est inconnu, `404` si la video n'existe pas. Appelee en
  `fetch` par les boutons **Vu** / **Écartée**, sans rechargement de page.
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
  `DownloadJob` et le lance en arriere-plan comme `/videos/download` ; repond
  en JSON (`{job_id, status, message, status_url}`) si l'appel porte l'en-tete
  `X-Requested-With: fetch`, sinon redirige. Le champ optionnel `next`
  (chemin interne) est renvoye en `return_to` dans la reponse JSON et sert de
  cible a la redirection ; `video_quality` vaut 1080 par defaut. Utilisee par
  la barre d'actions de la page detail video, par la file de telechargement
  des playlists et par le clic sur une tuile de short sans fichier local.
- `POST /videos/{id}/activity` : enregistrer une activite de lecture
  (`played`/`prompt`).
- `GET /videos/cards?ids=…&section=…` : HTML des cartes (`_video_cards.html`)
  des fiches indiquees, pour l'exploration d'une chaine (voir « Page d'une
  chaine » dans [11 Interface HTML](11-interface-html.md)).
- `POST /jobs/{id}/cancel` : passe un job d'import de chaine en `cancelled`
  (bouton × de la bulle de Raton) ; l'import s'arrete avant la fiche suivante.
- `GET /raton/variations` : toutes les repliques de Raton, sans condition
  (voir [18 Raton](18-raton-scenarios.md)).
- `GET /videos/{id}/transcript` : redirection vers detail ancre transcript.
- `POST /videos/{id}/transcript/generate` : generer les notes structurees, le resume (+ resume court + questions suggerees) en un seul appel LLM, a partir de `transcript.txt` — voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).
- `POST /videos/{id}/transcript/download` : retenter la recuperation du
  transcript (FR en priorite, repli EN) pour une video dont le transcript est
  manquant/en echec — voir "Recuperation manuelle du transcript" dans
  [07 YouTube et telechargements](07-youtube-et-telechargements.md). Cree un
  `DownloadJob` et le lance en arriere-plan comme les telechargements de
  format ; meme reponse JSON/redirection que `/videos/{id}/media/{media_type}/download`,
  suivie via `GET /videos/download-jobs/{id}`.
- `POST /videos/{id}/transcript/chat` : poser question.
- `POST /videos/{id}/transcript/chat/clear` : effacer chat.
- `GET /videos/{id}/transcript/jobs/{job_id}` : statut/resolution d'un job LLM asynchrone, tous fournisseurs confondus (traite en tache de fond dans le process web) ; pour un job `generate` en cours, renvoie aussi le résumé court deja ecrit (`partial_short_summary`).
- `POST /videos/{id}/sponsors/fetch` : rechercher les segments sponsorises via l'API publique SponsorBlock — **seule source** — pour les categories activees (`/settings`) ; remplace uniquement les lignes `source="sponsorblock"` de la video. Repond en JSON (`{status, message}`) si l'appel porte l'en-tete `X-Requested-With: fetch`, sinon redirige vers `/videos/{id}?message=...#segments-sponsors` (l'ancre ouvre l'onglet Segments ; `level=error` en cas d'echec) — voir [08 Medias et lecteurs](08-medias-et-lecteurs.md). Il n'existe plus de route de detection par IA : `POST /videos/{id}/sponsors/detect` a ete supprimee.
- `POST /chat` : chat cross-video (le modele cherche chaines, videos et notes via des outils), voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).
- `POST /chat/clear` : effacer le fil du chat cross-video (`library_chat_messages`, fil unique).
- `GET /chat/jobs/{job_id}` : statut/resolution d'un job `kind="library_chat"` (equivalent cross-video de `GET /videos/{id}/transcript/jobs/{job_id}`) ; `pending` porte aussi `tool_calls` (appels d'outils deja faits).
- `GET /videos/import` : page du formulaire de telechargement manuel (entree Import du menu Bibliotheque).
- `POST /videos/download` : telechargement manuel ; `subtitle_language` vide (defaut, le formulaire n'en envoie plus) laisse `choose_subtitle_track` choisir la piste originale.
- `POST /videos/upload` : import d'un fichier video ou audio depose sur la page d'import (champ multipart `file`). Extensions acceptees : celles de `VIDEO_EXTENSIONS`/`AUDIO_EXTENSIONS` (`app/services/youtube/downloads.py`), sinon 400. Le fichier va dans `Local/<YYYY-MM-DD> - <nom>/`, la video est rattachee a la chaine `Fichiers locaux` (`url` `local://files`, cloches desactivees) avec `yt_video_id` = `local:<sha1 du contenu>` (un meme contenu n'est pas importe deux fois). Repond en JSON (`status`, `message`, `video_id`, `return_to`) avec `X-Requested-With: fetch`, sinon redirige vers la fiche. Pas de transcript ni de metadonnees YouTube.
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
- `GET /videos/download-jobs/{id}` : statut job telechargement.
- `POST /videos/import-metadata` : import metadata video.
- `GET /jobs/{id}` : statut job generique.

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

- `GET /api/channels`
- `POST /api/channels` : lance aussi le rattrapage du profil en arriere-plan ;
  `409` si la chaine est deja dans la bibliotheque, reconnue par son identifiant
  YouTube quelle que soit l'URL donnee (meme regle que le formulaire de `/channels`)
- `POST /api/channels/{id}/rating?rating=0..5`
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
- `POST /api/videos/{id}/rating?rating=0..5`
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
  [11 Interface HTML](11-interface-html.md).
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/errors` : les 100 lignes les plus recentes de `download_jobs`
  (tous statuts), la plus recente d'abord.

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
  sinon. Equivalent de `POST /videos/{id}/list-state`.
- `PUT /api/videos/{id}/categories` `{categories: [...]}` : remplace les
  categories de la fiche (normalisees, ajoutees a la liste des categories).
- `PUT /api/videos/{id}/comment` `{comment}` : une chaine vide efface le
  commentaire.
- `POST /api/videos/{id}/activity` `{media_type, position_seconds,
  duration_seconds, watched_seconds}` : rapport de lecture d'un lecteur, peut
  passer la fiche en Vu ; `media_type` vaut `video` ou `audio` (`400`
  sinon). Equivalent de `POST /videos/{id}/activity`.
- `POST /api/videos/{id}/media/{audio|video}/download` `{video_quality}`
  (facultatif, `1080` par defaut) : `202 {job_id, status, message,
  status_url}`, le telechargement tourne en arriere-plan ; `400` pour un
  autre format ou une qualite inconnue.
- `DELETE /api/videos/{id}/media/{audio|video}` : `204` ; `400` si le
  format est refuse (meme regle que `POST /videos/{id}/media/{type}/delete`).
- `POST /api/videos/{id}/transcript/download` : nouvelle tentative de
  recuperation du transcript, `202` comme un telechargement.
- `POST /api/videos/{id}/sponsor-segments/fetch` : interroge SponsorBlock et
  remplace les segments `sponsorblock` de la fiche ; repond `{count,
  skip_enabled, segments}` (comme `GET /api/videos/{id}/sponsor-segments`),
  `502` si SponsorBlock ou l'enregistrement echoue.
- `GET /api/jobs/{id}` : etat d'un job lance par ces actions, a interroger
  jusqu'a `done` : `{id, status, message, video_id, done}`, plus `videos`
  (fiches deja importees) pour une exploration de chaine ; `404 Job
  introuvable`. Meme contenu que `GET /jobs/{id}`.

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

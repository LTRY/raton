---
title: "12 API et routes"
---
# 12 API et routes

## Pages et formulaires du front (`front/routes/`)

Toutes les routes de cette section sont celles du front (`front/`) : une
page lit ses donnees par `/api`, une route de formulaire (repli sans
JavaScript) appelle `/api` puis redirige (303). Le front relaie aussi vers le
back tous les appels `/api/*` du navigateur (`front/proxy.py`), si bien que
les adresses `/api` ci-dessous valent pour les deux ports. Une erreur de
l'API sur une page (fiche, chaine ou playlist inconnue) est repondue avec le
meme statut et le meme `detail`.

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

- `GET /` : accueil (barre de chat de la bibliotheque seule) ;
  `?discussion={id}` ouvre cette discussion du chat au lieu de Raton.
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
- `POST /videos/{id}/categories` : modifier les categories de la video, puis
  rediriger vers `next`. L'editeur de la page detail enregistre a chaque
  coche par `PUT /api/videos/{id}/categories`.
- `POST /videos/{id}/comment` : commentaire libre (texte, champ `comment`).
- `POST /videos/{id}/rating` : note de 0 à 5, redirige (303) vers `next`.
  Repli sans JavaScript : les étoiles appellent `PUT /api/videos/{id}/rating`.
  Les boutons **Vu** / **Écartée** appellent `PUT /api/videos/{id}/list-state`
  et la lecture est rapportee par `POST /api/videos/{id}/activity` : ni l'un ni
  l'autre n'a de route HTML.
- `GET /videos/{id}` : detail video.
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
- `POST /videos/{id}/transcript/generate` : repli sans JavaScript de
  `POST /api/videos/{id}/notes/generate` (notes structurees, resume court et
  questions suggerees en un seul appel LLM, a partir de `transcript.txt` —
  voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) ;
  redirige vers l'onglet transcript de la fiche. La discussion d'une fiche et
  le chat de la bibliotheque n'ont pas de route HTML : leurs widgets appellent
  `/api/videos/{id}/chat`, `/api/chat` et `/api/llm-jobs/{id}`.
- `POST /videos/{id}/sponsors/fetch` : rechercher les segments sponsorises via l'API publique SponsorBlock — **seule source** — pour les categories activees (`/settings`) ; remplace uniquement les lignes `source="sponsorblock"` de la video. Redirige vers `/videos/{id}?message=...#segments-sponsors` (l'ancre ouvre l'onglet Segments ; `level=error` en cas d'echec) — voir [08 Medias et lecteurs](08-medias-et-lecteurs.md). Meme recherche : `POST /api/videos/{id}/sponsor-segments/fetch`.
- `GET /videos/import` : renvoie (303) vers `/videos?import=video`, qui ouvre la feuille d'import de la Bibliotheque ; garde `message`/`level`. `GET /import/categories` : fragment `turbo-frame` des pastilles de categories de la feuille.
- `POST /videos/download` : telechargement manuel ; `subtitle_language` vide (defaut, le formulaire n'en envoie plus) laisse `choose_subtitle_track` choisir la piste originale.
- `POST /videos/upload` : import d'un fichier video ou audio depose sur la page d'import (champ multipart `file`). Extensions acceptees : celles de `VIDEO_EXTENSIONS`/`AUDIO_EXTENSIONS` (`back/services/youtube/downloads.py`), sinon 400. Le fichier va dans `Local/<YYYY-MM-DD> - <nom>/`, la video est rattachee a la chaine `Fichiers locaux` (`url` `local://files`, cloches desactivees) avec `yt_video_id` = `local:<sha1 du contenu>` (un meme contenu n'est pas importe deux fois). Redirige vers la fiche ; repli sans JavaScript de `POST /api/videos/upload`, qu'appelle la page d'import. Pas de transcript ni de metadonnees YouTube.
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

Utilisateurs (`front/routes/users.py`) — le front seul pose le cookie
`raton_user`, qui dit pour qui agit ce navigateur (voir « Utilisateur d'une
requete » plus bas) :

- `POST /users/switch` `user_id` : agir comme cet utilisateur (pose le
  cookie), puis redirige vers `/` avec « Bonjour <nom> ! » ; un utilisateur
  inconnu redirige vers `/` avec un message d'erreur.
- `POST /users` `name` : ajoute un utilisateur (`POST /api/users`) et agit
  aussitot comme lui ; un nom vide, trop long ou deja pris redirige vers `/`
  avec le message du back.
- `POST /users/{id}/rename` `name`, `POST /users/{id}/delete` : formulaires de
  la section Utilisateurs de `/settings`, redirigent vers `/settings` avec un
  message. Supprimer l'utilisateur courant efface le cookie (retour a
  l'utilisateur par defaut).

Parametres et divers :

- `GET /settings` : page parametres.
- `POST /settings` : mise a jour parametres.
- `GET /logs` : logs jobs, filtres `status` (`all`, `errors`, `warnings`, `running`), `q` (recherche) et `page` (voir [11 Interface HTML](11-interface-html.md), section Logs).

Le bouton "Lancer le scan maintenant" de `/settings` appelle `POST /api/scan`
et suit `GET /api/scan/events` (voir Scan plus bas).

## API interne `/api`

Conventions communes : une modification envoie un corps JSON (`PUT` pour
fixer une valeur) et repond l'etat modifiable de ce qu'elle a change ; les
categories d'une chaine, d'une fiche ou d'une playlist se lisent toujours
`categories`, une liste de libelles normalises (la colonne `category_labels`
ne sort pas de l'API).

Erreurs : toute erreur de `/api` repond `{"detail": "<message en francais>"}`
(`ErrorRead`, `back/api/errors.py`). Un refus metier porte le message du
service (`400`, `404`, `409`, `502`) ; une requete invalide repond `422` avec
un `detail` lisible (`Requête invalide : state : champ obligatoire.`) et
`errors`, la liste `{field, message}` des champs en cause (les routes du
front gardent la reponse `422` par defaut de FastAPI). Chaque route declare
dans le schema OpenAPI les codes d'erreur qu'elle peut repondre, et toutes
ses reponses sont typees ; le schema est servi par le back (`/docs`, port
8001), le front n'en a pas.

Les dates-heures sont en ISO 8601, les durees en secondes, les tailles en
octets, les couleurs en `#rrggbb` : la mise en forme (francais, `m:ss`,
« 1,2 Go ») est l'affaire de chaque client.
`tests/test_api_contract.py` verifie ces regles.

Utilisateur d'une requete : chaque requete agit pour un utilisateur
(`back/api/users.py:current_user_id`), celui que nomme l'en-tete
`X-Raton-User` (son `id` ; le front l'envoie pour ses propres appels) ou, a
defaut, le cookie `raton_user` (les appels du navigateur relayes par le
front). Sans l'un ni l'autre, ou pour un utilisateur supprime : l'utilisateur
par defaut, le plus ancien (le serveur MCP agit ainsi). Ce qui est propre a un
utilisateur (voir [05 Modele de donnees](05-modele-de-donnees.md),
« Utilisateurs ») est lu et ecrit pour lui : `rating`, `list_state`,
`comment`, `is_new` et `watched_at` d'une fiche, `rating` et cloches d'une
chaine, playlists, discussions, historique, positions de reprise, temps
d'ecran, vues enregistrees, phrases de Raton. Le reste (fiches, fichiers,
transcripts, notes, categories, reglages de la bibliotheque) est commun. Une
playlist ou une discussion d'un autre utilisateur repond `404`, comme si elle
n'existait pas.

- `GET /api/users` : `{users: [{id, name}], current_user_id}`, les
  utilisateurs du plus ancien au plus recent et celui de la requete.
- `POST /api/users` `{name}` : `201` avec `{id, name}` ; `400` pour un nom
  vide, de plus de 40 caracteres ou deja pris (sans tenir compte de la
  casse). Un nouvel utilisateur n'a rien a lui : ni Vu, ni etoiles, ni cloche,
  ni playlist.
- `PUT /api/users/{id}` `{name}` : renomme, memes refus ; `404` si inconnu.
- `DELETE /api/users/{id}` : `204` ; supprime ce qui lui est propre (ses
  etats, reglages, playlists, discussions), jamais une fiche ; `409
  Impossible de supprimer le dernier utilisateur.`

- `GET /api/channels?sort=…&rated=true|false&q=…&page=N` : une page de 50
  chaines, memes tris (`activity` par defaut, `rating`, `alpha`, `added` ; un
  tri inconnu donne `activity`), meme recherche et meme filtre Notees que
  `/channels` (`channel_page`). Contrairement a la page, toutes les chaines
  sont listees sauf `rated=true`. Repond `{items, sort, page, total_pages,
  total, channel_count}` (`total` : chaines filtrees et cherchees ;
  `channel_count` : chaines gardees par le filtre Notees, sans la recherche) ; chaque chaine `{id, url, name, yt_channel_id, rating,
  categories, auto_metadata_enabled, auto_shorts_enabled, created_at,
  avatar_url, banner_url, metadata_fetched_at, video_count, last_played_at}`
  (`rating` et cloches : ceux de l'utilisateur ; `last_played_at` : sa
  derniere lecture d'une des fiches de la chaine, `null` sinon). Le nombre de requetes ne depend pas du nombre de
  chaines affichees.
- `GET /api/channels/{id}` : la chaine plus son profil : `description`,
  `keywords` (liste), `avatar_url` et `banner_url` (`/api/channels/{id}/avatar`,
  `/api/channels/{id}/banner`, `null` sans image), `metadata_fetched_at`,
  `last_scanned_at`, `video_count`.
- `GET /api/channels/names` : toutes les chaines `{id, name}` par nom (le
  selecteur de chaine de `/videos`).
- `GET /api/youtube/channels?q=<nom>` : les chaines YouTube qui
  correspondent a un nom, `{yt_channel_id, name, handle, url,
  subscriber_count, description, thumbnail_url, existing}` (`existing` :
  `{id, name}` de la chaine si elle est deja dans la bibliotheque) ; `502
  Recherche YouTube impossible : …` si YouTube echoue.
- `POST /api/channels` `{url, rating, categories}` (`rating` facultatif, `1`,
  la note de l'utilisateur qui ajoute ;
  `categories` facultatives) : `url` doit etre une URL ou un `@handle` (`422`
  sinon : un nom se cherche avec `GET /api/youtube/channels`) ; lance aussi
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
  brutes (meme service `detail_view` ; la page `GET /videos/{id}` du front
  la lit) : les champs de
  `GET /api/videos`, plus `is_new`, `list_state` (choix enregistre, pas
  l'etat deduit de la lecture), `comment`, `duration_seconds`, `watched_at`
  (ces cinq-la et `rating` sont ceux de l'utilisateur), `files_purged` (la
  purge a retire les fichiers apres le premier Vu, de quiconque : la page le
  dit),
  `media_urls` (`video`, `audio`, `thumbnail`, `subtitles` : la route qui sert
  le fichier, `null` si la fiche n'a pas ce fichier), `metadata` (champs de
  `metadata.json` : `description`, `tags`, `chapters` `{title,
  start_seconds}`, `duration_seconds`, `view_count`, `like_count`,
  `comment_count`, `uploader` ; un nombre illisible vaut `null`),
  `documents` (`transcript`, `notes`, `short_summary`, `suggested_questions`,
  `chat_messages`), `sponsor_segments` (segments actifs), `skip_segments` et
  `sponsor_skip_enabled` (comme `GET /api/videos/{id}/sponsor-segments`),
  `resume_positions` (`{video|audio: {position_seconds, at_ms}}`),
  `playlists` (`{playlist_id, title, item_id}`, celles de l'utilisateur qui
  contiennent la fiche), `channel` (`{id, name}`),
  `badges` (ce que contient la fiche, dans l'ordre des badges : `new`,
  `audio`, `video`, `metadata`, `transcript`, `notes`, `imported`),
  `has_transcript` (un transcript est enregistre) et `transcript_lines` (le
  transcript ligne par ligne avec l'heure de debut de chacune,
  `{start_seconds, text}`, lu dans les sous-titres `.vtt` ; liste vide sans
  `.vtt` lisible). Lecture seule :
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
  duration_seconds, progress_percent, is_completed}` ou `null`, et ce que la
  carte affiche : `shown_state` (`normal`, `watched`, `hidden` : le choix
  enregistre, sinon deduit de la lecture), `auto_state` (l'etat deduit de la
  lecture seule — Vu a 90 % ou derniere lecture terminee —, ce que « clear » ramene), `replay_category` (fiche d'une
  categorie « sans barre de progression » : ni barre ni Vu automatique)),
  `saved_views` les vues enregistrees avec `active`, et pour la page d'une
  chaine `publication_interval_days` (jours medians entre deux publications,
  `null` sous deux jours), `explore_next_page` (la page du catalogue YouTube
  qu'« Explorer la suite » importe) et `explore_page_size`. Une fiche
  ancienne sans chaine recoit la sienne (et ses labels) en etant listee.
  `404` si `channel_id` ne designe aucune chaine.
- `GET /api/library/views` : les vues enregistrees (memes champs que
  `saved_views`, `active` toujours faux) : le menu de la Bibliotheque des
  pages autres que `/videos`.
- `GET /api/library/cards?ids=1,2,3` : les cartes de ces fiches (memes
  champs que `items`), dans cet ordre, les inconnues ignorees (au plus 200) :
  la page d'une chaine y ajoute les fiches qu'une exploration importe. Le nombre de requetes SQL ne depend pas de la
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
- `GET /api/stats` : `{channels, rated_channels, videos, regular_videos,
  shorts, downloaded_media, transcripts, used_bytes, quota_bytes,
  storage_percent}`, les compteurs de la page `/settings`.
- `GET /api/stats/charts` : memes donnees que la page `/stats` (stockage et
  fiches par chaine, par format, par mois) — voir
  [11 Interface HTML](11-interface-html.md). Chaque type de stockage et chaque
  format porte sa part (`percent`) ; plus `purged` (fiches purgees par mois),
  `spend` (depense LLM par mois), `quota_bytes` et `quota_percent`. `monthly`
  garde toute la fenetre de 12 mois : la page, elle, en retire les premiers
  mois vides et en tire son dessin (`front/charts.py:monthly_view`).
- `GET /api/rag` : ce que montre `/rag` (`rag_dashboard_data`) : `buckets`
  (etape de chaque fiche), `pipeline` (etat du balayage, lot en cours,
  prochain passage), `next_batch`, `in_flight_videos`, `jobs`, `history`,
  `chunks`, `channels`, `failures`, `parameters`. Dates en ISO 8601,
  `pipeline.next_sweep_in_seconds` en secondes ; les libelles et
  `family` (couleur) des etapes sont ceux de la page.
- `GET /api/auto-notes` : le dernier lot de notes automatiques,
  `{last_run_at, last_run_summary}`.
- `GET /api/settings` : les reglages de `/settings` (`media_root`,
  `global_quota_bytes`, `video_category_labels`,
  `video_category_label_styles`, `video_library_views`,
  `no_progress_category_labels`, `auto_notes_enabled`,
  `auto_notes_excluded_category_labels`, `sponsor_segment_categories`,
  `sponsor_skip_enabled`, `screen_time_limits` en minutes par type et par
  periode), plus `sponsor_segment_category_choices` (`{value, label}` de
  chaque categorie SponsorBlock) et `llm_provider_label` (qui repond aux
  demandes au LLM, fixe par l'environnement).
- `PUT /api/settings` : memes champs (sauf les deux derniers), chacun
  facultatif ; `screen_time_today_minutes` `{video, short, podcast, music}`
  fixe les limites du jour. Les listes sont normalisees ; une liste vide de
  categories ou de vues enregistrees ramene les valeurs par defaut.
- `GET /api/categories` : les categories et leurs couleurs `{label, color}`,
  dans leur ordre, sans lire les autres reglages : ce qu'il faut a une page
  pour colorer ses labels.
- `GET /api/jobs?status=…` : les 100 derniers jobs du journal
  (`download_jobs`, comme `/logs`), le plus recent d'abord : `{id, status,
  message, channel_id, video_id, created_at, done}` ; `status` (repetable)
  ne garde que ces statuts.
- `GET /api/logs?filter=all|errors|warnings|running&q=…&page=N` : le journal
  page par page (50), le plus recent d'abord, ce que montre `/logs` : `{rows,
  page, total_pages, total, filter_counts, last_24h_counts}`, chaque ligne
  comme `GET /api/jobs` plus `video` `{id, title}` et `channel` `{id, name}`.
  `q` cherche dans le message, le titre de la fiche et le nom de la chaine ;
  les compteurs (par filtre, et sur 24 h) ignorent `q`.

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

- `GET /api/playlists[?sort=title]` : toutes les playlists, la plus recente
  d'abord (ou par titre), plus `item_count`, `cover_video_id` (premiere
  fiche, `null` si vide) et `cover_has_thumbnail`. Nombre de
  requetes constant.
- `POST /api/playlists` `{title}` : creation manuelle, `201` ; `400 Le titre
  est obligatoire.` pour un titre vide.
- `GET /api/playlists/{id}` : la playlist plus `stats` `{count,
  total_duration_seconds, seen_count, missing_audio, missing_video}` et
  `items` dans l'ordre (`{item_id, position, added_at, video_id, title,
  channel_name, duration_seconds, has_audio, has_video, has_thumbnail, url,
  seen}`).
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
- `GET /api/chat` : le chat bibliotheque sans discussion ouverte
  (`conversation_id` et `title` `null`, `messages` vide), la liste
  `conversations` (`[{id, title, updated_at}]`, les 50 plus recentes) et
  `indexed_video_count`/`total_video_count`.
  `GET /api/chat/conversations/{id}` : meme reponse avec cette discussion
  ouverte (`messages`, chaque reponse avec les `channels` et `citations`
  qu'elle cite) ; `DELETE /api/chat/conversations/{id}` la supprime (`204`) ;
  `404 Discussion introuvable.`. `POST /api/chat` `{question,
  conversation_id}` : pose une question a la suite de cette discussion, ou en
  ouvre une nouvelle sans `conversation_id` (`202`, la reponse porte le
  `conversation_id`) ; `400 La question est vide.`, `404 Discussion
  introuvable.`.
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

### Tableau de bord

- `GET /api/nouveautes?page=N` : `{stacks, page, total_pages}`, une pile par
  chaine suivie, 10 chaines par page (`page` compte des chaines) ; chaque pile
  `{channel: {id, name}, items}` avec les 10 fiches les plus recentes des
  types que suivent ses cloches, en cartes de `GET /api/library`.
- `GET /api/historique?page=N` : une ligne par media et par jour local, la plus
  recente d'abord, 50 par page : `{rows, page, total_pages, day_seconds}` ;
  chaque ligne `{job_id, created_at, day, video, channel, playback,
  watched_seconds, rewatch, shown_state, auto_state, replay_category}`, `day`
  etant le jour local sous lequel elle se range, `job_id`/`created_at`/`playback`
  le dernier rapport de lecture du media ce jour-la, `watched_seconds` la somme
  de tous ses rapports du jour, `rewatch` vrai quand la fiche etait deja Vu
  avant ce jour, `video` `{id, title, rating, file_size_bytes,
  list_state, categories, badges}` (`null` si la fiche a ete supprimee) et
  `playback` `{action, media_label, title, position_seconds,
  duration_seconds, watched_seconds, progress_percent, is_completed}`.
  `day_seconds` : le temps de lecture de chaque jour de la page, toutes les
  lectures du jour comptees.
- `GET /api/screen-time` : `{periods}`, le temps de lecture par periode
  (`today`, `week`, `month`) et par type (`video`, `short`, `podcast`,
  `music`) : `{seconds, count, limit_minutes}`.
- `POST /api/raton/visit` : une visite de l'accueil, enregistree ; repond la
  replique a afficher `{id, line, art, cta_label, cta_href, closing}` (`art` :
  un fichier de `front/static/img/raton/`). Voir [18 Raton](18-raton-scenarios.md).
- `GET /api/raton/variations` : toutes les repliques de chaque scenario,
  sans condition ni comptage de visite.

### Medias

Les fichiers d'une fiche ou d'une chaine, lus sur le volume media du back
(`back/api/media.py`) ; voir « Reponses media » plus bas et
[15 Securite](15-securite.md).

- `GET /api/videos/{id}/thumbnail[?w=320|640]` : la vignette (copie reduite si
  elle existe), `Cache-Control: public, max-age=86400`.
- `GET /api/videos/{id}/subtitles` : le `.vtt`.
- `GET|HEAD /api/videos/{id}/audio` et `/api/videos/{id}/video` : le flux,
  avec `Range` (`206`, `416`).
- `GET /api/channels/{id}/avatar` et `/api/channels/{id}/banner` : l'image de
  profil (`Cache-Control: public, max-age=86400`) ; `404` si la chaine ou
  l'image n'existe pas, ou si le chemin stocke sort de `_channels/`.

### Scan

- `GET /api/scan` : `{running, last_event_id, last_at, last_status,
  last_imported}` : un scan tourne-t-il, ou reprendre le flux d'evenements,
  et le resultat du dernier scan.
- `POST /api/scan` : lance le scan des chaines suivies (meme traitement que le
  cron de 3h, via `scheduled_scan`) en tache de fond ; `202 {after}` (`after` :
  dernier identifiant d'evenement emis avant ce scan), `409 Un scan est déjà
  en cours.` si un scan tourne.
- `GET /api/scan/events?after=N` : evenements du scan emis apres `N`,
  `{events: [{id, level, message, final}], last_id, running}`. Flux en memoire
  du processus (`back/services/ingest/scan_events.py`), pas une table.

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
- `POST /api/videos/share-import` `{url}` : importe tout de suite un lien
  YouTube partage depuis le telephone (metadonnees et transcript, sans
  media) et attend la fin : `{job_id, status, message, video_id}` ; `400` si
  le lien n'est pas YouTube, `502` si l'import echoue (le message dit
  pourquoi). La route `POST /videos/share-import` du front l'appelle pour le
  raccourci iOS.

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

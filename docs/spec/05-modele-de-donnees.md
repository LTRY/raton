---
title: "05 Modele de donnees"
---
# 05 Modele de donnees

## Tables principales

### `channels`

Champs :

- `id` : entier, cle primaire ;
- `url` : URL YouTube unique ;
- `name` : nom affiche ;
- `yt_channel_id` : identifiant YouTube si disponible ;
- `auto_metadata_enabled` : cloche de suivi quotidien des videos, desactivee
  par defaut ; active l'import metadata quotidien planifie de l'onglet videos
  et le marquage `is_new` des nouvelles fiches trouvees par ce scan planifie
  (la synchronisation immediate declenchee par l'activation de la cloche ne
  marque pas `is_new`, voir plus bas) ;
- `auto_shorts_enabled` : cloche de suivi quotidien des shorts, desactivee par
  defaut, independante de la precedente ; meme comportement, applique a
  l'onglet shorts de la chaine ;
- `rating` : note utilisateur de 0 à 5 (defaut 1) ;
- `category_labels` : categories associees a la chaine, appliquees aux
  nouvelles videos importees qui n'ont pas encore de categorie ;
- `description` : texte de presentation de la chaine (nullable) ;
- `keywords` : liste JSON de mots-cles declares par la chaine (nullable), lue via
  la propriete `Channel.keyword_list` (liste vide si absente ou invalide) ;
- `avatar_path`, `banner_path` : chemins relatifs a la racine des medias
  (nullable) ;
- `metadata_fetched_at` : date du dernier import du profil de la chaine ;
- `last_scanned_at` : date de fin du dernier passage du scan planifie sur la
  chaine (nullable). Il ordonne le scan : jamais scannees d'abord, puis la plus
  anciennement scannee ; une chaine interrompue par un 429 n'est pas marquee ;
  `NULL` signifie profil jamais recupere, ce que cible le job de rattrapage
  (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md)) ; reste
  renseigne meme si une image n'a pas pu etre enregistree (indexee).
  Ces cinq colonnes ont ete ajoutees par une ancienne migration ;
  les images sont rangees sous `_channels/<yt_channel_id>/` (voir
  [06 Stockage fichiers](06-stockage-fichiers.md)) ;
- `created_at`, `updated_at`.

Relations :

- `Channel.videos` cascade delete-orphan.

### `videos`

Champs :

- `id` : entier, cle primaire ;
- `channel_id` : nullable, FK vers `channels.id` ;
- `yt_video_id` : identifiant YouTube, unique ;
- `title` ;
- `url` : URL source YouTube, conservee pour telechargements ulterieurs ;
- `media_type` : valeur derivee historique (`video`, `audio`, `metadata`) ;
- `download_source` : `auto` ou `manual` ;
- `imported_via_form` : `true` si la fiche vient d'un import manuel via le
  formulaire (utilise par le filtre "Import manuel" de la bibliotheque) ;
- `is_new` : label technique `Nouveau`, pose uniquement par le scan planifie
  du suivi quotidien (pas par la synchronisation immediate declenchee a
  l'activation de la cloche, ni par un import manuel), retire des la visite
  de `/videos/{id}` ;
- `list_state` : etat de grisage force manuellement depuis les listes video,
  nullable. `null` = aucun forcage, la carte suit la detection automatique
  (derniere lecture terminee) ; `watched` = marquee vue a la main ; `unwatched`
  = forcee non-vue, ce qui annule la detection automatique ; `hidden` = ecartee,
  soit un grisage renforce plus le filtre "Masquer les ecartees" de `/videos`.
  Un `watched` pose a la main est respecte meme sur une categorie replay, alors
  que la detection automatique y reste neutralisee ;
- `category_labels` : categories associees a la video ;
- `comment` : commentaire libre de la personne, optionnel ;
- `published_at` ;
- `downloaded_at` ;
- `folder_path` : dossier final du contenu ;
- `video_path` : fichier video local, nullable ;
- `audio_path` : fichier audio local, nullable ;
- `thumbnail_path` : vignette locale, nullable ;
- `metadata_path` : `metadata.json`, nullable ;
- `subtitle_path` : sous-titres bruts telecharges, nullable ;
- `transcript_path` : `transcript.txt`, nullable ;
- `transcript_status` : `missing`, `downloaded`, `failed` ;
- `rating` : note utilisateur de 0 à 5 ;
- `file_size_bytes` : taille totale du dossier media ;
- `watched_at` : date (avec fuseau, indexee, nullable) a laquelle la lecture a atteint 90 % de la duree pour la premiere fois ; posee par `POST /videos/{id}/activity` (voir [08 Medias et lecteurs](08-medias-et-lecteurs.md)), remise a `NULL` quand un telechargement ajoute un format, et point de depart de la retention de [06 Stockage fichiers](06-stockage-fichiers.md). `NULL` = jamais vue a 90 % (donc jamais purgee) ;
- `view_count` : nombre de vues recopie de `metadata.json` (entier, indexe, nullable), pose a l'import (telechargement manuel, import de metadonnees) et par le rattrapage de demarrage (`app/services/youtube/view_counts.py`, une ancienne migration). Sert au tri « les plus vues » de `/videos`, execute en SQL ; `NULL` compte comme 0. Un `metadata.json` lisible sans compteur donne 0, un fichier illisible laisse `NULL` (reessaye au demarrage suivant) ;
- `duration_seconds` : duree recopiee de `metadata.json` (entier, nullable), posee au meme moment que `view_count` (une ancienne migration). Sert a la duree affichee sur les cartes : `metadata.json` est le dump complet de yt-dlp (~140 Ko) et n'est pas relu pour chaque carte d'une liste. Un fichier lisible sans duree donne 0 (non affichee), un fichier illisible laisse `NULL` ;
- `ai_analysis_json` : JSON serialise, ecrit par `POST /videos/{id}/transcript/generate` (avec les notes et le resume, en un seul appel LLM) — voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md), section "Génération : notes, résumé et analyse". Cles possibles, toutes absentes plutot que `null` quand la section correspondante n'a pas ete produite : `clickbait_score` (1-10), `clickbait_rationale`, `relevance_percent` (0-100), `relevance_rationale`, `suggested_titles` (liste), `suggested_categories` (liste), `generated_at` (horodatage ISO). Une nouvelle generation remplace tout le JSON ;
- `created_at`, `updated_at`.

Contraintes :

- `yt_video_id` est unique.
- Un seul enregistrement represente une video YouTube.
- `video_path` et `audio_path` peuvent coexister.
- `media_type` ne suffit pas a determiner tous les fichiers presents ; les
  chemins `video_path` et `audio_path` font autorite.

### `playlists`

Une playlist locale, cree de trois facons possibles (`source`) : import depuis
une URL de playlist YouTube, import depuis un CSV Google Takeout (un fichier
par playlist, voir [07 YouTube et telechargements](07-youtube-et-telechargements.md)),
ou creation manuelle vide que l'utilisateur remplit ensuite a la main. Pas de
re-synchronisation periodique (pas de "cloche" comme pour les chaines) :
l'import est un instantane, a relancer manuellement si besoin.

Champs :

- `id` ;
- `title` ;
- `source` : `manual`, `url` ou `csv` ;
- `source_url` : URL de la playlist d'origine, uniquement pour
  `source="url"` (YouTube) ;
- `yt_playlist_id` : identifiant YouTube (`PLxxxx`), uniquement pour
  `source="url"` — un CSV Takeout par playlist ne contient pas cet identifiant
  (seul le fichier `playlists.csv` global du Takeout l'a, non utilise par
  l'import CSV de Raton qui traite un fichier a la fois) ;
- `category_labels` : categories de la playlist, modifiables depuis le menu
  **Gérer** de la page detail. Elles se transmettent aux videos comme celles
  d'une chaine : une video qui n'a aucun label recoit ceux de la playlist
  quand on les enregistre et quand la video est ajoutee a la playlist (import
  URL/CSV compris) ; une video qui a deja des labels (les siens, ou ceux de sa
  chaine) les garde, donc la premiere source gagne. La copie est ecrite sur la
  video : retirer un label de la playlist ne le retire pas des videos. Une
  duplication de playlist reprend ses labels ;
- `free_listening` : booleen, faux par defaut. Vrai = « ecoute libre » : le
  lecteur de la playlist n'enregistre aucune activite de lecture et ne marque
  aucune video comme vue (musique, podcasts). Ne change pas `videos.watched_at`
  deja renseigne par ailleurs ;
- `created_at`, `updated_at`.

Relations :

- `Playlist.items` cascade delete-orphan (supprimer une playlist ne supprime
  que les liens `playlist_items`, jamais les `videos` qu'elle contenait).

### `playlist_items`

Table de liaison ordonnee entre `playlists` et `videos` (many-to-many avec
position).

Champs :

- `id` ;
- `playlist_id` : FK `playlists.id`, `ON DELETE CASCADE` ;
- `video_id` : FK `videos.id`, `ON DELETE CASCADE` ;
- `position` : entier, ordre d'affichage dans la playlist ;
- `added_at` : horodatage "ajoutee a la playlist", nullable — rempli
  uniquement pour un import CSV (colonne "Code temporel de creation de la
  video de la playlist" du Takeout) ; toujours `null` pour un ajout manuel ou
  un import par URL (yt-dlp n'expose aucun horodatage "ajoutee a la
  playlist") ;
- `created_at` : horodatage de creation de la ligne (distinct de `added_at`).

Contrainte d'unicite `(playlist_id, video_id)` : une video ne peut apparaitre
qu'une seule fois dans une meme playlist.

### `download_jobs`

Champs :

- `id` ;
- `channel_id` nullable ;
- `video_id` nullable ;
- `status` ;
- `message` ;
- `created_at`.

Statuts utilises :

- `queued`
- `running`
- `downloaded`
- `metadata`
- `failed`
- `warning`
- `skipped`
- `scheduled` : premiere ou direct liste par une chaine mais pas encore disponible ; repris au scan suivant (voir [07 YouTube et telechargements](07-youtube-et-telechargements.md))
- `cancelled` : exploration de chaine arretee par la personne (X de la bulle de Raton) ; ce qui etait deja importe reste (voir [11 Interface HTML](11-interface-html.md))
- `purged` : fichiers media supprimes par la purge des videos vues (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md))
- `played`, `prompt` : suivi d'activite du dashboard (lecture, question IA), listes aussi sur `/logs` en badge neutre

### `app_settings`

Cle-valeur texte.

Cles connues :

- `media_root`
- `global_quota_bytes`
- `video_category_labels`
- `video_library_views`
- `auto_notes_enabled`, `auto_notes_excluded_category_labels`,
  `auto_notes_last_run_at`, `auto_notes_last_run_summary`,
  `auto_notes_batch_id`, `auto_notes_batch_submitted_at` : notes automatiques,
  voir [13 Jobs, logs et planification](13-jobs-logs-planification.md)
- `screen_time_<kind>_today_limit_minutes` pour `kind` dans
  `video`/`short`/`podcast`/`music` — seule la limite journaliere est
  configurable ; les limites "semaine" et "mois" affichees au dashboard sont
  derivees automatiquement (x7 et x30) a partir de cette limite journaliere
- `raton_last_seen_at`, `raton_session_previous_visit_at` et
  `raton_visit_shown` : dernières visites et phrases déjà affichées dans la
  visite en cours (liste JSON), utilisées par les scenarios de l'accueil, voir
  [18 Raton](18-raton-scenarios.md). Les anciennes clés `raton_tone` et
  `raton_rotation_index` ne sont plus lues.
- `last_auto_scan_at`, `last_auto_scan_status`, `last_auto_scan_imported_count` :
  etat du dernier scan planifie (cloche), voir
  [13 Jobs, logs et planification](13-jobs-logs-planification.md)

### `llm_jobs`

Job asynchrone pour toute completion LLM (generation, chat ou notes automatiques),
quel que soit le fournisseur — une ligne est toujours creee, jamais d'appel
synchrone dans le handler de la requete. Le job est traite dans le process
web lui-meme, via une tache `fastapi.BackgroundTasks`
(`app/services/background_jobs.py:run_llm_job`) planifiee juste apres la reponse `queued`.

Champs :

- `id` ;
- `kind` : `generate` (notes + resume + analyse en un
  seul appel), `auto_notes` (notes + resume court d'une video, en lot
  nocturne : voir [13 Jobs, logs et planification](13-jobs-logs-planification.md),
  jamais interroge par le navigateur, son prompt n'est pas stocke), `chat` ou
  `library_chat`. La valeur historique
  `detect_sponsors` (detection IA des segments sponsorises) n'est **plus
  produite** depuis le retrait de cette detection, mais les lignes deja en
  base sont conservees : une ancienne migration ne
  touche pas `llm_jobs`. Le libelle correspondant reste donc volontairement
  dans `app/services/llm/usage.py` pour que ces jobs passes continuent de
  s'afficher dans la section "Couts LLM" de `/settings`. Il en va de meme de
  `clean_transcript` (nettoyage LLM retire, voir
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) ;
- `provider` : `anthropic` ;
- `video_id` : FK `videos.id`, cascade delete, **nullable** — null uniquement
  pour `kind="library_chat"` (le chat cross-video n'est rattache a aucune
  video precise, voir `library_chat_messages` ci-dessous) ;
- `prompt` : prompt complet envoye au fournisseur ;
- `question` : question brute (pour `kind="chat"`/`"library_chat"`), reutilisee
  pour reconstituer l'historique une fois la reponse obtenue ;
- `status` : `queued`, `running`, `done`, `failed`, `applied` (resultat deja
  ecrit sur disque, evite une double application si le job est repoll) ;
- `result` : reponse texte du fournisseur ; pendant qu'un job `generate` est
  `running`, texte recu jusque-la (voir `09-transcript-et-discussion-llm.md`) ;
- `sources` : JSON `{"channel_ids": [...], "video_ids": [...]}`, uniquement
  pour `kind="library_chat"` — les chaines et videos citees par la reponse
  (voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)),
  recopiees dans `library_chat_messages` quand le job est applique ; `null`
  pour les autres types de job ;
- `error` : message d'erreur si `failed` ;
- `model`, `input_tokens`, `output_tokens`, `cost_usd` : usage reel rapporte
  par le fournisseur (pas une estimation par nombre de caracteres), rempli
  pour les completions qui ont reussi et pour un job `failed` dont la reponse
  a ete recue mais inutilisable (tronquee/vide, tokens factures)
  (`app/services/background_jobs.py:run_llm_job`) ; `cost_usd` reste `null`
  sauf pour `anthropic` sur un modele dont le tarif est connu
  (`app/services/llm/usage.py:ANTHROPIC_MODEL_PRICING`). Voir
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md) pour
  le detail du calcul. Agrege par type de job et par modele dans `/settings`
  (section "Couts LLM", `app/services/llm/usage.py:llm_usage_summary`).
- `created_at`, `completed_at`.

### `video_note_chunks`

Un chunk embedde par section de notes structurees, socle du chat cross-video
(RAG). Peuple/remplace entierement par
`app/services/rag/indexing.py:index_video_notes` des qu'un job `generate` est
applique (notes/resume/analyse en un seul appel LLM, voir
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)). Les
notes venant du transcript, une video n'est
recherchable depuis le chat cross-video que si elle a au moins une ligne ici.

Champs :

- `id` ;
- `video_id` : FK `videos.id`, cascade delete ;
- `section` : nom de la section Markdown d'origine (`Faits`, `Dates`, `Lieux`,
  `Acteurs`, `Concepts`, `Relations causales`, ou `Notes` en repli si le
  modele n'a pas suivi le format de sections) ;
- `content` : texte de la section (une puce par ligne). Ce n'est pas le texte
  embeddé : celui-ci est `Titre — Chaîne — Section` suivi du contenu
  (`embeddings.contextualized_text`) ;
- `embedding` : `vector(1024)` (extension `pgvector`), genere par l'API Voyage
  AI (`app/services/rag/embeddings.py`, modele `EMBEDDING_MODEL`, `voyage-3.5` par
  defaut, `VOYAGE_API_KEY` requise). Un seul modele et une seule dimension
  pour toute la table : en changer impose de tout re-embedder (migration qui
  vide la table, puis reindexation au demarrage, voir
  [09](09-transcript-et-discussion-llm.md)) ;
- `created_at`.

Pas d'index de similarite approximative (IVFFlat/HNSW) pour l'instant : a
l'echelle d'une bibliotheque personnelle, un tri par distance cosinus
(`embedding <=> :query`) sans index specialise est suffisant ; a
reconsiderer si la table grossit significativement.

### `library_chat_messages`

Le fil unique et continu du chat cross-video ("toute la bibliotheque"),
distinct du chat par-video (fichier `transcript.chat.json`, voir
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) : pas
de fichier naturel ou stocker un historique qui n'est rattache a aucune video
precise, d'ou une table. Un seul fil global, pas de notion de conversations
multiples ni de multi-utilisateur (coherent avec le reste de l'app, usage LAN
personnel).

Champs :

- `id` ;
- `role` : `user` ou `assistant` ;
- `content` : texte du message ;
- `sources` : liste d'ids video separes par des virgules, uniquement sur les
  messages `assistant` — les videos citees par la reponse, pour afficher les
  puces de citation ; `null` sur les messages `user` ;
- `channel_sources` : meme format et meme regle que `sources`, pour les
  chaines citees par la reponse ;
- `created_at`.

### `video_sponsor_segments`

Un segment sponsorisé/auto-promotion/etc. détecté pour une vidéo, produit par
l'API publique SponsorBlock — **seule source** depuis le retrait de la
détection IA — voir [08 Médias et lecteurs](08-medias-et-lecteurs.md).

Champs :

- `id` ;
- `video_id` : FK `videos.id`, `ON DELETE CASCADE` ;
- `category` : `sponsor`, `selfpromo`, `interaction`, `intro` ou `outro` ;
- `start_seconds`, `end_seconds` : bornes du segment en secondes (flottant) ;
- `source` : `sponsorblock` — seule valeur écrite aujourd'hui ;
- `created_at`.

La colonne `source` est **volontairement conservée** malgré la source unique :
elle ne coûte rien, `replace_video_sponsor_segments` s'appuie dessus pour ne
toucher que les lignes de sa propre source, et elle laisse la porte ouverte à
une source manuelle ultérieure sans migration. Ne pas la supprimer.

Règle `(category, source)` : pas de contrainte d'unicité dans la DB ; c'est le
remplacement applicatif qui garantit la cohérence
(`app/services/youtube/sponsor_segments.py:replace_video_sponsor_segments`) —
relancer la recherche SponsorBlock pour une vidéo supprime d'abord toutes les
lignes existantes de **cette seule source** puis réinsère le résultat courant.

Avant l'envoi aux lecteurs (page détail et
`GET /api/videos/{id}/sponsor-segments`, voir
[12 API et routes](12-api-et-routes.md)), les lignes filtrées par catégories
activées passent par
`app/services/youtube/sponsor_segments.py:normalize_skip_segments` : tri par
`start_seconds`, fusion des segments qui se chevauchent ou se touchent
(SponsorBlock renvoie régulièrement des doublons issus de plusieurs
contributeurs), puis rejet des segments dont la durée après fusion est
inférieure à `MINIMUM_SKIP_SECONDS` (1,0 s). La sortie est une liste de
`{"start", "end"}` sans catégorie : le moteur de saut ne compare que des
bornes. Cette normalisation n'écrit rien dans la DB, l'affichage de l'onglet
Segments continue de lister les lignes brutes.

## Migrations

Les migrations Alembic sont la source de verite pour l'evolution de schema.

Le depot demarre sur une seule migration, `0001_initial`, qui regroupe tout
l'historique du schema d'origine : elle active d'abord l'extension Postgres
`pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`, socle des chunks de notes),
puis cree toutes les tables. Son `downgrade()` defait tout, extension et type
`transcript_status` compris. Les migrations suivantes se nomment
`NNNN_short_slug`.

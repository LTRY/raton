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

Les cloches et la note en etoiles d'une chaine sont propres a chaque
utilisateur : elles sont dans `user_channels` (voir « Utilisateurs »).

Relations :

- `Channel.videos` cascade delete-orphan ;
- `Channel.user_states` (`user_channels`) cascade delete-orphan.

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
- `category_labels` : categories associees a la video (partagees) ;
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
- `file_size_bytes` : taille totale du dossier media ;
- `watched_at` : date (avec fuseau, indexee, nullable) a laquelle la lecture d'**un utilisateur quelconque** a atteint 90 % de la duree pour la premiere fois ; posee par `POST /api/videos/{id}/activity` (voir [08 Medias et lecteurs](08-medias-et-lecteurs.md)), remise a `NULL` quand un telechargement ajoute un format, et point de depart de la retention de [06 Stockage fichiers](06-stockage-fichiers.md). `NULL` = jamais vue a 90 % (donc jamais purgee). Le Vu de chaque utilisateur est `user_videos.watched_at` ;
- `view_count` : nombre de vues recopie de `metadata.json` (entier, indexe, nullable), pose a l'import (telechargement manuel, import de metadonnees) et par le rattrapage de demarrage (`back/services/youtube/view_counts.py`, une ancienne migration). Sert au tri « les plus vues » de `/videos`, execute en SQL ; `NULL` compte comme 0. Un `metadata.json` lisible sans compteur donne 0, un fichier illisible laisse `NULL` (reessaye au demarrage suivant) ;
- `duration_seconds` : duree recopiee de `metadata.json` (entier, nullable), posee au meme moment que `view_count` (une ancienne migration). Sert a la duree affichee sur les cartes : `metadata.json` est le dump complet de yt-dlp (~140 Ko) et n'est pas relu pour chaque carte d'une liste. Un fichier lisible sans duree donne 0 (non affichee), un fichier illisible laisse `NULL` ;
- `created_at`, `updated_at`.

La note en etoiles, l'etat Vu/Indesiree, le commentaire et le label Nouveau
d'une fiche sont propres a chaque utilisateur : ils sont dans `user_videos`
(voir « Utilisateurs »). `Video.user_states` les regroupe, cascade
delete-orphan.

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
- `user_id` : FK `users.id`, `ON DELETE CASCADE`, non nul, indexe — l'utilisateur
  a qui la playlist appartient : lui seul la voit et la modifie (une playlist
  d'un autre repond `404` comme une playlist supprimee) ; une duplication
  appartient au meme utilisateur ;
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
  aucune video comme vue (musique, podcasts). Ne change pas un `watched_at`
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
- `user_id` : FK `users.id`, `ON DELETE SET NULL`, nullable, indexe — a qui
  est une ligne d'activite `played` ou `prompt` (historique, positions, temps
  d'ecran, tri « activite » des chaines de cet utilisateur) ; `NULL` sur les
  autres lignes, qui sont celles de la bibliotheque ;
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

Cle-valeur texte : les reglages de la bibliotheque, communs a tous les
utilisateurs. Ceux d'un utilisateur sont dans `user_settings`.

Cles connues :

- `media_root`
- `global_quota_bytes`
- `video_category_labels`
- `auto_notes_enabled`, `auto_notes_excluded_category_labels`,
  `auto_notes_last_run_at`, `auto_notes_last_run_summary`,
  `auto_notes_batch_id`, `auto_notes_batch_submitted_at` : notes automatiques,
  voir [13 Jobs, logs et planification](13-jobs-logs-planification.md)
- `last_auto_scan_at`, `last_auto_scan_status`, `last_auto_scan_imported_count` :
  etat du dernier scan planifie (cloche), voir
  [13 Jobs, logs et planification](13-jobs-logs-planification.md)

### `llm_jobs`

Job asynchrone pour toute completion LLM (generation, chat ou notes automatiques),
quel que soit le fournisseur — une ligne est toujours creee, jamais d'appel
synchrone dans le handler de la requete. Le job est traite dans le process
web lui-meme, via une tache `fastapi.BackgroundTasks`
(`back/services/jobs/llm_jobs.py:run_llm_job`) planifiee juste apres la reponse `queued`.

Champs :

- `id` ;
- `kind` : `generate` (notes + resume en un
  seul appel), `auto_notes` (notes + resume court d'une video, en lot
  nocturne : voir [13 Jobs, logs et planification](13-jobs-logs-planification.md),
  jamais interroge par le navigateur, son prompt n'est pas stocke), `chat` ou
  `library_chat`. La valeur historique
  `detect_sponsors` (detection IA des segments sponsorises) n'est **plus
  produite** depuis le retrait de cette detection, mais les lignes deja en
  base sont conservees : une ancienne migration ne
  touche pas `llm_jobs`. Le libelle correspondant reste donc volontairement
  dans `back/services/llm/usage.py` pour que ces jobs passes continuent de
  s'afficher dans la section "Couts LLM" de `/settings`. Il en va de meme de
  `clean_transcript` (nettoyage LLM retire, voir
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) ;
- `provider` : `anthropic` ;
- `user_id` : FK `users.id`, `ON DELETE SET NULL`, nullable — qui a pose la
  question d'un job `chat` ou `library_chat` : la reponse va dans sa
  discussion ; `null` pour les autres types, et pour les jobs anterieurs aux
  utilisateurs (la reponse va alors a l'utilisateur par defaut, ou a celui de
  la discussion) ;
- `video_id` : FK `videos.id`, cascade delete, **nullable** — null uniquement
  pour `kind="library_chat"` (le chat cross-video n'est rattache a aucune
  video precise, voir `library_chat_messages` ci-dessous) ;
- `conversation_id` : FK `library_chat_conversations.id`, `ON DELETE SET
  NULL`, nullable — la discussion d'un job `library_chat`, ou sa reponse est
  ajoutee ; `null` pour les autres types, et une fois la discussion supprimee
  (la reponse n'est alors ecrite nulle part : le poll repond `failed`) ;
- `prompt` : le `Prompt` envoye au fournisseur, en JSON `{"system": ..., "messages": [...]}` (`back/services/llm/prompts.py:Prompt`) ; un job cree avant ce format porte une simple chaine, lue comme un message `user` sans `system` ;
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
  (`back/services/jobs/llm_jobs.py:run_llm_job`) ; `cost_usd` reste `null`
  sauf pour `anthropic` sur un modele dont le tarif est connu
  (`back/services/llm/usage.py:ANTHROPIC_MODEL_PRICING`). Voir
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md) pour
  le detail du calcul. Agrege par type de job et par modele dans `/settings`
  (section "Couts LLM", `back/services/llm/usage.py:llm_usage_summary`).
- `created_at`, `completed_at`.

### `video_note_chunks`

Un chunk embedde par section de notes structurees, socle du chat cross-video
(RAG). Peuple/remplace entierement par
`back/services/rag/indexing.py:index_video_notes` des qu'un job `generate` est
applique (notes/resume en un seul appel LLM, voir
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
  AI (`back/services/rag/embeddings.py`, modele `EMBEDDING_MODEL`, `voyage-3.5` par
  defaut, `VOYAGE_API_KEY` requise). Un seul modele et une seule dimension
  pour toute la table : en changer impose de tout re-embedder (migration qui
  vide la table, puis reindexation au demarrage, voir
  [09](09-transcript-et-discussion-llm.md)) ;
- `created_at`.

Pas d'index de similarite approximative (IVFFlat/HNSW) pour l'instant : a
l'echelle d'une bibliotheque personnelle, un tri par distance cosinus
(`embedding <=> :query`) sans index specialise est suffisant ; a
reconsiderer si la table grossit significativement.

### `library_chat_conversations`

Les discussions du chat cross-video ("toute la bibliotheque"), distinctes du
chat par-video (fichier `transcript.chat.json`, voir
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) : pas
de fichier naturel ou stocker un historique qui n'est rattache a aucune video
precise, d'ou une table. Plusieurs discussions par utilisateur. La migration
`0003` a range les messages de l'ancien fil unique dans une premiere
discussion.

Champs :

- `id` ;
- `user_id` : FK `users.id`, `ON DELETE CASCADE`, non nul, indexe — l'utilisateur
  dont c'est la discussion : lui seul la liste, la rouvre, la continue ou la
  supprime ;
- `title` : la premiere question, sur une ligne, coupee a 80 caracteres
  (`back/services/library_chat/history.py:conversation_title`) ;
- `created_at` ;
- `updated_at` (indexe) : date de la derniere reponse ; la liste des
  discussions est triee dessus, la plus recente d'abord.

Supprimer une discussion supprime ses messages (cascade).

### `library_chat_messages`

Un message d'une discussion du chat cross-video.

Champs :

- `id` ;
- `conversation_id` : FK `library_chat_conversations.id`, `ON DELETE
  CASCADE`, non nul, indexe ;
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
(`back/services/youtube/sponsor_segments.py:replace_video_sponsor_segments`) —
relancer la recherche SponsorBlock pour une vidéo supprime d'abord toutes les
lignes existantes de **cette seule source** puis réinsère le résultat courant.

Avant l'envoi aux lecteurs (page détail et
`GET /api/videos/{id}/sponsor-segments`, voir
[12 API et routes](12-api-et-routes.md)), les lignes filtrées par catégories
activées passent par
`back/services/youtube/sponsor_segments.py:normalize_skip_segments` : tri par
`start_seconds`, fusion des segments qui se chevauchent ou se touchent
(SponsorBlock renvoie régulièrement des doublons issus de plusieurs
contributeurs), puis rejet des segments dont la durée après fusion est
inférieure à `MINIMUM_SKIP_SECONDS` (1,0 s). La sortie est une liste de
`{"start", "end"}` sans catégorie : le moteur de saut ne compare que des
bornes. Cette normalisation n'écrit rien dans la DB, l'affichage de l'onglet
Segments continue de lister les lignes brutes.

## Utilisateurs

Les fiches, leurs fichiers, transcripts et notes generees sont partages ; ce
que chaque utilisateur garde pour lui est dans les tables ci-dessous. Une
fiche ou une chaine qu'un utilisateur n'a jamais touchee n'a pas de ligne :
la lecture donne les valeurs par defaut, l'ecriture cree la ligne
(`back/services/common/user_state.py`). Vocabulaire :
[20 Glossaire](20-glossaire.md), « Utilisateur ».

### `users`

- `id` ;
- `name` : nom affiche, unique (insensible a la casse a la saisie), 40
  caracteres au plus ;
- `created_at`.

L'utilisateur **par defaut** est le plus ancien (plus petit `id`) : celui pour
qui agit une requete qui n'en nomme aucun (voir
[12 API et routes](12-api-et-routes.md)). Une DB sans utilisateur (demo,
tests, installation neuve) en recoit un, « Moi », a la premiere requete. Le
dernier utilisateur ne peut pas etre supprime ; supprimer un utilisateur
supprime tout ce qui lui est propre (ses lignes ci-dessous, ses playlists, ses
discussions) et laisse ses lignes d'activite sans utilisateur.

### `user_videos`

Etat d'une fiche pour un utilisateur ; cle primaire `(user_id, video_id)`, les
deux en `ON DELETE CASCADE`.

- `rating` : note en etoiles de 0 a 5 (defaut 0) ;
- `list_state` : etat de grisage force a la main depuis les listes, nullable.
  `null` = aucun forcage, la carte suit la detection automatique (derniere
  lecture terminee de cet utilisateur) ; `watched` = marquee vue a la main ;
  `unwatched` = forcee non-vue, ce qui annule la detection automatique ;
  `hidden` = indesiree : un grisage renforce, et la fiche est retiree des listes
  de cet utilisateur (Bibliotheque, page d'une chaine, Nouveautes, Historique)
  quand leur selecteur d'affichage est sur « Masquer les déjà vues et les indésirées »
  (`hide=watched_hidden`, voir [11 Interface HTML](11-interface-html.md)). Un `watched` pose a la main est respecte meme sur une
  categorie replay, alors que la detection automatique y reste neutralisee ;
- `comment` : commentaire libre, optionnel ;
- `is_new` : label `Nouveau`, pose uniquement par le scan planifie du suivi
  quotidien, pour chaque utilisateur dont la cloche de la section est active
  (pas par la synchronisation immediate declenchee a l'activation de la
  cloche, ni par un import manuel) ; retire des que cet utilisateur visite
  `/videos/{id}` ;
- `watched_at` : premiere fois que la lecture de cet utilisateur a atteint
  90 % ; jamais deplacee par une relecture.

### `user_channels`

Etat d'une chaine pour un utilisateur ; cle primaire `(user_id, channel_id)`.

- `rating` : note en etoiles de 0 a 5 (defaut 0 : la chaine reste hors du
  filtre « Notées ») ; l'utilisateur qui ajoute une chaine (formulaire, import
  des abonnements, chat bibliotheque) lui donne 1 etoile, sauf note choisie ;
- `auto_metadata_enabled` : cloche de suivi quotidien des videos ;
- `auto_shorts_enabled` : cloche de suivi quotidien des shorts, independante
  de la precedente.

Le scan planifie passe sur une chaine des qu'au moins un utilisateur y a une
cloche active (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md)).

### `user_settings`

Cle-valeur texte d'un utilisateur ; cle primaire `(user_id, key)`. Cles
connues :

- `video_library_views` : ses vues enregistrees ;
- `screen_time_<kind>_today_limit_minutes` pour `kind` dans
  `video`/`short`/`podcast`/`music` — seule la limite journaliere est
  configurable ; les limites "semaine" et "mois" affichees au dashboard sont
  derivees automatiquement (x7 et x30) a partir de cette limite journaliere ;
- `curfew_enabled` (`true`/`false`, `false` par defaut), `curfew_start`,
  `curfew_end` (`HH:MM`, `22:00` et `10:00` par defaut) : son couvre-feu, voir
  [02 Fonctionnalites](02-fonctionnalites.md) ;
- `raton_last_seen_at`, `raton_session_previous_visit_at` et
  `raton_visit_shown` : ses dernieres visites et les phrases deja affichees
  dans la visite en cours (liste JSON), utilisees par les scenarios de
  l'accueil, voir [18 Raton](18-raton-scenarios.md).

Une cle absente prend la valeur par defaut du code.

## Migrations

Les migrations Alembic sont la source de verite pour l'evolution de schema.

Le depot demarre sur une migration `0001_initial`, qui regroupe tout
l'historique du schema d'origine : elle active d'abord l'extension Postgres
`pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`, socle des chunks de notes),
puis cree toutes les tables. Son `downgrade()` defait tout, extension et type
`transcript_status` compris. `0002_drop_ai_analysis` retire la colonne
`videos.ai_analysis_json` (l'onglet Analyse IA n'existe plus). Les migrations
suivantes se nomment `NNNN_short_slug`.

`0004_users` cree les tables des utilisateurs et un premier utilisateur,
« Moi », a qui elle donne tout ce qui etait personnel : les notes en etoiles,
etats Vu/Indesiree, commentaires et labels Nouveau des fiches, les notes et
cloches des chaines, les reglages devenus personnels, les playlists, les
discussions et les lignes d'activite `played`/`prompt`. Elle retire ensuite
ces colonnes de `videos` et `channels`. Son `downgrade()` remet l'etat du plus
ancien utilisateur dans ces colonnes ; celui des autres est perdu.

---
title: "20 Glossaire"
tableOfContents:
  maxHeadingLevel: 2
---
# 20 Glossaire

Vocabulaire commun entre la personne qui utilise Raton et les LLM qui
modifient le depot. Chaque entree donne le terme employe a l'ecran et dans les
specs (francais), son nom dans le code (anglais), sa definition, et ce avec quoi
il ne faut **pas** le confondre.

Regles :

- Employer ces termes tels quels dans l'interface, les specs, les noms de
  variables, les messages de PR et les conversations. Pas de synonyme
  (« abonne », « follow », « watched » pour « vu », « cachee » ou « ecartee » pour « indesiree », « cache media » pour « stockage media », « lu » pour « vu », « en base » ou « la base » pour « dans la DB »...).
- Ne lister ici que ce qui est ambigu ou propre a Raton. Le detail
  (colonnes, regles) reste dans la spec qui possede le sujet : le lien est
  donne a chaque entree, cette page ne le recopie pas.
- Un terme qui change de sens dans le code ou dans l'interface se corrige ici
  dans le meme changement.

## Utilisateurs

### Utilisateur

Une personne qui utilise Raton, choisie depuis le bouton rond en bas du tiroir « Discussions » de l'accueil. Les fiches, leurs fichiers, transcripts, notes structurees et resumes sont **partages** ; ce qui est a soi est **propre** a chaque utilisateur : Vu/Indesiree, note en etoiles, commentaire, Nouveau, cloches, playlists, discussions, historique et position de lecture, vues enregistrees, temps d'ecran, visites de Raton. Pas de mot de passe : Raton reste sur un LAN de confiance.

- **Code** : `users`, `user_videos`, `user_channels`, `user_settings` ; cookie `raton_user`, en-tete `X-Raton-User`
- **A ne pas confondre avec** : Un compte (aucune authentification) ; l'utilisateur par defaut, le plus ancien, pour qui agit un client qui n'en nomme aucun (le serveur MCP).

Specs : [05 Modele de donnees](05-modele-de-donnees.md),
[11 Interface HTML](11-interface-html.md), [12 API et routes](12-api-et-routes.md).

## Contenu

### Fiche

Une video YouTube dans Raton : ses metadonnees, et/ou son fichier video, et/ou son fichier audio. Une seule par `yt_video_id`, partagee par tous les utilisateurs.

- **Code** : ligne de `videos`
- **A ne pas confondre avec** : Les fichiers seuls : une fiche peut n'avoir que des metadonnees.

### Dossier

Dossier final d'une fiche : `YouTube/<chaine>/<date> - <titre>/`, avec media, miniature, `metadata.json`, `transcript.txt`.

- **Code** : `folder_path`
- **A ne pas confondre avec** : Le dossier de staging, temporaire.

### Staging

Dossier temporaire ou un telechargement ecrit d'abord ; son contenu n'est deplace dans le dossier final qu'apres succes.

- **Code** : dossier de staging
- **A ne pas confondre avec** : Le dossier final.

### DB

La base de donnees PostgreSQL de Raton (sqlite en `make demo` et en test). On dit « dans la DB », jamais « en base » ni « la base » seul : « base » est ambigu (base de depart, base de code).

- **Code** : `DATABASE_URL`, `SessionLocal`, service compose `db`
- **A ne pas confondre avec** : Le disque ou sont les fichiers media (voir Stockage media).

### Short

Video courte verticale, listee dans l'onglet shorts de la chaine.

- **Code** : `/shorts/` dans l'URL
- **A ne pas confondre avec** : Une video normale : elle a sa propre cloche et sa propre presentation (mosaique).

### Categorie

Etiquette libre posee sur une chaine, une playlist ou une fiche. Une fiche sans categorie recoit celles de sa chaine ou de sa playlist ; la copie est ensuite ecrite sur la fiche.

- **Code** : `category_labels`
- **A ne pas confondre avec** : Un tag YouTube.

### Note (etoiles)

Note de 0 a 5 donnee par un utilisateur a une chaine ou une fiche ; chacun a la sienne.

- **Code** : `user_videos.rating`, `user_channels.rating`
- **A ne pas confondre avec** : Les *notes structurees* ci-dessous.

### Commentaire

Texte libre d'un utilisateur sur une fiche ; chacun a le sien.

- **Code** : `user_videos.comment`
- **A ne pas confondre avec** : La note en etoiles.

### Notes structurees

Document genere par le LLM a partir du transcript (faits, dates, lieux, acteurs...). Affiche en label **Notes** sur la carte.

- **Code** : `transcript.notes.txt`
- **A ne pas confondre avec** : La note en etoiles.

### Resume

Resume court (3 lignes) genere avec les notes. Il n'existe pas de resume complet.

- **Code** : `transcript.summary_short.txt`
- **A ne pas confondre avec** : Les notes structurees.

### Playlist

Liste ordonnee **locale** de fiches, propre a l'utilisateur qui l'a creee. Un import est un instantane, sans re-synchronisation.

- **Code** : `playlists` (`user_id`)
- **A ne pas confondre avec** : Une playlist YouTube vivante. Supprimer une playlist ne supprime jamais les fiches.

### Ecoute libre

Mode ou le lecteur d'une playlist n'enregistre aucune activite et ne marque rien comme vu.

- **Code** : `playlists.free_listening`
- **A ne pas confondre avec** : Une lecture normale.

Specs : [05 Modele de donnees](05-modele-de-donnees.md),
[06 Stockage fichiers](06-stockage-fichiers.md),
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md).

## Suivi des chaines

### Cloche

Interrupteur de suivi quotidien d'une chaine, propre a chaque utilisateur. Il y en a **deux, independantes**, desactivees par defaut. Une cloche active chez au moins un utilisateur = le scan de 3h importe la section ; les Nouveautes de cet utilisateur la listent.

- **Code** : `user_channels.auto_metadata_enabled` (videos), `user_channels.auto_shorts_enabled` (shorts)
- **A ne pas confondre avec** : Un abonnement YouTube. Il n'y a pas d'autre interrupteur de suivi qu'une cloche.

### Suivie

Une chaine est « suivie » par un utilisateur si au moins une de ses cloches a lui est active. Dans le code, « abonne » se dit `auto_metadata_enabled`.

- **Code** : cloche active
- **A ne pas confondre avec** : Toute chaine qui possede au moins une fiche : les imports de playlist en creent sans que la personne la suive.

### Nouveau / Nouveautes

Une fiche decouverte par le scan quotidien **apres** l'activation de la cloche ; elle est nouvelle pour chaque utilisateur dont la cloche de sa section est active, et pour eux seuls. Le label disparait a la premiere visite de `/videos/{id}` par cet utilisateur. La section « Nouveautes » du dashboard en est la pile, une par chaine qu'il suit.

- **Code** : `user_videos.is_new`, `/dashboard/nouveautes`
- **A ne pas confondre avec** : Une fiche recente ou recemment importee : la synchronisation immediate a l'activation de la cloche et l'import manuel ne posent **jamais** `is_new`.

### Scan

Passage quotidien de 3h `Europe/Paris` sur les chaines a cloche active.

- **Code** : `scheduler.py`, `scanner.py`
- **A ne pas confondre avec** : Un import de metadonnees ponctuel, ou le scan a la demande.

### Import de metadonnees

Creation de fiches **sans** telecharger le media (titre, miniature, `metadata.json`).

- **Code** : `metadata` (statut)
- **A ne pas confondre avec** : Un telechargement (`downloaded`).

### Telechargement manuel

Telechargement video ou audio demande par la personne.

- **Code** : `download_source = "manual"`
- **A ne pas confondre avec** : Un import manuel par formulaire (`imported_via_form`), filtre « Import manuel ».

### Feuille d'import

Panneau de verre ouvert par le bouton rond (trois points verticaux) en haut a
droite des pages Chaines, Playlists et Bibliotheque. Elle ne porte que l'import
de la page : video, playlist, ou chaine et abonnements.

- **Code** : `front/templates/_import_sheet.html`
- **A ne pas confondre avec** : La feuille « Idees de Raton » du chat, ou la
  page `/videos/import`, qui ne fait plus que renvoyer vers la feuille.

Spec : [11 Interface HTML](11-interface-html.md).

### Ingestion

Tout ce qui fait entrer une fiche dans la bibliotheque : le scan, l'import de
metadonnees, le telechargement manuel, l'import d'un fichier local et le
rattrapage des transcripts.

- **Code** : paquet `back/services/ingest/`
- **A ne pas confondre avec** : L'import d'une playlist, qui range des fiches
  dans une playlist (`back/services/playlists/`) ; l'import du CSV
  d'abonnements, qui ajoute des chaines (`back/services/channels/`).

Specs : [02 Fonctionnalites](02-fonctionnalites.md),
[13 Jobs, logs et planification](13-jobs-logs-planification.md),
[07 YouTube et telechargements](07-youtube-et-telechargements.md).

## Lecture et stockage media

### Vu

Une fiche est vue par un utilisateur quand sa lecture a atteint 90 % de la duree (`user_videos.watched_at`) ou quand il la marque vue depuis une liste. `unwatched` force non-vu, `null` suit la detection automatique. Revoir la fiche ne retire pas son Vu, meme si la lecture s'arrete au debut ; dans l'Historique, la ligne d'un tel jour porte « Revu ». Un seul mot, deux origines ; chaque utilisateur a son propre Vu. `videos.watched_at` est le premier Vu de quiconque (remis a `NULL` si un nouveau fichier video ou audio est telecharge) : il ne sert qu'a la purge.

- **Code** : `user_videos.watched_at` (automatique), `user_videos.list_state = "watched"` (a la main), `videos.watched_at` (purge)
- **A ne pas confondre avec** : « Lu », qui n'est pas employe. Un evenement de lecture du journal (`played`) s'affiche « Lecture ».

### Indesiree

Fiche qu'un utilisateur ne veut plus voir dans ses listes : grisee au palier fort, et retiree de ses listes par le selecteur d'affichage sur « Masquer les déjà vues et les indésirées » (le defaut, sauf sur l'Historique). Les autres utilisateurs la voient toujours ; sa page `/videos/{id}` reste ouverte.

- **Code** : `user_videos.list_state = "hidden"`
- **A ne pas confondre avec** : Une fiche supprimee ou purgee. Les mots « cachee » et « ecartee » (l'ancien nom) ne sont pas employes.

### Purge

Suppression quotidienne (4h) des **fichiers media** d'une fiche vue depuis 7 jours (premier Vu de quiconque), sauf si un utilisateur l'a notee 4+. Les fichiers sont partages : la purge vaut pour tous. La fiche reste.

- **Code** : `purge_watched_media`, statut `purged`
- **A ne pas confondre avec** : Une suppression de fiche, ou la suppression d'un seul fichier (video ou audio) a la demande.

### Stockage media

L'ensemble des fichiers media gardes sur disque, borne par le quota global.

- **Code** : `media_storage.py`, `storage.py`
- **A ne pas confondre avec** : Le cache HTTP du navigateur. Le mot « cache » ne designe pas les fichiers media.

Specs : [06 Stockage fichiers](06-stockage-fichiers.md),
[08 Medias et lecteurs](08-medias-et-lecteurs.md).

## LLM et recherche

### Transcript

Texte des sous-titres de la fiche. Etats : `missing`, `downloaded`, `failed`.

- **Code** : `transcript.txt`
- **A ne pas confondre avec** : Les notes structurees, derivees du transcript.

### Job LLM

Demande au LLM : creee tout de suite, executee en tache de fond, le client interroge `GET /api/llm-jobs/{job_id}` jusqu'a la fin.

- **Code** : `LlmJob`, `run_llm_job`
- **A ne pas confondre avec** : Un `download_jobs` (journal des telechargements et scans).

### Journal applicatif

Fichier JSON-lines, un evenement par ligne, ecrit par l'application elle-meme (requetes, jobs, appels externes, erreurs) et conserve 7 jours sur un volume. Sert a relire ce qui s'est passe et a reperer un dysfonctionnement.

- **Code** : `back/core/logging.py`, `LOG_DIR`, `app.jsonl`
- **A ne pas confondre avec** : La page Logs (`/logs`), qui affiche les lignes `download_jobs` pour l'utilisateur.

### Chat

Questions-reponses avec le LLM. Deux portees : le chat d'**une** fiche (page detail) et le chat de **toute la bibliotheque** (barre de l'accueil, avec des outils de recherche). Un seul mot, la portee se dit en complement.

- **Code** : `/api/videos/{id}/chat`, `/api/chat`
- **A ne pas confondre avec** : Un job LLM, qui est la tache de fond derriere chaque reponse.

### Discussion

Un fil de questions-reponses du chat, que le modele relit a chaque question, propre a l'utilisateur qui l'a ouvert. Le chat d'une fiche en a une seule par utilisateur (effacable) ; le chat bibliotheque en garde plusieurs : une question sans discussion en ouvre une nouvelle, nommee d'apres sa premiere question, et les precedentes restent dans le tiroir « Discussions » (☰), rangees sous « Récents ».

- **Code** : `transcript.chat.json` / `transcript.chat.<user_id>.json` (fiche), `library_chat_conversations` / `conversation_id` (bibliotheque)
- **A ne pas confondre avec** : Le chat lui-meme (l'outil), ni l'onglet `Commentaire` d'une fiche.

### Chunk

Morceau de notes ou de resume indexe avec son embedding pour la recherche semantique.

- **Code** : `video_note_chunks`
- **A ne pas confondre avec** : Une portion de fichier media.

### Lot nocturne

Generation automatique des notes structurees a 5h : au plus 100 fiches, collectees au passage suivant.

- **Code** : `auto_notes_sweep`, Message Batches
- **A ne pas confondre avec** : Un job LLM unitaire declenche a la main.

Specs : [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md),
[19 Indexation et recherche dans les notes](19-indexation-et-recherche-notes.md).

## Interface

### Raton

Assistant de la page d'accueil `/` : choisit une replique et un dessin a chaque chargement.

- **Code** : paquet `back/services/raton/` (catalogue `scenarios.py`, tirage `picker.py`, visites `visits.py`)
- **A ne pas confondre avec** : Un composant de chat.

### Dashboard

Pages d'accueil et de suivi (Nouveautes, historique...).

- **Code** : `/dashboard/*`
- **A ne pas confondre avec** : `/` seul, la page de Raton.

### Bibliotheque

Liste des fiches, avec filtres, tri et recherche.

- **Code** : `/videos`
- **A ne pas confondre avec** : La bibliotheque *entiere* au sens du chat bibliotheque.

### Recherche (section de la Bibliotheque)

Section de la Bibliotheque qui cherche des videos sur YouTube lui-meme et ajoute
celle qu'on choisit comme fiche (metadonnees + transcript).

- **Code** : `/videos/recherche` (`youtube_search.html`), `GET /api/youtube/videos`, `back/services/videos/youtube_search.py`
- **A ne pas confondre avec** : Le champ `q` de `/videos` et `/channels`, qui cherche dans la bibliotheque ; la recherche de chaines YouTube de `/channels`.

### Menu de la Bibliotheque

Navigation des pages Bibliotheque (tiroir ouvert par le bouton ☰ a gauche du titre sur telephone, colonne a gauche sur bureau) : un lien par section (Nouveautes, Historique, Exploration, Recherche) puis un par vue enregistree (« Sous-bibliothèques »).

- **Code** : macro `library_menu` (`front/templates/_macros.html`), `initLibraryMenu` (`front/static/js/app.js`)
- **A ne pas confondre avec** : Le tiroir « Discussions » du chat bibliotheque, dont il reprend le style, ni le menu Bibliotheque de la barre du haut (bureau).

### Vue enregistree

Combinaison de filtres et de tri de `/videos` sauvegardee par un utilisateur, pour lui seul.

- **Code** : reglage utilisateur `video_library_views` (`back/services/common/library_views.py`)
- **A ne pas confondre avec** : Une playlist.

### Selecteur d'affichage

Les deux boutons d'une liste (Bibliotheque, page d'une chaine, Nouveautes, Historique) qui choisissent ce qu'elle retire des fiches de l'utilisateur : rien (« Tout voir »), ou les fiches deja vues et les indesirees (« Masquer les déjà vues et les indésirées »).

- **Code** : parametre `hide` (`none`, `watched_hidden`), `LIST_HIDES` (`back/services/videos/filters.py`), macro `list_hide_selector`
- **A ne pas confondre avec** : Un filtre de `/videos` : « Tout effacer » ne le remet pas a zero, et il n'entre pas dans une vue enregistree.

### Carte

Rendu d'une fiche dans une liste.

- **Code** : macro `video_card` (front), donnees `LibraryVideoRead` (`back/api/cards.py`)
- **A ne pas confondre avec** : La page detail `/videos/{id}`.

### Back

L'application qui detient les donnees et les regles : l'API `/api`, la DB,
le dossier media, les jobs et le scheduler.

- **Code** : dossier `back/`, conteneur `api` (port 8001)
- **A ne pas confondre avec** : Le serveur Postgres (`db`), qui n'est que la DB du back.

### Front

L'application des pages HTML : elle ne lit et n'ecrit que par l'API du back,
et relaie vers lui les appels `/api/*` du navigateur.

- **Code** : dossier `front/`, conteneur `app` (port 8000), `RATON_API_URL`
- **A ne pas confondre avec** : Le JavaScript des pages (`front/static/js/`), qui n'en est qu'une partie.

Specs : [03 Architecture](03-architecture.md), [11 Interface HTML](11-interface-html.md),
[18 Raton : scenarios et repliques](18-raton-scenarios.md).

## Developpement

### Preview

Instance jetable de Raton construite a partir d'une PR ouverte, sur la DB
reelle (ou une copie quand la PR a une migration a jouer), sur le port `9000 + N`. Se deploie depuis la page des
previews (`make previews`), qui deploie aussi `main` sur la vraie instance
(`scripts/deploy.sh`).

- **Code** : `scripts/preview.sh`, `scripts/previews.py`, `docker-compose.preview.yml`, projet compose `raton-pr-<N>`
- **A ne pas confondre avec** : `make demo` (le code local, pas celui d'une PR) ; l'apercu d'une playlist avant import.

Specs : [04 Configuration et deploiement](04-configuration-et-deploiement.md).

---
title: "03 Architecture"
---
# 03 Architecture

## Stack

- Python 3.14
- FastAPI
- Jinja2 templates (front)
- httpx (front -> API)
- SQLAlchemy ORM
- Alembic migrations
- PostgreSQL 16 en Docker Compose
- yt-dlp pour YouTube
- ffmpeg dans l'image Docker
- APScheduler pour scans planifies
- API Anthropic pour generation des documents et chat

## Deux dossiers : `back/` et `front/`

Raton est decoupe en deux applications FastAPI, chacune dans son dossier, qui
peuvent tourner dans deux conteneurs (voir
[04 Configuration et deploiement](04-configuration-et-deploiement.md)) :

- **`back/`** : l'API JSON sous `/api` et tout ce qui la sert — services
  (regles metier), modeles, DB, migrations, jobs de fond, scheduler, fichiers
  medias. Seul le back lit la DB, le dossier media et les secrets.
- **`front/`** : les pages HTML (Jinja, rendues cote serveur), leurs
  feuilles de style et scripts, et les replis sans JavaScript des
  formulaires. Le front n'importe **jamais** le back : il lit et ecrit tout
  par l'API, en HTTP (`front/api.py`, adresse `RATON_API_URL`), comme le ferait
  un autre front (une SPA, une app native) ou un serveur MCP.
- **`mcp_server/`** : le serveur MCP, autre client de l'API `/api` en HTTP
  (`mcp_server/api.py`), sans règle métier (voir
  [21 Serveur MCP](21-serveur-mcp.md)).

`tests/test_code_structure.py` verifie la frontiere : `front/` n'importe
rien de `back/`, `back/` rien de `front/`, `mcp_server/` ni l'un ni l'autre, et
seuls `front/api.py`, `front/proxy.py` et `mcp_server/api.py` parlent HTTP.

Ce qui decide d'un comportement (un filtre, un etat Vu/Indesiree deduit de la
lecture, la categorie « sans barre de progression », la pagination, un tri)
est calcule par le back et arrive tout fait dans la reponse de l'API ; le
front ne fait que le mettre en forme (dates et durees en francais, couleurs,
regroupement par jour, liens) et l'afficher.

## Modules du back

### `back/main.py`

Contient uniquement la composition FastAPI, le lifespan (tables de demo,
reglages par defaut, scheduler) et les middlewares (gzip, verification
d'origine, chronometrage). Aucune route : une route va dans le module
`back/api/` de son sujet.

### `back/api/`

L'API JSON sous `/api`, un module par sujet : `channels.py` (chaines,
recherche de chaines YouTube, import CSV des abonnements), `videos.py` (fiches
et leurs actions, recherche de videos YouTube), `media.py` (vignettes, sous-titres, flux audio/video avec `Range`,
avatars et bannieres, tous verifies sous le dossier de la fiche ou des
chaines), `imports.py` (telechargement manuel, import de fichier, import du
raccourci iOS), `library.py` (`GET /api/library` et les cartes par
identifiants), `dashboard.py` (Nouveautes, Historique, temps d'ecran),
`playlists.py`, `llm.py` (demandes au LLM, leurs jobs, cout reel), `jobs.py`
(journal des jobs, page des logs, etat d'un job), `scan.py` (scan des chaines
a la demande, son etat et son flux d'evenements), `stats.py` (`/stats`,
`/rag`, dernier lot de notes automatiques), `settings.py` (reglages et
categories), `raton.py` (la replique de Raton), `users.py` (les utilisateurs,
et `current_user_id`, la dependance qui dit pour quel utilisateur agit une
requete). `__init__.py` les assemble en
un seul routeur, inclus par `back/main.py` ; chaque module a son tag OpenAPI,
et le schema (`/docs` du back) decrit toute l'API. `cards.py` construit la
carte d'une fiche commune a toutes les listes, `lookups.py` trouve
l'enregistrement qu'un chemin designe (fiche, chaine, playlist, element) ou
repond `404` avec le message du service, `errors.py` le format d'erreur
commun.

### `back/core/`

Configuration, journal applicatif, et les middlewares HTTP du back :
`compression.py` (gzip du texte seulement), `same_origin.py` (refus des
ecritures inter-sites), `request_timing.py` (duree et nombre de requetes SQL
de chaque requete).

### `back/services/`

Les regles metier, rangees en paquets par domaine (`common`, `youtube`,
`llm`, `media`, `channels`, `ingest`, `playlists`, `videos`, `raton`, `rag`,
`library_chat`, `jobs`) : role de chaque paquet et de chaque module,
dependances autorisees et regles de structure dans
[10 Services](10-services.md).

## Modules du front

### `front/main.py`

Composition de l'app des pages : middlewares (gzip, verification d'origine
des formulaires), `/static`, le relais `/api/*` et les routeurs de
`front/routes/`. Une erreur de l'API sur une page (fiche inconnue...) est
repondue avec le meme statut et le meme `detail`.

### `front/api.py` et `front/proxy.py`

`api.py` : le client de l'API qu'utilisent les routes des pages ; un refus
leve `ApiError` avec le message francais du back. Chaque appel porte
l'en-tete `X-Raton-User` tire du cookie `raton_user` de la requete de la page
(`get_api`), pour que le back agisse pour le meme utilisateur que le
navigateur. `proxy.py` : le relais des
appels `/api/*` du navigateur vers le back (corps et reponses en flux,
`Range` compris) ; il transmet les en-tetes `Host`, `Origin` et
`Sec-Fetch-*` d'origine, si bien que la verification d'origine du back
s'applique aux ecritures du navigateur. Pages et API partagent donc une seule
origine : pas de CORS.

### `front/records.py`

Le JSON de l'API en objets pour les templates (`Record`) : les dates-heures
ISO redeviennent des `datetime`.

### `front/routes/`

Une page par sujet, et les routes de formulaire qui servent de repli sans
JavaScript (elles appellent l'API puis redirigent) : `dashboard.py`
(accueil, Nouveautes, Historique), `videos.py` (bibliotheque, page d'une
chaine, fiche, import, raccourci iOS `/videos/share-import`), `channels.py`,
`playlists.py`, `stats.py` (`/stats`, `/rag`), `settings.py` (`/settings`,
`/logs`), `raton.py` (`/raton/variations`), `users.py` (changer
d'utilisateur, en ajouter, renommer ou supprimer ; seul endroit qui pose le
cookie `raton_user`).

### Mise en forme

`formatting.py` (dates, durees, tailles, nombres, couleurs des categories),
`cards.py` (badges, libelles de progression, jours de l'Historique, anneaux
de temps d'ecran), `library.py` (de l'URL de `/videos` aux parametres de
`GET /api/library`, pastilles de filtres, liens des vues enregistrees,
mosaique des shorts, periodicite d'une chaine), `video_detail.py` (libelles
de la fiche), `library_chat.py` (le widget du chat de l'accueil), `logs.py`
(badges et jours de `/logs`), `charts.py` (dessin de `/stats`), `pages.py`
(redirections, chemins de retour internes, liens de pagination), `forms.py`
(champs des formulaires), `templating.py` (environnement Jinja et ses
globals).

### `front/templates/_macros.html`

Macro Jinja partagee `video_card(card, next_path, category_style_map,
channel_mode=False, feature=False, index=0, short_tile=False)` : rend une carte de fiche, a partir d'une carte de l'API (`LibraryVideoRead` : l'etat de grisage, l'etat deduit de la lecture et la categorie « sans barre de progression » sont donnes par l'API) — vignette
pleine hauteur, titre, meta, progression de lecture, notation, sans labels
techniques ni categories. Utilisee par `videos.html`, `channel_videos.html`,
`dashboard.html` (section Nouveautes) et `dashboard_new_videos.html` pour
garantir un rendu identique. `channel_mode` est reserve a la page d'une chaine
(`channel_videos.html`) : pastille « Nouveau », progression sur la vignette,
point de note, pas de ligne chaine/date ; `feature` marque les grandes
tuiles de la mosaique des shorts et `index` echelonne l'animation d'entree.
Macro `numbered_pagination(current_page, total_pages, page_href)` :
pagination numerotee de la page d'une chaine (la pagination « Precedent /
Suivant » reste celle des autres pages).

Macro Jinja partagee `video_stack_list(stacks, next_path, category_style_map)` : rend la section Nouveautes — une pile
(`.video-stack`) par chaine, chacune enveloppant ses cartes `video_card`
dans un carrousel navigable aux fleches (`.video-stack-carousel`). Utilisee
par `dashboard.html` et `dashboard_new_videos.html`.

Macro Jinja partagee `media_row(row, category_style_map)` : rend une ligne "Historique"
(une ligne de `GET /api/historique`). Utilisee par `dashboard.html` et `dashboard_history.html`.

La ligne affiche le titre, les labels techniques et categories, la chaine, la
progression de lecture, puis une derniere ligne qui porte le poids du fichier
a gauche et les actions Vu/Indesiree + la notation a droite. Elle ne repete ni la
date de publication ni la date de lecture : le bloc de journee qui la contient
donne deja le jour (voir [02 Fonctionnalites](02-fonctionnalites.md)).

Le JavaScript des pages (`app.js`, `playlist-player.js`) n'appelle que
`/api` (relaye par le front) : un formulaire porte son jumeau dans
`data-api-action`, et son `action` HTML reste le repli sans JavaScript, qui
ne fait que rediriger. Les routes du front ne repondent jamais en JSON (seule
exception : `POST /videos/share-import`, appelee par le raccourci iOS).

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
Browser <video>/<audio> -> /api/videos/{id}/video|audio -> relais du front -> back : StreamingResponse Range -> media file
```

## Contraintes d'architecture

- Les telechargements ecrivent d'abord dans un dossier staging cache.
- Les fichiers ne doivent etre deplaces vers le dossier final qu'apres succes.
- Ajouter un format a une fiche existante doit merger les fichiers staging dans
  le dossier final sans supprimer l'autre format.
- Les routes media restent isolees dans `back/api/media.py`.
- Le front ne lit les donnees que par l'API ; ses templates restent server-rendered, sans framework frontend. Turbo Drive
  (`front/static/js/vendor/`) accelere la navigation entre pages deja rendues
  cote serveur (voir [11 Interface HTML](11-interface-html.md)) mais ne
  change pas ce modele : pas de composants, pas d'etat client, pas d'etape de
  build.

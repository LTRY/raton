---
title: "04 Configuration et deploiement"
---
# 04 Configuration et deploiement

## CSS (Tailwind)

`front/static/css/app.css` est un artefact compile, plus verse en Git
(`.gitignore`). La source versionnee est `front/static/css/tailwind.input.css`
(directives Tailwind v4 + tokens `@theme` + le CSS ecrit a la main, migre
page par page - voir [11 Interface HTML](11-interface-html.md)). Compilation
via le CLI standalone Tailwind (pas de Node/npm) : `scripts/build_css.sh`
telecharge le binaire pour la plateforme courante dans `.local/bin/`
(gitignore, comme `.local/media`) puis compile vers `front/static/css/app.css`.

Preflight (le reset CSS de base de Tailwind) est desactive intentionnellement
(`tailwind.input.css` importe uniquement `theme.css` et `utilities.css`, pas
`preflight.css`) : le CSS ecrit a la main pour les pages pas encore migrees
compte sur le rendu par defaut du navigateur pour `h3`/`h4`/`p`/listes, que
Preflight reinitialiserait globalement. A reevaluer une fois toutes les pages
migrees.

`make css` (aussi un prerequis de `make demo` et `make ci`)
lance ce script. L'image Docker compile le CSS dans une etape de build
dediee (`css-builder` dans le `Dockerfile`) et copie uniquement le fichier
compile dans l'image du front : le conteneur de prod n'a jamais besoin
d'acces reseau pour le CSS.

## Docker Compose

Services :

- `db` : PostgreSQL 16 avec l'extension `pgvector` (image
  `pgvector/pgvector:pg16`, compatible drop-in avec `postgres:16`, meme
  volume). L'extension elle-meme est activee par une migration Alembic
  (`CREATE EXTENSION IF NOT EXISTS vector`), pas par un script d'init compose ;
  elle sert de socle au RAG cross-video sur les notes structurees (voir
  [05 Modele de donnees](05-modele-de-donnees.md) et
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) ;
- `api` : le back (`back/`) — FastAPI + Uvicorn + Alembic + ffmpeg, image
  `raton-api:local` (etape `back` du `Dockerfile`). Seul conteneur qui joint
  PostgreSQL, monte le dossier media et le journal, et recoit les secrets
  (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`). Le scheduler y tourne : une seule
  instance de `api` a la fois ;
- `app` : le front (`front/`) — les pages, image `raton:local` (etape
  `front`). Ni DB, ni media, ni secret : il appelle l'API du conteneur `api`
  (`RATON_API_URL=http://api:8001`) et relaie vers lui les appels `/api/*`
  du navigateur.

Les conteneurs ont un nom fixe (`container_name`) : `raton` pour `app`,
`raton-api` pour `api` et `raton-db` pour `db`, au lieu de `raton-app-1`...
Une seule instance de la pile peut donc tourner par machine.

Port publie : `8000` (`app`, le front), sur `127.0.0.1` par defaut ;
`APP_BIND=0.0.0.0` l'ouvre au LAN. Ni `api` ni `db` ne publient de port : le
navigateur, un raccourci iOS ou un client MCP passent par le front, dont le
relais `/api/*` atteint le back sur le reseau interne de Compose. Seul `api`
joint PostgreSQL.

Volumes :

- `postgres_data` pour PostgreSQL ;
- `${MEDIA_HOST_ROOT:-./.local/media/YouTube}:/media/youtube` ;
- `${LOG_HOST_DIR:-./.local/logs}:/var/log/raton` : le journal
  applicatif, qui doit survivre a la recreation du conteneur a chaque deploiement
  (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md), section
  « Journal applicatif »).

Les jobs LLM (generation et chat, table `llm_jobs`) sont traites
par le conteneur `api` lui-meme, qui appelle directement l'API du fournisseur
configure en tache de fond (voir plus bas et
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)). Il
n'y a pas de worker separe hors Docker.

## Commandes

Commande de deploiement :

```bash
make up
```

Elle doit :

- creer le dossier media hote ;
- reconstruire les deux images (back et front) ;
- lancer PostgreSQL ;
- appliquer les migrations Alembic au demarrage du back ;
- relancer le back puis le front ;
- supprimer l'image precedente devenue orpheline (`docker image prune -f`),
  pour que les builds ne s'empilent pas ; le cache BuildKit est conserve.

### Construction de l'image

Le `Dockerfile` est organise pour que `make up` reste rapide apres un simple
changement de code :

- les dependances Python sont installees avec `uv` depuis `uv.lock`
  (`uv sync --frozen --no-dev --no-install-project`) dans une couche dediee,
  placee **avant** la copie de `back/` et `front/`. Cette couche n'est reconstruite que si
  `pyproject.toml` ou `uv.lock` changent ;
- un cache BuildKit (`/root/.cache/uv`) conserve les wheels deja telechargees
  : meme quand une dependance change, seules les nouvelles versions sont
  telechargees ;
- le binaire Tailwind de l'etape `css-builder` est conserve dans un cache
  BuildKit (`.local/bin`) et n'est pas retelecharge a chaque modification de
  template ;
- le `Dockerfile` est multi-etapes (`css-builder`, `deps`, `base`, puis les
  deux images finales `back` et `front`) : ni `uv`, ni les caches de build, ni
  `curl` n'y sont embarques ; seule l'image `back` a ffmpeg, Alembic et le
  code du back, seule l'image `front` a le code du front et le CSS compile ;
- le conteneur tourne avec l'utilisateur non privilegie `raton` (uid/gid 1000
  par defaut, `--build-arg APP_UID=... APP_GID=...` pour un autre uid). Sous
  Linux, les dossiers montes (media, journal) doivent etre accessibles en
  ecriture a cet uid ;
- le code n'est pas installe comme paquet : il est copie dans `/app`
  et execute depuis ce dossier avec le virtualenv `/app/.venv`.

Consequence : les versions deployees sont exactement celles de `uv.lock`.
L'image n'embarque plus automatiquement le dernier `yt-dlp` a chaque build.
Quand YouTube casse les telechargements, mettre a jour le verrou puis
redeployer :

```bash
make upgrade-ytdlp   # uv lock --upgrade-package yt-dlp
make up
```

Le `uv.lock` modifie doit etre commite.

Les commandes de test sont dans [16 Tests et criteres d'acceptation](16-tests-et-criteres.md).

## Variables d'environnement

### Base

Toutes ces variables sont celles du back (conteneur `api`), sauf mention.

- `RATON_API_URL` (front) : adresse du back que le front appelle et vers
  laquelle il relaie `/api/*` (`http://127.0.0.1:8001` par defaut, `http://api:8001`
  dans le compose). Le front n'a besoin d'aucune autre variable.
- `DATABASE_URL` : URL SQLAlchemy.
- `MEDIA_ROOT` : racine media vue par l'application.
- `POSTGRES_PASSWORD` : mot de passe du role PostgreSQL du service `db`
  (defaut `raton`), lu uniquement par Docker Compose, qui l'injecte aussi dans
  le `DATABASE_URL` de l'application. Il n'est applique qu'a la creation du
  volume `postgres_data` ; caracteres sans danger dans une URL uniquement.
- `MEDIA_ROOT_REMOTE_PREFIX` / `MEDIA_ROOT_LOCAL_PREFIX` : remapping de chemin
  cote lecture seule (`back/core/config.py:local_media_path()`), utilise quand
  une autre machine accede par un point de montage local different a la meme
  bibliotheque media que celle qui a fait les telechargements (ex. prefixe
  `/media/youtube` du conteneur Docker remplace par un montage reseau local). Ne modifie rien dans la DB ; s'applique uniquement au moment de lire
  les fichiers (`back/api/media.py`, `back/services/ingest/identity.py`,
  `back/services/media/media_storage.py`) et, pour les profils de chaines
  (`_channels/`), aussi a leur ecriture et suppression
  (`back/services/channels/profile.py:local_media_root`).
- `GLOBAL_QUOTA_BYTES` : quota global.
- `APP_AUTO_CREATE_TABLES` : creation automatique de tables hors Alembic.
- `LOG_DIR` : dossier du journal applicatif (`app.jsonl`). Vide : pas de
  fichier, seulement stderr (dev, demo). Le compose de prod le fixe
  a `/var/log/raton`.
- `APP_TRUSTED_ORIGINS` (back et front) : hotes (`host[:port]`, separes par
  des virgules) acceptes en plus du `Host` de la requete pour les ecritures,
  derriere un reverse proxy (voir [15 Securite](15-securite.md)). Vide par
  defaut.
- `APP_SCHEDULER_ENABLED` : active/desactive le scheduler (aucun job
  enregistre, ni scan, ni purge, ni backfill, quand elle vaut `false`).

### LLM (generation et chat)

- `LLM_PROVIDER` : fournisseur utilise ; `anthropic` (defaut) est la seule valeur
  acceptee. C'est la seule source du choix : il n'y a plus de reglage
  `app_settings.llm_provider` ni de selecteur dans `/settings`.
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` : cle et modele Anthropic, utilises
  quand `LLM_PROVIDER=anthropic`.

- `VOYAGE_API_KEY` / `EMBEDDING_MODEL` : cle Voyage AI
  (<https://dash.voyageai.com/>) et modele d'embedding (`voyage-3.5` par
  defaut) de la recherche dans les notes du chat bibliotheque. Aucun modele
  n'est execute localement (`torch`/`sentence-transformers` ne sont plus
  des dependances). Sans cle, cette recherche est indisponible et le chat
  le dit ; le reste de l'app n'est pas affecte. Changer de modele ou de
  dimension impose de re-embedder les notes (voir 05 et
  [19](19-indexation-et-recherche-notes.md)).
- `RERANK_MODEL` : modele de reranking Voyage (`rerank-2.5` par defaut),
  applique aux candidats de la recherche vectorielle ; meme cle que ci-dessus.

`ANTHROPIC_API_KEY` est uniquement lue depuis
`.env`/l'environnement (comme `DATABASE_URL`), jamais stockee dans
`app_settings` : c'est un secret, pas un reglage editable depuis
`/settings`. Sans cle valide, la generation et le chat echouent avec un message d'erreur
explicite plutot que de degrader silencieusement.

## `DATABASE_URL`, configuration d'infrastructure

`DATABASE_URL` est une configuration d'infrastructure : l'`engine` SQLAlchemy
est cree une seule fois au demarrage du process, avant qu'aucune session DB
n'existe (`back/db/session.py`). Elle ne peut donc pas etre exposee comme un
reglage editable depuis `/settings`, qui stocke ses valeurs dans la table
`app_settings` de cette meme base : ce serait circulaire (il faut deja etre
connecte a la DB pour lire un reglage qui indiquerait comment s'y
connecter).

Le Docker Compose code `DATABASE_URL` et `MEDIA_ROOT` en dur vers le service
`db` local : `make up` ignore ces deux variables du `.env`. Il n'y a pas de
cible Make pour lancer l'application hors Docker sur une base PostgreSQL ;
`make demo` (`scripts/demo.sh`) lance le back sur une base SQLite jetable
(port 8001) et le front qui l'appelle (port 8000), tous deux rechargés a
chaque modification du code.

## Integration continue (`ci.yml`)

A chaque pull request et a chaque push sur `main`, `make ci` tourne sur un
runner GitHub (`ubuntu-latest`) : CSS, lint `ruff`, tests et validation
Compose. Un second job construit l'image du site de documentation
(`make docs-build`), un troisieme scanne l'historique a la recherche de
secrets (gitleaks). Le deploiement se fait a la main avec `make up`.

Un workflow separe, `pr-title.yml`, valide le titre de chaque PR avec
`scripts/check_pr_title.py` (regles de « Conventions de nommage des PR »
ci-dessous ; les PR de Dependabot sont ignorees). Les regles sont testees dans
`tests/test_pr_title.py`.

### Site de documentation (`docker-compose.docs.yml`, `scripts/docs.sh`)

Les specs de `docs/spec/` sont publiees sur le LAN par un site
[Starlight](https://starlight.astro.build/) (`docs-site/`, Astro), sur le port
`8091` (`DOCS_PORT`), dans son propre projet compose `raton-docs` : ni
`make up` ni `make down` n'y touchent. `docs/spec/` reste la seule source, lue
en place (aucune copie) : chaque fichier commence par un frontmatter
`title` egal a son premier `# ...` (verifie par `tests/test_docs_spec.py`), et
`README.md` porte `slug: index`. Un plugin rehype (`docs-site/plugins/`)
convertit les liens `xx-nom.md` en URL du site et retire le `# ...` en double.

`docs-site/Dockerfile` construit le site avec Node (contexte = racine du depot)
puis le sert avec nginx. `scripts/docs.sh` le (re)construit et le relance. `make docs-dev` lance le serveur Astro local, joignable depuis le LAN (`0.0.0.0`)
(Node >= 22.22 requis), `make docs-build` construit l'image comme le fait la CI
(job `docs` de `ci.yml`).

## Previews des PR

Une preview est une instance jetable de Raton (back et front) construite a
partir d'une PR ouverte, pour l'essayer avant le merge sans toucher a la pile
reelle. Elle se deploie a la main, depuis une page web ou en ligne de commande ;
le merge ne deploie rien.

- **Page des previews** : `make previews` (`scripts/previews.py`, bibliotheque
  standard Python seulement) sert une page sur le port `8999` (`PREVIEWS_PORT`),
  sur l'interface d'`APP_BIND` du `.env` (`PREVIEWS_BIND` la remplace). Elle
  liste les PR ouvertes (via `gh`, qui doit etre connecte au depot), l'etat de
  leur preview (« Pas de preview », « Construction… », « En ligne », « En ligne,
  en retard » quand la PR a recu des commits depuis, « Echec du deploiement »)
  et les boutons **Deployer**/**Redeployer**, **Ouvrir** et **Retirer**. Les
  previews dont la PR est fermee restent listees pour etre retirees, et
  **Retirer les previews des PR fermees** les supprime toutes. La sortie de
  chaque action est dans `.local/previews/logs/pr-<N>.log` (lien **Journal**).
  La page n'a pas d'authentification (comme Raton, reseau local de confiance)
  et refuse un formulaire poste depuis une autre origine.
- **Script** : `scripts/preview.sh up <N>` recupere la tete de la PR
  (`refs/pull/<N>/head`) dans un worktree git `.local/previews/pr-<N>`, puis
  construit et lance le projet compose `raton-pr-<N>`
  (`docker-compose.preview.yml`) ; `down <N>` supprime conteneurs, images et
  worktree ; `list` liste les previews ; `sweep` retire celles des PR fermees.
- **Port** : `9000 + N` (PR 31 : `9031`), sur l'interface d'`APP_BIND`.
- **Isolement** : DB SQLite dans le conteneur `api`, remplie par les donnees de
  demo (`scripts/demo_seed.py`, `APP_AUTO_CREATE_TABLES=true`), recreee a chaque
  deploiement ; pas de dossier media, pas de secret (`ANTHROPIC_API_KEY`,
  `VOYAGE_API_KEY`), scheduler coupe (`APP_SCHEDULER_ENABLED=false`). Les
  migrations Alembic ne tournent pas : le schema vient des modeles de la PR.
- **PR de fork refusees** : la machine construit et execute le code de la PR,
  donc seules les PR du depot lui-meme ont une preview.

`make compose-config` valide aussi `docker-compose.preview.yml`. Les fonctions
de la page sont testees dans `tests/test_previews_page.py`.

## Conventions de nommage des PR

Le titre d'une PR commence par une ou plusieurs etiquettes de perimetre entre
crochets, puis un resume court a l'imperatif, en anglais :
`[FRONT] Stats: link channel names to their channel page`.

| Etiquette | Quand l'utiliser |
| --- | --- |
| `[FRONT]` | templates Jinja, CSS, JavaScript, rendu visible dans l'interface |
| `[BACK]` | routes, services, modeles, scheduler, API JSON, logique metier |
| `[DB]` | migration Alembic ou changement de schema (souvent avec `[BACK]`) |
| `[CI]` | workflows GitHub, `scripts/`, Makefile, Docker |
| `[DOCS]` | uniquement `docs/spec/` ou commentaires, sans changement de comportement |

Regles :

- une PR qui touche le front **et** le back porte les deux etiquettes, dans
  l'ordre `[FRONT][BACK]`, sans espace entre elles ; il n'y a pas de limite
  de nombre, mais une PR qui en cumule beaucoup est probablement trop large :
  la couper ;
- l'etiquette decrit ce que la PR change, pas ce qu'elle lit : un correctif de
  spec accompagnant du code ne justifie pas `[DOCS]` ;
- un correctif commence le resume par `Fix` (`[BACK] Fix scan skipping
  shorts`) ; pas d'autre prefixe de type (`feat:`, `fix:`) ;
- resume : 72 caracteres maximum, majuscule initiale, pas de point final, pas
  de numero de PR ni d'identifiant de session ;
- ces regles sont verifiees par `scripts/check_pr_title.py` (workflow
  `pr-title.yml`) ;
- le commit principal de la branche reprend le meme resume sans etiquette ;
- la description suit `.github/pull_request_template.md` et reste courte et
  concrete : « Quoi » (1 a 3 puces sur ce qui change : page, bouton, route,
  comportement), « Pourquoi » (une phrase), et les captures d'ecran pour tout
  `[FRONT]` (bureau et telephone si la mise en page differe) ; pas de
  checklist, pas de liste de fichiers ou de tests, pas de compte rendu de
  `make ci` (la CI l'affiche) ;
- ni la description, ni les messages de commit, ni les commentaires GitHub ne
  contiennent de lien vers une session Claude Code
  (`https://claude.ai/code/session_...`, trailer `Claude-Session:`).

## Regle post-modification

Voir « Regle de maintenance obligatoire » dans le [README](README.md) et les
criteres d'acceptation de [16 Tests et criteres d'acceptation](16-tests-et-criteres.md).
`make up` est la commande de deploiement.

---
title: "04 Configuration et deploiement"
---
# 04 Configuration et deploiement

## CSS (Tailwind)

`app/static/css/app.css` est un artefact compile, plus verse en Git
(`.gitignore`). La source versionnee est `app/static/css/tailwind.input.css`
(directives Tailwind v4 + tokens `@theme` + le CSS ecrit a la main, migre
page par page - voir [11 Interface HTML](11-interface-html.md)). Compilation
via le CLI standalone Tailwind (pas de Node/npm) : `scripts/build_css.sh`
telecharge le binaire pour la plateforme courante dans `.local/bin/`
(gitignore, comme `.local/media`) puis compile vers `app/static/css/app.css`.

Preflight (le reset CSS de base de Tailwind) est desactive intentionnellement
(`tailwind.input.css` importe uniquement `theme.css` et `utilities.css`, pas
`preflight.css`) : le CSS ecrit a la main pour les pages pas encore migrees
compte sur le rendu par defaut du navigateur pour `h3`/`h4`/`p`/listes, que
Preflight reinitialiserait globalement. A reevaluer une fois toutes les pages
migrees.

`make css` (aussi un prerequis de `make demo` et `make ci`)
lance ce script. L'image Docker compile le CSS dans une etape de build
dediee (`css-builder` dans le `Dockerfile`) et copie uniquement le fichier
compile dans l'image finale : le conteneur de prod n'a jamais besoin
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
- `app` : FastAPI + Uvicorn + Alembic + ffmpeg.

Les conteneurs ont un nom fixe (`container_name`) : `raton` pour `app` et
`raton-db` pour `db`, au lieu de `raton-app-1` / `raton-db-1`. Une seule
instance de la pile peut donc tourner par machine.

Port publie : `8000` (app), sur `127.0.0.1` par defaut ; `APP_BIND=0.0.0.0` l'ouvre au LAN. Le service `db` ne publie aucun port : seul
le conteneur `app` joint PostgreSQL, par le reseau interne de Compose.

Volumes :

- `postgres_data` pour PostgreSQL ;
- `${MEDIA_HOST_ROOT:-./.local/media/YouTube}:/media/youtube` ;
- `${LOG_HOST_DIR:-./.local/logs}:/var/log/raton` : le journal
  applicatif, qui doit survivre a la recreation du conteneur a chaque deploiement
  (voir [13 Jobs, logs et planification](13-jobs-logs-planification.md), section
  « Journal applicatif »).

Les jobs LLM (generation et chat, table `llm_jobs`) sont traites
par le conteneur `app` lui-meme, qui appelle directement l'API du fournisseur
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
- reconstruire l'image Docker ;
- lancer PostgreSQL ;
- appliquer les migrations Alembic au demarrage de l'app ;
- relancer FastAPI ;
- supprimer l'image precedente devenue orpheline (`docker image prune -f`),
  pour que les builds ne s'empilent pas ; le cache BuildKit est conserve.

### Construction de l'image

Le `Dockerfile` est organise pour que `make up` reste rapide apres un simple
changement de code :

- les dependances Python sont installees avec `uv` depuis `uv.lock`
  (`uv sync --frozen --no-dev --no-install-project`) dans une couche dediee,
  placee **avant** la copie de `app/`. Cette couche n'est reconstruite que si
  `pyproject.toml` ou `uv.lock` changent ;
- un cache BuildKit (`/root/.cache/uv`) conserve les wheels deja telechargees
  : meme quand une dependance change, seules les nouvelles versions sont
  telechargees ;
- le binaire Tailwind de l'etape `css-builder` est conserve dans un cache
  BuildKit (`.local/bin`) et n'est pas retelecharge a chaque modification de
  template ;
- l'image finale est multi-etapes (`css-builder`, `deps`, image finale) : ni
  `uv`, ni les caches de build, ni `curl` n'y sont embarques ;
- le conteneur tourne avec l'utilisateur non privilegie `raton` (uid/gid 1000
  par defaut, `--build-arg APP_UID=... APP_GID=...` pour un autre uid). Sous
  Linux, les dossiers montes (media, journal) doivent etre accessibles en
  ecriture a cet uid ;
- le code de l'app n'est pas installe comme paquet : il est copie dans `/app`
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

- `DATABASE_URL` : URL SQLAlchemy.
- `MEDIA_ROOT` : racine media vue par l'application.
- `POSTGRES_PASSWORD` : mot de passe du role PostgreSQL du service `db`
  (defaut `raton`), lu uniquement par Docker Compose, qui l'injecte aussi dans
  le `DATABASE_URL` de l'application. Il n'est applique qu'a la creation du
  volume `postgres_data` ; caracteres sans danger dans une URL uniquement.
- `MEDIA_ROOT_REMOTE_PREFIX` / `MEDIA_ROOT_LOCAL_PREFIX` : remapping de chemin
  cote lecture seule (`app/core/config.py:local_media_path()`), utilise quand
  une autre machine accede par un point de montage local different a la meme
  bibliotheque media que celle qui a fait les telechargements (ex. prefixe
  `/media/youtube` du conteneur Docker remplace par un montage reseau local). Ne modifie rien dans la DB ; s'applique uniquement au moment de lire
  les fichiers (`app/web/routes/media.py`, `app/services/channels/identity.py`,
  `app/services/media/media_storage.py`) et, pour les profils de chaines
  (`_channels/`), aussi a leur ecriture et suppression
  (`app/services/channels/profile.py:local_media_root`).
- `GLOBAL_QUOTA_BYTES` : quota global.
- `APP_AUTO_CREATE_TABLES` : creation automatique de tables hors Alembic.
- `LOG_DIR` : dossier du journal applicatif (`app.jsonl`). Vide : pas de
  fichier, seulement stderr (dev, demo). Le compose de prod le fixe
  a `/var/log/raton`.
- `APP_TRUSTED_ORIGINS` : hotes (`host[:port]`, separes par des virgules)
  acceptes en plus du `Host` de la requete pour les ecritures, derriere un
  reverse proxy (voir [15 Securite](15-securite.md)). Vide par defaut.
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
n'existe (`app/db/session.py`). Elle ne peut donc pas etre exposee comme un
reglage editable depuis `/settings`, qui stocke ses valeurs dans la table
`app_settings` de cette meme base : ce serait circulaire (il faut deja etre
connecte a la DB pour lire un reglage qui indiquerait comment s'y
connecter).

Le Docker Compose code `DATABASE_URL` et `MEDIA_ROOT` en dur vers le service
`db` local : `make up` ignore ces deux variables du `.env`. Il n'y a pas de
cible Make pour lancer l'application hors Docker sur une base PostgreSQL ;
`make demo` utilise une base SQLite jetable.

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
- la description contient : un resume du changement et de sa raison, les
  fichiers de spec mis a jour, les captures d'ecran pour tout `[FRONT]`
  (bureau et telephone si la mise en page differe), et le resultat de
  `make ci`.

## Regle post-modification

Voir « Regle de maintenance obligatoire » dans le [README](README.md) et les
criteres d'acceptation de [16 Tests et criteres d'acceptation](16-tests-et-criteres.md).
`make up` est la commande de deploiement.

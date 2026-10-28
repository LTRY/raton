---
title: "L'outil ops"
---

# L'outil ops

L'outil ops est le code de `ops/` : la page des previews, le deploiement de la
branche principale et la revue quotidienne des journaux. Il tourne dans un
conteneur a part (etape `ops` du `Dockerfile` du depot), en bibliotheque standard
Python seulement, et ne connait aucun projet par son code : il lit un `ops.toml` a
la racine du depot qu'il sert et appelle les scripts que ce fichier nomme. Le
projet fournit donc ce **contrat** (`ops.toml`, un script de previews, un script
de deploiement, de quoi lancer l'outil) ; ce que Raton y met est decrit dans
`docs/spec/04-configuration-et-deploiement.md`,
sections « Deploiement de main » et « Previews des PR ». Les regles de travail
sur ce dossier sont dans `ops/CLAUDE.md`.

## Configuration de l'outil ops

Tout ce qui nomme le projet est lu dans `ops.toml`, a la racine du depot servi
(`ops/config.py`). Ce depot est `OPS_REPO` quand la variable est posee (le
conteneur y monte le depot au meme chemin que sur l'hote), sinon le depot qui
contient `ops/`. Un autre projet reutilise l'outil en fournissant son propre
`ops.toml` et ses scripts.

- `[project] name` : nom affiche dans le titre de la page et la confirmation du
  deploiement.
- `[deploy]` : `script` (lance par le bouton **Deployer main en production**),
  `branch` (suivie pour comparer avec la version deployee), `container` et
  `sha_label` (conteneur en marche et label de son image qui porte le commit
  construit ; sans eux, la version deployee reste « inconnue »).
- `[previews] script` : le script de previews (`up`, `down`, `sweep`,
  `list`), propre au projet : la base partagee ou copiee, les ports et les
  reseaux y restent.
- `[jobs] timeout_minutes` (30 par defaut) : un job de preview ou de deploiement
  encore en cours apres ce delai est arrete (SIGTERM puis SIGKILL sur tout son
  groupe de processus), son journal le dit et la page le montre en echec ; sans
  cela, le bouton resterait grise indefiniment.
- `[review]` : `skill` (skill Claude Code lance chaque jour), `allowed_tools`
  (outils en lecture seule), puis les valeurs par defaut `hour`, `hours`,
  `model`, `max_usd`, que `OPS_REVIEW_HOUR`, `OPS_REVIEW_HOURS`,
  `OPS_REVIEW_MODEL` et `OPS_REVIEW_MAX_USD` surchargent.

Une cle absente prend la valeur par defaut de `OpsConfig`. Verification :
`ops/tests/test_ops_config.py`.

## Jobs persistes

L'etat des jobs (un par PR, plus le deploiement de production) est ecrit dans
`.local/previews/jobs/` : un fichier JSON par job (`pr-<N>.json`, `prod.json`)
avec `action`, `pr`, `started` (heure de debut), `pid` (le processus du script,
chef de son groupe), `pid_start` (son heure de demarrage lue dans `/proc`, pour
reconnaitre un pid reutilise), `returncode` et `interrupted`. Le fichier est
reecrit (de facon atomique) au lancement, quand le pid est connu et a la fin.
Au demarrage, la page relit ces fichiers :

- un job termine reste tel quel ;
- un job « en cours » dont le processus n'existe plus (conteneur redemarre,
  pid inconnu ou reutilise) devient **interrompu** : `returncode` 1,
  `interrupted` vrai, une ligne « Interrompu » ajoutee a son journal, et la page
  montre « Interrompu (la page a redemarre) » / « Deploiement interrompu » en
  echec, bouton de nouveau actif ;
- un job dont le processus tourne encore est surveille : il passe a interrompu
  quand le processus disparait, ou est arrete apres `timeout_minutes`.

Un fichier illisible est ignore et signale sur la sortie du serveur. Le
journal d'un job (`.local/previews/logs/`) n'est pas touche.

## Contrat du script de previews

`[previews] script` est un executable appele depuis la racine du depot
(`ops/jobs.py`) avec l'environnement de la page (`GH_TOKEN`,
`OPS_REPO`, acces au Docker de l'hote...) ; la page ne lui en fournit pas
d'autre. Il n'a pas de terminal : il ne lit pas l'entree standard.

| Appel | Role | Sortie |
|---|---|---|
| `<script> up <pr>` | construit et lance la preview de la PR | journal du job |
| `<script> down <pr>` | retire la preview de la PR | journal du job |
| `<script> sweep` | retire les previews des PR qui ne sont plus ouvertes (sans argument) | ignoree |
| `<script> list` | liste les previews | lue par la page (ci-dessous) |

`<pr>` est un numero de PR, entier decimal. Les sous-commandes `up` et
`down` tournent comme jobs en arriere-plan (un a la fois par PR), avec stdout et
stderr dans `.local/previews/logs/pr-<N>.log`.

**Code de retour** : 0 en cas de succes, non nul en cas d'echec, que la page
montre comme « Echec » (127 : le script n'a pas pu demarrer ; 124 : arrete
apres `timeout_minutes`). Convention du script fourni : 2 pour un appel
incorrect (sous-commande inconnue, numero de PR absent ou non numerique), un
message d'usage sur stderr.

**Format de `list`** : une ligne par preview sur stdout, cinq champs separes
par des espaces, sans ligne d'entete :

```
<pr> <port> <commit> <etat> <db>
31 9031 3f2a9c0d4b1e8a7c6d5e4f3a2b1c0d9e8f7a6b5c running copy
```

- `pr` : numero de PR, chiffres ASCII ;
- `port` : port de la preview sur l'hote, de 1 a 65535 ;
- `commit` : le commit construit, hexadecimal en minuscules (7 a 40 caracteres),
  ou `-` s'il est inconnu ;
- `etat` : etat du conteneur (`running`, `exited`, `created`...), minuscules ;
- `db` : `shared` (DB reelle), `copy` (copie migree) ou `-` si inconnu.

Une sortie vide veut dire aucune preview. Les lignes vides sont ignorees. Toute
autre ligne qui ne respecte pas ce format, ou qui repete un numero de PR deja
liste (la premiere est gardee), est **ignoree mais signalee** : la page affiche
en bandeau « N ligne(s) invalide(s) ignoree(s) (premiere : ... ») et le meme
texte va sur la sortie du serveur. Un `list` qui sort avec un code non nul,
qui ne peut pas demarrer ou qui ne repond pas en 30 s (il est alors arrete,
avec son groupe de processus) est signale de la meme facon (les lignes valides qu'il
a imprimees sont gardees). `ops/jobs.py` : `parse_previews` (retourne
les previews et les lignes invalides), `list_previews`.

`retire-stale` n'est pas appele par la page : c'est le point d'entree de
`make up` de ce projet. Verification du contrat : `ops/tests/test_ops_jobs.py`
appelle `scripts/preview.sh` avec un faux `docker` et un faux `gh` (`list`,
`sweep`, appels incorrects) et teste `parse_previews` sur des lignes valides
et invalides.

**Cache des lectures** : la page se rafraichit toutes les 4 s pendant un job.
La liste des PR (`gh`), le commit deploye (`docker inspect`) et le retard sur
`origin/main` sont gardes 15 s (`CACHE_TTL`), le `git fetch` 30 s ; le lien
**Rafraichir** (`/?refresh=1`) et la fin d'un job les relisent aussitot. La liste
des previews (`list`) n'est pas mise en cache.

**Jeton de la page** : la page peut deployer en production depuis un conteneur
root qui pilote Docker. Par defaut elle est ouverte, comme Raton (LAN de
confiance). Avec `OPS_TOKEN` dans le `.env`, chaque requete (page, journaux,
actions) doit porter ce jeton comme mot de passe d'une authentification HTTP
Basic (nom d'utilisateur libre) ; le navigateur le demande une fois. Sans jeton
et avec une interface autre que loopback, la page affiche un avertissement au
demarrage. Le jeton ne vit pas dans `ops.toml` (versionne).

## Verrou de deploiement

Un seul deploiement a la fois, qu'il vienne du
bouton ou d'un `scripts/deploy.sh` lance a la main. `deploy.sh` se relance sous
`ops/deploy_lock.py`, qui prend sans attendre un `fcntl.flock` exclusif sur
`.local/previews/deploy.lock` puis execute le script ; le verrou est tenu tant
que le deploiement (et ses processus fils) tourne, et le noyau le libere si le
processus meurt. Si un autre deploiement le tient, `deploy.sh` n'a rien fait
quand `ops/deploy_lock.py` affiche `Un deploiement est deja en cours : rien n'est
deploye` et sort avec le code 75. La page lit le meme verrou : quand il est tenu
par un deploiement qu'elle n'a pas lance, la carte **Production** affiche
« Deploiement deja en cours (lance hors de cette page) », le bouton est grise
et un POST sur `/prod/deploy` ne lance rien. `make up` prend le
meme verrou (sa recette passe par `ops/deploy_lock.py`, cible `up-locked`) ; quand
`deploy.sh` l'a deja pris, le `make up` qu'il lance le sait par la variable
`DEPLOY_LOCK_HELD=1` et ne le reprend pas. Un flock ne protege que
les processus d'un meme noyau : le depot monte dans `le conteneur ops` par bind mount
et la machine hote partagent le noyau sous Linux, mais pas avec Docker
Desktop (macOS, Windows), ou le verrou ne croise pas la frontiere de la VM ;
ce croisement n'est pas verifie par les tests, qui couvrent deux processus
d'une meme machine (`ops/tests/test_ops_jobs.py`).

## Code

`ops/jobs.py` (PR, previews, lancement des scripts en arriere-plan, jobs
persistes), `ops/deploy_lock.py` (verrou de deploiement), `ops/render.py` (HTML et
libelles d'etat), `ops/graph.py` (graphe des commits de l'alerte de production), `ops/server.py` (serveur, jeton), `ops/review.py` (revue des
journaux), `ops/config.py` (`ops.toml`). Les tests sont dans `ops/tests/`, lances
par `make test` ; le linter (`make lint`, `make format`) couvre `ops/`. Un test de
`tests/test_code_structure.py` garde l'outil independant de Raton : `ops/` n'importe
rien de `back/`, `front/` ni `scripts/`, et ne contient pas le nom du projet.

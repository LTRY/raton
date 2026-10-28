---
title: "L'outil monitoring"
---

# L'outil monitoring

L'outil monitoring est le code de `monitoring/` : une page qui montre ce que la
surveillance du projet a trouve, aujourd'hui la revue quotidienne des journaux.
Il tourne dans un conteneur a part (etape `monitoring` du `Dockerfile`, lance par
`make monitoring`), en bibliotheque standard Python seulement, avec le CLI
Claude Code et la cle `ANTHROPIC_API_KEY`. Il est separe de l'outil ops
(`ops/docs/outil-ops.md`) : ops agit sur l'infrastructure (previews,
deploiement) sans aucune dependance a Claude ; monitoring observe. Les regles de
travail sur ce dossier sont dans `monitoring/CLAUDE.md`.

L'outil est prevu pour accueillir d'autres rapports (couts du RAG, metriques
fonctionnelles de l'application). Il ne lit jamais la base du projet : une
metrique passera par l'API du projet en HTTP, ou par ses fichiers de journal.

## Configuration de l'outil monitoring

Tout ce qui nomme le projet est lu dans `monitoring.toml`, a la racine du depot
surveille (`monitoring/config.py`). Ce depot est `MONITORING_REPO` quand la
variable est posee (le conteneur y monte le depot sur `/project`), sinon le depot
qui contient `monitoring/`.

- `[project] name` : nom affiche dans le titre de la page.
- `[review]` : `skill` (skill Claude Code lance chaque jour), `allowed_tools`
  (outils en lecture seule), puis les valeurs par defaut `hour`, `hours`,
  `model`, `max_usd`, que `MONITORING_REVIEW_HOUR`, `MONITORING_REVIEW_HOURS`,
  `MONITORING_REVIEW_MODEL` et `MONITORING_REVIEW_MAX_USD` surchargent.

Une cle absente prend la valeur par defaut de `MonitoringConfig`. Verification :
`monitoring/tests/test_monitoring_config.py`.

## Page de monitoring

`monitoring/server.py` sert la page sur le port `8998` (`MONITORING_PORT`, interface
d'`APP_BIND` dans le conteneur) : une carte par rapport. Aujourd'hui, la carte
**Revue des journaux** (voir `docs/spec/13-jobs-logs-planification.md`, « Revue
quotidienne des journaux »). La page se rafraichit toute seule pendant qu'une
revue tourne.

**Jeton de la page** : par defaut elle est ouverte, comme Raton (LAN de confiance).
Avec `MONITORING_TOKEN` dans le `.env`, chaque requete doit porter ce jeton comme
mot de passe d'une authentification HTTP Basic (nom d'utilisateur libre). Un
formulaire envoye depuis un autre site est refuse. Le jeton ne vit pas dans
`monitoring.toml` (versionne). Verification :
`monitoring/tests/test_monitoring_server.py`.

## Code

`monitoring/review.py` (revue des journaux : planification, lancement de Claude
Code, stockage, carte), `monitoring/render.py` (page et CSS),
`monitoring/server.py` (serveur, jeton), `monitoring/config.py`
(`monitoring.toml`). Les tests sont dans `monitoring/tests/`, lances par
`make test` ; le linter (`make lint`, `make format`) couvre `monitoring/`. Un
test de `tests/test_code_structure.py` garde l'outil independant de Raton et
d'ops : `monitoring/` n'importe rien de `back/`, `front/`, `mcp_server/`,
`scripts/` ni `ops/`, et ne contient pas le nom du projet.

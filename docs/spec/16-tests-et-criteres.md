---
title: "16 Tests et criteres d'acceptation"
---
# 16 Tests et criteres d'acceptation

## Commandes

Tests complets :

```bash
UV_CACHE_DIR=.local/uv-cache uv run pytest
```

CI locale, a executer avant d'ouvrir une pull request :

```bash
make ci
```

`make ci` enchaine le CSS, le lint (`make lint` : `ruff check` et
`ruff format --check`, configuration dans `pyproject.toml`, section
`[tool.ruff]`), les tests et la validation Compose. Le meme `make ci` tourne
sur GitHub a chaque pull request (`.github/workflows/ci.yml`). `make format`
corrige automatiquement ; `E501` (longueur de ligne) est ignore : c'est le
formateur qui coupe les lignes, `ruff check` ne signalerait que des
commentaires et des chaines. `B008` reste actif : les appels FastAPI
(`Depends`, `Query`, `Form`, `File`, `Path`) sont declares immuables dans
`pyproject.toml`.

`make docs-build` construit l'image du site de documentation (comme le job
`docs` de la CI) ; `tests/test_docs_spec.py` verifie le frontmatter `title` de
chaque spec.

`scripts/screenshot.sh [chemin] [dossier]` sert a verifier une page a la main :
il lance l'application sur une DB sqlite jetable remplie par
`app/services/demo_seed.py`, prend une capture a 1280 px (`desktop.png`) et une
a 390 px (`phone.png`) avec Playwright, affiche `scrollWidth` et `clientWidth`
aux deux largeurs (egaux = pas de defilement horizontal de la page), puis arrete
le serveur. Il n'est pas lance par la CI ; `tests/test_page_overflow_css.py`
garde seulement le filet `overflow-x: clip` de `html`/`body`.

## Couverture attendue

### Videos et pages

Verifier :

- les cartes videos ne lient pas vers YouTube ;
- les labels Audio/Video/Metadata/Transcript ;
- les thumbnails de liste ;
- la page detail ;
- les players audio/video ;
- les routes Range ;
- les actions formats manquants ;
- l'integration transcript/discussion ;
- la redirection de l'ancienne page transcript.

### Stockage

Verifier :

- staging avant dossier final ;
- remplacement metadata-only ;
- ajout audio a video existante ;
- ajout video a audio existant ;
- preservation des fichiers existants ;
- quota global ;
- notes préservées ;
- graphiques `/stats` (`tests/test_stats.py`) : agregation par chaine et par
  format, regroupement "Autres" au-dela du top 10, fenetre de 12 mois et
  cumul, bibliotheque vide, vue de la page (mois vides ecartes, phrase de
  synthese, chiffres cles, courbe), depenses en modele par mois et par groupe.
- tableau de bord `/rag` (`tests/test_rag_dashboard.py`) : une video dans
  exactement une etape, labels de la chaine a defaut de ceux de la video,
  prochain lot plafonne et trie, lot en cours, couts et historique, chunks,
  heure du prochain passage, nombre de requetes constant.

### Cloche et nouveautes

Verifier :

- le scan quotidien ne traite que les chaines avec la cloche active ;
- activer la cloche declenche un import metadata immediat en arriere-plan ;
- visiter la page detail d'une video retire son label `Nouveau`.

### YouTube

Verifier :

- detection audio/video ;
- configuration audio M4A et extraction de la piste audio d'une video deja telechargee ;
- sous-titres FR/EN ;
- pagination chaine ;
- comptage chaine.

## Criteres d'acceptation par changement

Un changement est termine si :

- le code implemente la demande ;
- la spec concernee est mise a jour ;
- les tests pertinents passent ;
- la suite complete passe si surface partagee ;
- `make ci` passe ;
- une pull request vers `main` est ouverte sur le depot GitHub.

Le deploiement (`make up`) ne fait pas partie des criteres d'acceptation.

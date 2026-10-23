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
`scripts/demo_seed.py` (trois chaines, une quinzaine de fiches variees : titres
courts et longs, etoiles, Vu, Ecartee, lectures en cours pour la barre de
progression ; quelques transcripts ; aucun fichier media, donc Exploration ne les
montre qu'une fois le filtre de type de fichier vide), prend une capture a 1280 px (`desktop.png`) et une
a 390 px (`phone.png`) avec Playwright, affiche `scrollWidth` et `clientWidth`
aux deux largeurs (egaux = pas de defilement horizontal de la page), puis arrete
le serveur. Il n'est pas lance par la CI ; `tests/test_page_overflow_css.py`
garde seulement le filet `overflow-x: clip` de `html`/`body`.

### Évaluer un prompt

`scripts/eval_prompts.py` compare deux variantes d'un prompt sur de vrais
transcripts (la tâche du lot nocturne : notes + résumé court) :

```
uv run --python 3.14 python -m scripts.eval_prompts \
    --a evals/notes/current.py --b evals/notes/candidate.py [--n 8] [--seed 1] \
    [--model claude-haiku-5-5] [--media-root CHEMIN] [--env-file .env] [--dry-run]
```

- une variante est un fichier Python avec `build(transcript)` qui renvoie un
  `Prompt` (voir `evals/notes/`) : `current.py` suit le prompt de l'application,
  `candidate.py` est la copie à modifier ;
- les mêmes `--n` transcripts (tirés avec `--seed`, parmi les `transcript.txt`
  d'au moins `MIN_TRANSCRIPT_CHARS` octets sous `--media-root`, par défaut
  `.local/media/YouTube`) passent dans les deux variantes ;
- le rapport `.local/evals/<date>/report.html` (et `results.json`) montre les deux
  sorties côte à côte, avec jetons, coût et durée, les sorties qui ne se
  parsent pas (notes vides, résumé court qui n'a pas 3 phrases) signalées avec
  leur réponse brute, et un vote A / B / égal par vidéo gardé dans le navigateur ;
- une réponse est mise en cache (`.local/evals/cache/`) sous un hachage du modèle
  et du `Prompt` envoyé : relancer après avoir modifié une variante ne paie que
  celle-là ; `--dry-run` liste les appels à payer sans en faire ;
- les rapports contiennent les transcripts : `.local/` est ignoré par git ;
- l'appel passe par `AnthropicProvider.complete`, sans l'`effort` bas du lot
  nocturne : le coût et la longueur de sortie peuvent différer un peu de ceux du lot.

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

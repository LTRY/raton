---
name: review-logs
description: Revue du journal applicatif de Raton sur les dernières 24 h (ou N heures) : conclut "fonctionnement nominal" ou liste les problèmes par gravité avec leur cause probable. À utiliser quand l'utilisateur tape /review-logs ou demande de relire les logs, de vérifier que l'application tourne bien ou de chercher un dysfonctionnement. Lecture seule : ne modifie ni code ni données.
---

# Revue du journal applicatif

Tu relis le journal applicatif (`app.jsonl`, voir `docs/spec/13-jobs-logs-planification.md`, section « Journal applicatif ») et tu rends un verdict : **nominal** ou **problèmes**. Tu ne corriges rien, tu ne lances ni `make up` ni aucun script de déploiement, tu ne redémarres rien : tu constates et tu proposes.

Argument optionnel : un nombre d'heures (`/review-logs 48`), 24 par défaut.

## 1. Trouver le journal

Le journal de l'instance qui tourne est dans le checkout principal, pas dans un worktree :

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
LOG_DIR="$(sed -n 's/^LOG_HOST_DIR=//p' "$MAIN/.env" 2>/dev/null | tail -n 1 | tr -d "\"'")"
LOG_DIR="${LOG_DIR:-$MAIN/.local/logs}"
ls -la "$LOG_DIR"
```

Si le dossier n'existe pas ou `app.jsonl` est vide : dis-le, c'est déjà un constat (l'application n'a pas démarré avec le volume de journal, ou l'application n'a pas été relancée avec `make up` depuis l'ajout de ce volume). Vérifie alors `docker ps` et `docker compose logs --since 24h app | tail -200` comme repli, et signale que ce repli est moins fiable.

## 2. Lire le digest

```bash
uv run --python 3.14 python -m app.services.logs_digest --dir "$LOG_DIR" --hours 24
```

Il résume : niveaux, redémarrages, signaux automatiques, erreurs et avertissements groupés, réponses 5xx, requêtes lentes, jobs, appels externes.

## 3. Creuser chaque anomalie dans le journal brut

Pour chaque signal, remonte à la source avec `grep`/`jq` sur `$LOG_DIR/app.jsonl*` :

```bash
jq -c 'select(.level=="ERROR")' "$LOG_DIR"/app.jsonl | tail -20
jq -c 'select(.request_id=="<id>")' "$LOG_DIR"/app.jsonl      # toutes les lignes d'une requête
jq -c 'select(.event|startswith("job."))' "$LOG_DIR"/app.jsonl  # chronologie des jobs
```

Cherche la **cause**, pas seulement le symptôme : une erreur isolée après un redémarrage n'est pas une panne ; la même erreur toutes les 10 minutes en est une.

## 4. Ce qui est normal (ne pas le signaler comme un problème)

- Un `HTTP 429` de YouTube (`ext.error` en WARNING, scan `rate_limited`) : prévu, repris le lendemain. Le signaler seulement s'il se répète plusieurs jours de suite ou arrive dès la première chaîne.
- Une vidéo « pas encore disponible » (premiere programmée).
- `scheduler.disabled` sur une instance de preview ou de dev.
- Des lignes `job.record` de statut `warning`/`skipped` isolées.
- Un seul `app.started` juste après un déploiement.

## 5. Ce qui est anormal

- Toute exception non gérée (`request.error`), toute réponse 5xx.
- Un job planifié attendu (`scheduled_scan` 3 h, `scheduled_media_purge` 4 h, `scheduled_auto_notes` 5 h) sans `job.start`, ou sans `job.end`/`job.error`.
- Plusieurs `app.started` sans déploiement correspondant (crash en boucle, OOM).
- Un service externe en échec répété (Anthropic, Voyage, yt-dlp hors 429).
- Des requêtes lentes récurrentes (`SLOW`, `LOOP-LAG`) : sépare SQL (`sql_ms`) du reste (`duration_ms`).
- Des `ext.error` d'authentification (clé API absente ou invalide).

## 6. Format de la réponse

Une réponse courte, en français :

1. **Verdict** en une ligne : `Nominal` ou `N problème(s)`.
2. **Période** couverte et volume (lignes, requêtes, redémarrages).
3. Si nominal : ce qui a été vérifié (jobs de la nuit terminés, aucune erreur, appels externes sains), en 3 à 5 puces.
4. Si problèmes, par gravité décroissante : le constat (avec compte et horodatages), la **cause probable**, et la suite proposée (fichier du code concerné, correctif envisagé). Cite un `request_id` ou une ligne du journal comme preuve.
5. Ce que tu n'as **pas** pu vérifier (journal incomplet, période courte, secret masqué).

N'invente rien : une conclusion qui n'est pas dans le journal se présente comme une hypothèse. Ne recopie ni clé d'API ni contenu de transcript (le journal les masque, ne les cherche pas ailleurs).

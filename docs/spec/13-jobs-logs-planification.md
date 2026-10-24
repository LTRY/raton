---
title: "13 Jobs, logs et planification"
---
# 13 Jobs, logs et planification

## Download jobs

Les jobs sont stockes dans `download_jobs`.

Ils servent a afficher :

- progression courte ;
- erreurs ;
- historique logs (page `/logs`, voir [11 Interface HTML](11-interface-html.md), section Logs).

## Telechargement manuel

`POST /api/videos/import` (et son repli sans JavaScript `POST /videos/download`) :

1. valide `media_type` ;
2. cree un job `queued` ;
3. lance `run_manual_download_job` en background ;
4. repond `202` avec l'adresse du job (`/api`) ou redirige avec message
   (formulaire sans JavaScript).

`run_manual_download_job` :

1. passe job `running` ;
2. appelle `download_manual_media` ;
3. passe job `downloaded` ;
4. associe `video_id`.

## Import metadata chaine

`POST /channels/{id}/import-metadata` :

- cree un job `queued` ;
- lance `run_channel_metadata_import_job` ;
- importe la page demandee.

## Cloches de suivi quotidien

Comportement et vocabulaire : [02 Fonctionnalites](02-fonctionnalites.md),
section « Cloches de suivi quotidien », et glossaire. Cote jobs,
`POST /channels/{id}/auto-metadata` bascule la cloche du champ `section`
(`videos` par defaut, ou `shorts`) de l'utilisateur courant sans toucher
l'autre ; a l'activation, il cree un job `queued` puis lance
`run_channel_metadata_import_job(job.id, channel.id, page=1, section=<section>)`
en arriere-plan, qui ne marque rien Nouveau : seuls les scans automatiques
ulterieurs posent `is_new`.

## Import playlist (URL)

`POST /api/playlists/import-url` (repli sans JavaScript `POST /playlists/import-url`) :

1. resout l'URL synchronement via `extract_playlist_info` (sonde `yt-dlp`
   rapide, `extract_flat`) — si echec, message d'erreur immediat, aucun job
   cree ;
2. cree la `Playlist` (`source="url"`) tout de suite (pas d'etape separee
   comme pour l'ajout d'une chaine) ;
3. cree un job `queued` ;
4. lance `run_playlist_url_import_job` en arriere-plan ;
5. repond `202 {playlist, job}`, ou redirige vers la playlist (repli).

`run_playlist_url_import_job` (`back/services/jobs/playlists.py`) :

1. passe le job `running` ;
2. parcourt toutes les pages de `list_playlist_entries` jusqu'a une page
   vide (plafond 40 pages) ;
3. pour chaque entree, appelle `import_video_metadata(...)` (sans `new_for` :
   rien n'est Nouveau)
   puis cree la ligne `playlist_items` correspondante si elle n'existe pas
   deja — **continue au-dela d'une video deja connue** (pas d'arret anticipe
   comme `scan_channel_section`, voir
   [07 YouTube et telechargements](07-youtube-et-telechargements.md)) ;
4. une erreur sur une video individuelle est loggee (`failed`) et n'interrompt
   pas le reste de l'import ; une video deja connue est rattachee sans requete
   YouTube, et une pause (`PAUSE_BETWEEN_IMPORTS`) separe deux vraies
   extractions ;
5. un `HTTP 429` (`RateLimitedError`) arrete l'import : le job passe `failed`
   avec le compte importe jusque-la (voir "Limites de debit YouTube" dans
   [07 YouTube et telechargements](07-youtube-et-telechargements.md)) ;
6. sinon passe le job `metadata` avec le compte final importe.

## Import playlist (CSV)

`POST /api/playlists/import-csv` (repli sans JavaScript `POST /playlists/import-csv`) :

1. parse le fichier synchronement via `parse_playlist_csv` (pas de reseau,
   rapide) — si le CSV est illisible ou vide, message d'erreur immediat,
   aucun job cree ;
2. cree la `Playlist` (`source="csv"`, titre deduit du nom de fichier ou
   fourni par l'utilisateur) tout de suite ;
3. cree un job `queued` ;
4. lance `run_playlist_csv_import_job` avec les lignes deja parsees ;
5. repond `202 {playlist, job}`, ou redirige vers la playlist (repli).

**Pas d'etape de previsualisation/confirmation**, contrairement a l'import CSV
des abonnements de chaine (`POST /channels/import-csv` puis
`/confirm`, voir [12 API et routes](12-api-et-routes.md)) : chaque ligne du
CSV playlist est une inclusion inconditionnelle, il n'y a pas de choix
utilisateur ligne par ligne a faire avant de lancer l'import.

`run_playlist_csv_import_job` (`back/services/jobs/playlists.py`) :

1. passe le job `running` ;
2. pour chaque ligne, appelle `import_video_metadata(...)` (rien n'est
   Nouveau) puis
   cree la ligne `playlist_items` (`position` = ordre du CSV, `added_at` =
   horodatage de la ligne) ;
3. une video introuvable/privee depuis l'export (ligne obsolete) est loggee
   `warning` et n'interrompt pas le reste de l'import ;
4. mêmes regles de debit que l'import par URL : video deja connue rattachee
   sans requete, pause entre deux extractions, arret au premier `HTTP 429`
   (job `failed` avec le compte importe) ;
5. sinon passe le job `metadata` avec le compte final importe.

## Scan automatique

Le scheduler APScheduler (`back/services/jobs/scheduler.py`) demarre reellement au
lifespan FastAPI (`back/main.py:lifespan`, appel a `start_scheduler()` juste
apres `ensure_default_settings`, `stop_scheduler()` a l'arret) et enregistre
un job cron quotidien a `DAILY_SCAN_HOUR` (3h, timezone
`Europe/Paris`). Un declenchement a la demande (`POST /api/scan`) et un
rattrapage au demarrage existent en plus du cron (voir ci-dessous).

`scheduled_scan()` :

- ouvre une session ;
- appelle `run_scan(enforce_storage_headroom=True)` ;
- enregistre le resultat via `record_scan_result(db, result)` (voir "Dernier
  scan automatique" ci-dessous), quel que soit le status retourne
  (`completed`, `storage_low`, `rate_limited`, `already_running`).

`run_scan()` :

- evite les scans concurrents avec lock ;
- si stockage trop plein, log `skipped` ;
- parcourt les chaines de la moins recemment scannee a la plus recente
  (`channels.last_scanned_at`, jamais scannees d'abord) : un scan coupe par un
  429 reprend ainsi la ou il s'est arrete au lieu de toujours oublier les
  memes chaines ;
- scanne uniquement les chaines ou au moins un utilisateur a une cloche
  active : l'onglet videos si l'`auto_metadata_enabled` d'un utilisateur est
  vrai, l'onglet shorts si l'`auto_shorts_enabled` d'un utilisateur est vrai,
  avec `new_for` = ces utilisateurs (`channel_followers`) : les fiches
  importees sont Nouveau (`user_videos.is_new = true`) pour eux seuls ;
- borne sa charge (plafond de fiches par onglet, pauses, arret au premier
  `HTTP 429` : log `warning`, status `rate_limited`, chaines restantes reprises
  le lendemain) — voir "Limites de debit YouTube" dans
  [07 YouTube et telechargements](07-youtube-et-telechargements.md) ;
- nettoie le stockage ;
- retourne status, downloaded, deleted.

## Scan a la demande et evenements

`/settings` (carte "Suivi automatique") porte un bouton "Lancer le scan
maintenant" : `POST /api/scan` (`start_manual_scan` puis `run_manual_scan_job`,
`back/services/jobs/scheduler.py`) lance `scheduled_scan` en tache de fond,
donc avec le meme verrou, la meme garde de stockage et la meme mise a jour de
"Dernier scan automatique" que le cron.

Le scan (planifie ou manuel) publie ce qu'il fait dans un flux en memoire,
`back/services/ingest/scan_events.py` : debut (nombre de chaines), chaine en cours,
nouveautes trouvees et plafond atteint, chaque fiche importee, chaque echec,
"rien de nouveau", interruption par un 429, garde de stockage, fin avec le
total et la duree. Le dernier evenement d'un scan porte `final = true`.
La page parametres lit `GET /api/scan/events` toutes les 1,5 s et affiche
chaque evenement en notification (toast, rouge pour un echec) jusqu'a
l'evenement final ; elle suit aussi un scan deja en cours a son ouverture. Le
flux est volatil (500 evenements, perdu au redemarrage) : la trace durable
reste dans `download_jobs` (page Logs) et dans les cles "Dernier scan".

## Rattrapage au demarrage

Un `CronTrigger` fixe ne rattrape pas les declenchements manques : si
l'application (ou la VM Docker) n'est pas en cours d'execution a 3h pile, le scan
de ce jour-la est perdu silencieusement. Pour limiter ce risque,
`start_scheduler()` verifie au demarrage, via
`scan_is_overdue(get_last_auto_scan_info(db)["at"])`, si le dernier scan
enregistre date de plus de 24h (ou n'existe pas) ; si oui, un job unique
(`scan_channels_catchup`, sans trigger — execute une seule fois, des que
possible, sur le thread de fond d'APScheduler, sans bloquer le demarrage de
FastAPI) est ajoute en plus du cron quotidien normal.

## Journal applicatif

`docker compose logs` ne suffit pas : le conteneur est recree a chaque
deploiement et l'historique disparait. L'application ecrit donc aussi un
**journal applicatif** (`back/core/logging.py`, `configure_app_logging`, appele au
lifespan) dans `LOG_DIR/app.jsonl`, sur le volume
`${LOG_HOST_DIR:-./.local/logs}` (voir
[04 Configuration et deploiement](04-configuration-et-deploiement.md)).
Rotation a minuit, 7 jours conserves (`app.jsonl.AAAA-MM-JJ`). Si le dossier est
inutilisable, l'application demarre quand meme avec stderr seul.

Une ligne = un objet JSON : `ts` (ISO avec fuseau), `level`, `logger`, `msg`,
`request_id` (si la ligne est ecrite pendant une requete), `event` et les champs
propres a l'evenement. Les memes lignes vont aussi sur stderr, en texte lisible.
Les loggers `raton.*` et `app.*` sont tous deux captes (la plupart des
modules utilisent `getLogger(__name__)`), ainsi que les erreurs de `uvicorn.error` et
`apscheduler`.

Evenements :

| `event` | Niveau | Quand | Champs |
|---|---|---|---|
| `app.started` / `app.stopping` | INFO | demarrage / arret | |
| `request` | INFO (WARNING si lente) | chaque requete (sauf miniatures et statiques, sauf si >= 400 ou lentes) | `method`, `path`, `status`, `duration_ms`, `sql_count`, `sql_ms` |
| `request.error` | ERROR | exception non geree d'une route | `method`, `path`, `error`, `exc` (trace) |
| `job.start` / `job.end` | INFO | tout job de fond ou planifie (`logged_job`) | `job`, `job_id`/`channel_id`/`video_id`/`playlist_id`, `duration_ms`, `result` |
| `job.error` | ERROR | un job leve | idem + `error`, `exc` |
| `job.record` | INFO / WARNING / ERROR | chaque ligne ecrite dans `download_jobs` (page Logs), selon son statut | `status`, `message`, `channel_id`, `video_id` |
| `ext.call` / `ext.error` | INFO / ERROR | appel yt-dlp, Voyage, Anthropic (duree, tokens) ; un 429 YouTube ou une video pas encore disponible est WARNING | `service`, `op`, `duration_ms`, `error` |
| `scheduler.started`, `scheduler.catchup_check`, `scheduler.disabled`, `scheduler.stopped` | INFO | cycle de vie du scheduler | |
| `setting.set` | INFO | ecriture d'un reglage | `key` (jamais la valeur) |
| `channel.bell` | INFO | changement d'une cloche (formulaire ou `/api`) | `channel_id`, `section`, `enabled` |

Garde-fous :

- les cles d'API et jetons sont masques (`redact`) dans le message, les champs et
  les traces ; les transcripts et le texte des questions au LLM ne sont jamais
  journalises (tailles et compteurs seulement) ;
- `X-Request-ID` est renvoye dans chaque reponse, pour retrouver ses lignes ;
- un job attendu (scan 3h, purge 4h, notes 5h) sans `job.start` ce jour-la
  signale un scheduler qui n'a pas tourne.

### Revue des 24 dernieres heures

Le journal des dernieres heures se resume avec `back/core/logs_digest.py` : il conclut « nominal » ou liste les problemes par gravite, avec leur cause probable, en lecture seule.

Elle s'appuie sur `back/core/logs_digest.py` (bibliotheque standard seule),
lance par `python -m app.core.logs_digest --dir <LOG_DIR> --hours 24`. Le
digest lit `app.jsonl` et les fichiers tournes, garde la fenetre demandee et
sort un resume Markdown : lignes par niveau, redemarrages (`app.started`),
erreurs et avertissements groupes par signature (les nombres sont
neutralises), reponses 5xx, requetes les plus lentes, jobs
(demarres/termines/en erreur) et appels externes. Il leve un **signal** pour : une
erreur, une reponse 5xx, plusieurs demarrages de l'application, une ligne
`failed` de la page Logs, un job planifie attendu (`scheduled_scan`,
`scheduled_media_purge`, `scheduled_auto_notes`) sans `job.start` sur 24 h, un
job demarre depuis plus de 30 minutes sans `job.end` ni `job.error`. Sans
signal, la periode est un fonctionnement nominal.

Verification : `tests/test_app_logging.py`, `tests/test_logs_digest.py`.

## Revue quotidienne des journaux

Le conteneur `raton-ops` (voir [04 Configuration et deploiement](04-configuration-et-deploiement.md),
« Docker Compose ») lance chaque jour la revue des 24 dernieres heures, sans
intervention. Ce n'est pas un job de `api` : le scheduler APScheduler du back
n'y participe pas, et le journal est lu en lecture seule.

- **Planification** : un fil de `scripts/ops_review.py` verifie l'heure toutes les 30 s
  et lance la revue des qu'il est `OPS_REVIEW_HOUR` (8 par defaut, fuseau `TZ`,
  Europe/Paris par defaut) et qu'aucune revue planifiee n'existe pour la date
  du jour. Comme il regarde l'horloge au lieu de dormir jusqu'a 8 h, il rattrape
  une machine endormie a 8 h ou un conteneur relance plus tard dans la journee.
  Un echec compte comme la revue du jour : pas de nouvel essai en boucle.
- **Execution** : `claude --bare -p "/review-logs 24"` dans le depot, donc le
  skill `review-logs` (`.claude/skills/review-logs/`) sans copie de ses
  consignes. `--bare` ignore les hooks du depot et n'accepte que
  `ANTHROPIC_API_KEY` ; le skill lit le journal dans `LOG_DIR`. Les outils sont
  limites a la lecture (`Read`, le digest, `jq`, `grep`, `ls`, `head`, `tail`,
  `docker ps`/`docker compose logs`) ; `--max-budget-usd` plafonne une revue
  (`OPS_REVIEW_MAX_USD`, 1 $ par defaut) et `OPS_REVIEW_MODEL` choisit le modele
  (`sonnet` par defaut).
- **Cout** : l'appel est facture au token sur la cle API, en plus de
  l'abonnement Claude. Le cout de chaque revue (`total_cost_usd` du CLI) est
  stocke avec elle et affiche sur la page des previews : cout de la derniere
  revue et total des 30 derniers jours.
- **Resultat** : un fichier JSON par revue dans `.local/ops/reviews/` (date,
  declencheur, cout, duree, verdict). La carte **Revue des journaux** de la page
  des previews affiche le verdict de la derniere, les sept dernieres (lien vers
  le texte complet, `/reviews/<id>`) et le bouton **Analyser maintenant**
  (revue manuelle, sans effet sur la revue planifiee du jour). Une cle API
  absente ou un CLI qui echoue est enregistre comme une revue en echec, avec la
  raison.

Verification : `tests/test_ops_review.py`.

## Nombre de vues des videos

`run_view_count_backfill_job` (`back/services/jobs/backfills.py`) copie le
`view_count` et la `duration` de `metadata.json` dans `videos.view_count` et
`videos.duration_seconds` pour les videos qui ont un fichier de metadonnees et
n'ont pas encore l'une des deux valeurs. Il est lance une fois
au demarrage par `start_scheduler()` (job `backfill_view_counts`, sans
trigger) ; sans video en attente, il ne fait rien.

## Miniatures des videos

`run_thumbnail_backfill_job` (`back/services/jobs/backfills.py`) cree les
copies reduites de vignette (`thumbs/320.jpg`, `thumbs/640.jpg`) des videos
qui n'en ont pas encore. Il est lance une fois au demarrage par
`start_scheduler()` (job `backfill_thumbnails`, sans trigger), en arriere-plan
(environ 0,1 s par video) ; sans video en attente, il ne fait rien. Un echec
ffmpeg est journalise et la page sert la vignette d'origine.

## Profil des chaines

`run_channel_profile_backfill_job` (`back/services/jobs/backfills.py`) recupere
le profil de chaque chaine dont `metadata_fetched_at` est `NULL` (et qui a un
`yt_channel_id`), une a la fois, avec 2 s de pause entre deux chaines pour ne
pas marteler YouTube. C'est le point d'entree unique : il est lance en
arriere-plan apres `POST /channels`, l'import CSV confirme, `POST /api/channels`
et l'ajout d'une chaine par le chat bibliotheque (une fois le job de chat
termine, pour ne pas retarder la reponse), et une fois au demarrage par
`start_scheduler()` (job `backfill_channel_profiles`, sans trigger) pour les
chaines ajoutees pendant un arret ou avant l'existence des profils. Sans chaine
en attente, il ne fait rien.

Un seul passage a la fois : un verrou de module est pris sans attente, et un
appel fait pendant qu'un passage tourne retourne aussitot. Le passage en cours
relit les chaines en attente apres chaque tour, donc reprend celles ajoutees
entre-temps ; une chaine dont la recuperation echoue n'est tentee qu'une fois
par passage (elle sera reprise au passage suivant). Chaque chaine est isolee :
une exception (ex. chaine supprimee pendant le telechargement) est journalisee,
la session est annulee (`rollback`) et le passage continue. Cote chat
bibliotheque, le rattrapage est lance apres le commit du job de chat, hors du
`try/finally` : il ne tourne pas si le job a leve, et une erreur du rattrapage
est journalisee sans se propager.

`run_channel_profile_refresh_job(channel_id)` traite une seule chaine, quelle
que soit la valeur de `metadata_fetched_at` (bouton `↻`). Les deux passent par
`refresh_channel_profile` et journalisent via `log_job` : `failed` si
l'extraction echoue (la chaine reste en attente et sera reprise au prochain
demarrage ou ajout), `warning` si seule une image n'a pas pu etre enregistree.

## Purge du stockage media

Une seconde tache quotidienne (`purge_media`, `scheduled_media_purge`)
tourne a 4h `Europe/Paris` et appelle `purge_watched_media` (regles dans
[06 Stockage fichiers](06-stockage-fichiers.md)). A chaque execution, la cle
`app_settings` `last_media_cache_cleanup_at` recoit l'horodatage ISO.

Meme rattrapage au demarrage que le scan : si cette cle date de plus de 24h (ou
n'existe pas), un job unique (`purge_media_catchup`) est ajoute.

## Notes automatiques (lot nocturne)

Une troisieme tache quotidienne (`auto_notes_sweep`, `scheduled_auto_notes`)
tourne a 5h `Europe/Paris`, apres le scan de 3h (qui importe les videos
de la nuit) et la purge de 4h. Elle appelle `run_auto_notes_sweep`
(`back/services/rag/auto_notes.py`), qui fait deux choses, dans cet ordre :

1. **collecter** le lot soumis par le passage precedent, s'il y en a un : les
   resultats sont appliques un par un (`transcript.notes.txt`,
   `transcript.summary_short.txt`, embeddings), puis le lot est oublie ;
2. **soumettre** un nouveau lot d'au plus 100 videos eligibles.

Le travail se fait cote Anthropic (Message Batches, moitie prix, quelques
heures au plus) : un redemarrage de l'application ne perd rien, le resultat est
recupere au passage suivant. Un seul lot a la fois ; tant qu'il n'est pas
termine le passage ne fait rien (`lot en cours`). Un lot sans reponse depuis
plus de 36 h est abandonne et ses videos reessayees.

- **Eligibilite** : un transcript lisible d'au moins 500 caracteres, pas de
  `transcript.notes.txt`, pas un short (`/shorts/` dans l'URL), aucun label
  exclu (les labels de la video, ou a defaut ceux de sa chaine), pas deja dans
  un lot, et moins de 3 echecs. Les plus recentes d'abord ; un transcript trop
  long pour la sortie est donc reessaye au plus 3 fois.
- **Reglages** (`/settings`, section "Notes automatiques") :
  `auto_notes_enabled` (defaut `true`) et
  `auto_notes_excluded_category_labels` (defaut `cuisine, amv, musique, sport,
  entertainment`). Les cles `auto_notes_last_run_at` /
  `auto_notes_last_run_summary` gardent le dernier passage ; `auto_notes_batch_id`
  et `auto_notes_batch_submitted_at` le lot en cours.
- **Suivi** : un `llm_jobs` `kind="auto_notes"` par video, `running` tant que le
  lot est en cours puis `applied` ou `failed`, avec les tokens et le cout reels
  (moitie prix). Le prompt n'est pas stocke (le transcript est dans le lot).
  Visible dans « Couts LLM ».
- **Garde-fous** : un lot entierement en echec fait sauter la soumission de la
  nuit suivante (puis le passage reprend) ; sans cle Anthropic, ou desactive,
  le passage ne fait rien. Rien n'est jamais regenere ni retire de l'index :
  une video qui a deja des notes est ignoree, et un label exclu ajoute apres
  coup ne supprime pas ses chunks.
- **Rattrapage** : meme principe que le scan, une cle `auto_notes_last_run_at`
  de plus de 24 h (ou absente) ajoute un job unique `auto_notes_sweep_catchup`
  au demarrage. A chaque passage, `backfill_note_chunks` et
  `backfill_summary_chunks` indexent aussi les notes ecrites sans embedding.

## Dernier scan automatique

Trois cles `app_settings` (voir
[05 Modele de donnees](05-modele-de-donnees.md)) suivent l'etat du dernier
scan planifie, mises a jour par `record_scan_result` a chaque execution de
`scheduled_scan()` (cron ou rattrapage) :

- `last_auto_scan_at` : horodatage ISO de la derniere execution ;
- `last_auto_scan_status` : le `status` retourne par `run_scan()`
  (`completed`, `storage_low`, `rate_limited`, `already_running`) ;
- `last_auto_scan_imported_count` : nombre de fiches importees lors de cette
  execution.

`get_last_auto_scan_info(db)` relit ces trois cles. Affiche en lecture seule
sur `/settings` (section "Suivi automatique", voir
[11 Interface HTML](11-interface-html.md)) : date du dernier scan, nombre de
fiches importees si `completed`, ou message explicite si `rate_limited`
(YouTube a limite les requetes, le reste est repris au scan suivant),
`storage_low`
(garde de stockage bas, voir ci-dessous) ou `failed`.

## Stockage bas

Un scan planifie ne doit pas demarrer les imports si moins de 20% du quota
global est libre (`has_auto_download_headroom`). Cette garde s'applique au
scan entier (toutes les chaines a la fois), meme si le scan lui-meme
n'importe que des metadonnees/miniatures/sous-titres — jamais de
video/audio complet (le telechargement complet est une action separee,
`download_manual_media`, jamais appelee depuis le scan planifie).

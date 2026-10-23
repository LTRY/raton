---
title: "07 YouTube et telechargements"
---
# 07 YouTube et telechargements

## Extraction chaine

Pour ajouter une chaine :

- utiliser `yt-dlp` avec `skip_download` et `extract_flat` ;
- extraire `channel`, `uploader`, `title` ou l'URL comme nom ;
- extraire `channel_id`, `uploader_id` ou `id` comme identifiant.

`back/services/youtube/channel_info.py:extract_channel_info` n'accepte qu'une reference a une
chaine precise : URL, `@handle`, ou mot seul traite comme un handle. Un nom
libre (avec espaces) leve `ChannelNotFoundError` : il n'est jamais resolu en
devinant, il passe par la recherche ci-dessous.

## Profil de chaine

`back/services/youtube/channel_info.py:fetch_channel_profile(channel_url)` refait la meme
extraction plate (`extract_flat`, `skip_download`) que l'ajout et en tire
`description`, `keywords` (les `tags` de yt-dlp, vides ecartes) et les URL
d'image : les entrees `avatar_uncropped` et `banner_uncropped` de
`thumbnails` (les originaux, pas les recadrages numerotes).

`back/services/channels/profile.py:refresh_channel_profile` enregistre le texte,
puis telecharge chaque image vers `_channels/<yt_channel_id>/` (voir
[06 Stockage fichiers](06-stockage-fichiers.md)) : ecriture dans un fichier
temporaire `.part` au nom unique a chaque ecriture (un rafraichissement manuel
concurrent d'un rattrapage ne partage donc pas de fichier ; supprime si
l'ecriture echoue) puis `os.replace`, taille limitee a 10 Mo, types `jpeg`/`png`/`webp`/
`gif` acceptes, ancien fichier d'une autre extension supprime. L'echec d'une
image n'est pas bloquant : le texte est conserve, un `warning` est journalise
et le bouton de rafraichissement permet de reessayer. Si l'extraction elle-meme
echoue, un job `failed` est journalise et la chaine reste en attente
(`metadata_fetched_at` reste `NULL`). La racine media du reglage est traduite
par `local_media_path` (voir [04 Configuration](04-configuration-et-deploiement.md))
pour toutes les lectures/ecritures de fichiers ; le chemin stocke dans la DB reste
relatif.

## Recherche de chaine

`back/services/youtube/channel_info.py:search_channels(query, limit=8)` cherche des chaines par
nom, sans cle d'API : `yt-dlp` (`extract_flat`) lit la page de resultats
YouTube `results?search_query=...` avec le filtre "Type : chaine"
(`sp=EgIQAg%3D%3D`). Les candidates sont renvoyees dans l'ordre de pertinence
de YouTube, chacune avec `yt_channel_id`, `name`, `handle`, `url`
(`https://www.youtube.com/@handle`, ou `/channel/<id>` sans handle),
`subscriber_count`, `description` et `thumbnail_url` (avatar servi par
YouTube). Les entrees dont l'identifiant ne commence pas par `UC` (pas une
chaine) sont ignorees.

Une meme chaine est joignable par plusieurs URL : la detection de doublon
(`back/services/channels/lookup.py:find_channel`) compare donc d'abord
`yt_channel_id`, puis l'URL.

## Listing de chaine

La page `/videos?channel_id=...&page=N` doit :

- compter les entrees si possible ;
- charger seulement la fenetre demandee ;
- utiliser une taille de page de 25 ;
- calculer `playliststart` et `playlistend` ;
- afficher page courante et total si disponible.

## Import metadata

L'import metadata :

- ne telecharge pas le media ;
- extrait les infos completes de la video (une seule extraction : les
  sous-titres et la miniature sont ecrits depuis ces memes infos, via
  `info=` de `download_subtitles`/`download_thumbnail`, sans recharger la page
  YouTube) ;
- fusionne les infos plates de listing avec les infos detaillees ;
- ecrit `metadata.json` ;
- tente de telecharger les sous-titres ;
- ecrit `transcript.txt` si possible ;
- cree un `Video` avec `media_type = metadata`, `download_source = auto` ou
  `manual`.

## Limites de debit YouTube (HTTP 429)

YouTube repond `HTTP Error 429` quand `yt-dlp` le sollicite en rafale. Le scan
de chaine
(`scan_channel_section`, voir [13 Jobs, logs et planification](13-jobs-logs-planification.md))
borne donc sa charge :

- **plafond par section et par passage** : le scan planifie importe au plus
  `MAX_IMPORTS_PER_SECTION` (10) videos par onglet (videos, shorts) et par
  chaine ; l'import ponctuel (page de la chaine, activation de la cloche) n'a
  pas de plafond ;
- **ordre** : les fiches a importer sont d'abord listees (jusqu'a la premiere
  video connue, ou jusqu'a une page de shorts sans nouveaute), puis importees
  de la plus **ancienne** a la plus recente quand un plafond s'applique. Le
  reste est donc toujours plus recent que la premiere video connue et le scan
  suivant le retrouve ; importer la plus recente d'abord le laisserait derriere
  une video connue, definitivement ignore ;
- **pauses** : `PAUSE_BETWEEN_IMPORTS` (2 a 5 s, tirage aleatoire) entre deux
  imports, `PAUSE_BETWEEN_CHANNELS` (10 a 30 s) entre deux chaines du scan
  planifie quand la precedente a importe quelque chose,
  `PAUSE_AFTER_LISTING_ONLY` (1 a 3 s) quand elle n'a demande qu'un listing ;
- **arret au premier 429** : `is_rate_limit_error` reconnait l'erreur dans le
  listing, l'extraction et la miniature ; `import_video_metadata` leve alors
  `RateLimitedError` (la video n'est pas creee) et le scan s'arrete au lieu de
  continuer a frapper. Les chaines non atteintes passent en premier au scan du
  lendemain (`channels.last_scanned_at`). Un 429 sur les **sous-titres** ne
  l'arrete pas (voir ci-dessous).

### Sous-titres : jamais de traduction automatique

Les sous-titres sont la seule requete que YouTube refuse en continu, et
seulement pour les pistes **traduites automatiquement** (`tlang=`, par exemple
`en` sur une video francaise) ; les sous-titres de createur et les sous-titres
automatiques en langue originale (`<langue>-orig`) passent. Ce n'est donc pas
un quota de debit : les pauses n'y changent rien, et une traduction serait de
toute facon moins fidele que l'original.

`choose_subtitle_track(info)` choisit **une seule piste**, dans cet ordre :
sous-titres de createur en `fr`/`en`, sous-titres automatiques originaux
`fr-orig`/`en-orig`, puis sous-titres de createur ou piste originale dans
n'importe quelle langue (une video arabe donne `ar-orig`). Aucune piste ne
convient (video sans parole, seulement des traductions) : aucune requete, le
transcript reste `missing`. `download_subtitles` l'applique quand aucune langue
n'est imposee. Le formulaire de telechargement manuel (feuille d'import) n'en
impose plus (ni langue ni source) ; une langue passee explicitement a
`POST /videos/download` reste respectee telle quelle.

Un echec de sous-titres n'est qu'un `warning` : la fiche est importee sans
transcript et le scan continue.

**Rattrapage ponctuel** (`back/services/ingest/transcript_backfill.py`, job de
demarrage `backfill_original_transcripts`) : les videos `missing` dont
`metadata.json` liste une piste exploitable recuperent leur transcript (aucune
requete pour les autres). Il s'arrete apres 5 echecs consecutifs et n'est
marque fait (`original_transcript_backfill_done`) que s'il est alle au bout.

L'import d'une page (« Explorer la suite », premiere synchro de la cloche) ne
s'arrete pas non plus a la premiere video connue (`skip_known`) : la page
demandee peut commencer par des fiches deja importees (cloche, import par URL),
et s'y arreter n'importerait rien.

Les shorts ne s'arretent pas a la premiere video connue (leur URL `/watch` est
reparee en `/shorts/`) : le listing s'arrete des qu'une page ne contient aucun
short inconnu, au lieu de relire les 3 pages chaque nuit.

L'import de playlist (URL ou CSV) applique les pauses entre imports et l'arret
au premier 429, mais **pas de plafond** : importer toute la playlist est
justement la demande. Une video deja connue est rattachee a la playlist sans
aucune requete YouTube (et sans pause), si bien que relancer un import
interrompu par un 429 reprend aux videos restantes. Le job passe alors
`failed` avec le nombre de videos importees.

## Premieres et directs programmes

Une premiere ou un direct programme est liste par la chaine avant d'exister :
`yt-dlp` repond `Premieres in 3 hours` (ou `This live event will begin in`).
Ce n'est pas un echec : le scan (`is_not_yet_available_error`) ecrit un log
`scheduled` (« programmee et pas encore disponible », badge neutre, hors
erreurs et avertissements), emet une notification
normale, ne cree pas la fiche, et la reprend au scan suivant, une fois sortie.

## Extraction et import playlist

Une playlist se remplit de deux facons, toutes deux **metadonnees seules**
(aucun telechargement media declenche automatiquement) et **instantanees**
(pas de re-synchronisation periodique, contrairement a la cloche des
chaines) :

- **Import par URL** (`back/services/playlists/imports.py:extract_playlist_info`,
  `list_playlist_entries`) : `yt-dlp` avec `skip_download`/`extract_flat`,
  directement sur l'URL de playlist (pas de reecriture d'URL "section" comme
  pour une chaine, l'URL de playlist est deja la ressource de listing) ;
  `playliststart`/`playlistend` paginent la lecture (fenetre de 50), la tache
  de fond parcourt toutes les pages jusqu'a une page vide (plafonne a 40
  pages/2000 videos).
- **Apercu avant import** (`back/services/playlists/imports.py:preview_playlist`) :
  meme lecture `extract_flat`, sans `playlistend: 1`, plafonnee a
  40 x 50 entrees (`truncated` si le plafond est atteint). Calcule nombre de
  videos, entrees indisponibles (`[Private video]`, `[Deleted video]`), duree
  cumulee des entrees qui en ont une, videos deja connues par `yt_video_id`
  et premiers titres. Ne cree ni playlist ni video.
- **Import CSV Google Takeout** (`back/services/playlists/imports.py:parse_playlist_csv`) :
  un fichier `Vidéos de <Titre>.csv` par playlist (deux colonnes : identifiant
  video, horodatage ISO8601 d'ajout a la playlist). Le parsing est
  **positionnel, pas base sur le nom des colonnes** — l'entete est
  systematiquement ignoree plutot que verifiee, car son libelle depend de la
  langue du compte Google exporte. Un seul fichier a la fois (le
  `playlists.csv` global du Takeout, qui donne le vrai `PLxxxx` par playlist,
  n'est pas exploite).

Dans tous les cas, chaque video rencontree est importee via la meme fonction
`import_video_metadata` que l'import de chaine (voir "Import metadata"
ci-dessus), avec `is_new=False` (une playlist ne doit jamais alimenter la
section "Nouveautes" du dashboard, reservee au scan planifie de la cloche des
chaines) — puis rattachee a la playlist via une ligne `playlist_items`
(`position` = ordre de la playlist ou du CSV, `added_at` = timestamp du CSV
le cas echeant). Contrairement au scan de chaine
(`scan_channel_section`, qui s'arrete des la premiere video deja connue en
supposant un flux "plus recent d'abord" sans trou), l'import de playlist
**continue au-dela d'une video deja connue** : une playlist melange videos
anciennes et recentes dans un ordre arbitraire, s'arreter au premier doublon
sauterait a tort des videos valides plus loin dans la liste.

Les options `noplaylist = True` du telechargement media (ci-dessous) sont
sans rapport : l'import de playlist n'appelle jamais `download_media`.

## Telechargement video

Format yt-dlp (`{quality}` vaut `360`/`480`/`720`/`1080`/`1440`/`2160`, ou
absent pour `best`) :

```text
bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best
```

La qualite est choisie par l'utilisateur (defaut `1080p`) :

- sur le formulaire de telechargement manuel par URL (feuille d'import, segment
  "Qualite video") ;
- sur le formulaire "Telecharger video" de la page detail d'une video non
  encore telechargee (`/videos/{id}`, select "Qualite") ;
- sur le bouton Video de la barre d'actions de la page detail : un popover
  ephemere liste les qualites, se ferme sans rien lancer si on clique ailleurs
  ou `Échap`, et lance le telechargement avec la qualite choisie sinon.

Contraintes :

- `noplaylist = True`
- `writethumbnail = True`
- `writeinfojson = True`
- `restrictfilenames = True`

## Telechargement audio

Format yt-dlp :

```text
bestaudio[ext=m4a]/bestaudio/best
```

Postprocessor :

- `FFmpegExtractAudio`
- codec `m4a` (AAC, lisible par Safari) : une source deja en m4a est remuxee,
  sans reencodage ; il n'y a plus de conversion MP3. Les `.mp3` deja stockes
  restent lus tels quels.

### Audio d'une video deja telechargee

Quand l'utilisateur demande l'audio d'une video dont `video_path` existe,
Raton copie la piste audio du fichier video (`ffmpeg -vn -c:a copy`,
`back/services/media/audio_extract.py`) au lieu d'appeler yt-dlp : ni reseau, ni
reencodage, le `.m4a` est ecrit en quelques secondes dans le dossier de la
video (staging puis fusion, comme tout ajout de format).

L'extraction n'a lieu que si la piste n'est pas de moindre qualite qu'un
telechargement audio dedie. Elle est faite quand le `metadata.json` de la
video indique (`requested_formats`) que le fichier a ete fusionne avec un
flux audio AAC separe (`vcodec` `none`, `acodec` `mp4a.*`), c'est-a-dire le
meme flux que `bestaudio[ext=m4a]`. Une video issue d'un format progressif de
repli (piste audio de plus faible debit) n'est **pas** extraite.

Dans tous les autres cas (pas de `video_path`, fichier ou `metadata.json`
absent ou illisible, piste de moindre qualite, `audio_path` deja present,
echec de ffmpeg), le telechargement passe par yt-dlp comme ci-dessus ; un
echec d'extraction n'est jamais une erreur pour l'utilisateur. La video est
retrouvee par son `url` (sans appel reseau) ; une URL inconnue suit le flux
yt-dlp habituel.

La qualite video choisie par l'utilisateur (`360p` a `2160p`) ne concerne que
le telechargement de la video ; l'audio extrait est celui du fichier tel que
telecharge.

## Ajout audio/video sur fiche existante

Regles :

- si l'utilisateur demande video et `video_path` existe deja : erreur
  `La video a deja ete telechargee.`
- si l'utilisateur demande audio et `audio_path` existe deja : erreur
  `L'audio a deja ete telecharge.`
- si l'autre format existe, il doit etre preserve ;
- `metadata_path`, `thumbnail_path`, `transcript_path` peuvent etre mis a jour
  si le nouveau telechargement en produit ;
- `media_type` est recalcule avec priorite `video`, puis `audio`, puis
  `metadata`.

## Recuperation manuelle du transcript

Pour une video dont le transcript est `missing`/`failed` (sous-titres absents
ou indisponibles au moment du telechargement initial), la fiche video
(`/videos/{id}`) affiche un bouton "Recuperer la transcription" (visible
uniquement quand `video.transcript_path` est vide) :

- `POST /api/videos/{id}/transcript/download` cree un `DownloadJob` et lance
  `retry_transcript_download` (`back/services/ingest/transcript_retry.py`) en tache de fond ;
- une seule tentative, sur la piste choisie par `choose_subtitle_track`
  (createur fr/en, puis originale fr/en, puis originale dans une autre langue :
  voir "Sous-titres : jamais de traduction automatique") ; pas de fusion
  multi-langues ;
- si la video n'a aucune piste exploitable, le job echoue avec le message
  "Aucun sous-titre disponible pour cette video." ;
- les anciens fichiers de sous-titres (`.vtt`/`.srt`/`.json3`) deja presents
  dans le dossier final sont supprimes avant la fusion, pour eviter qu'un
  fichier au nom different (langue differente, titre modifie) ne s'accumule
  a cote du nouveau ;
- suit le meme pattern de polling que les autres telechargements manuels
  (`GET /api/jobs/{job_id}`).

## Jobs

Un telechargement manuel cree un `DownloadJob` :

- status initial `queued` ;
- background task ;
- status `running` pendant execution ;
- status `downloaded` au succes ;
- status `failed` avec message si exception.

Apres succes, le fichier telecharge doit etre visible dans la fiche locale.

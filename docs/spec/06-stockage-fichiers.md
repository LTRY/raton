---
title: "06 Stockage fichiers"
---
# 06 Stockage fichiers

## Racine media

La racine media par defaut est (modifiable via `MEDIA_HOST_ROOT`) :

```text
./.local/media/YouTube
```

Dans Docker Compose, l'application voit cette racine comme :

```text
/media/youtube
```

## Arborescence

Chaque video est stockee dans :

```text
<MEDIA_ROOT>/<channel_name>/<YYYY-MM-DD> - <video_title>/
```

Les fichiers locaux deposes sur la page d'import vont dans
`<MEDIA_ROOT>/Local/<YYYY-MM-DD> - <nom du fichier>/` (copie via un dossier de
staging frere, puis deplacement), rattaches a la chaine `Fichiers locaux`.

Les images de profil des chaines vivent a cote des dossiers de chaines, sous
une cle qui ne change jamais (l'identifiant YouTube, contrairement au nom) :

```text
<MEDIA_ROOT>/_channels/<yt_channel_id>/avatar.<ext>
<MEDIA_ROOT>/_channels/<yt_channel_id>/banner.<ext>
```

L'extension suit le type de l'image recue (`.jpg`, `.png`, `.webp`, `.gif`) ;
`channels.avatar_path`/`banner_path` stockent le chemin relatif a
`MEDIA_ROOT`. Le dossier est supprime avec la chaine (la suppression des
fichiers video, elle, reste decrite plus bas) et n'entre pas dans le quota, qui additionne `Video.file_size_bytes`.

Si la date de publication est inconnue, le nom doit rester stable et lisible.
Les noms doivent etre sanifies pour eviter les caracteres invalides.

## Fichiers attendus

Un dossier video peut contenir :

- fichier video : `.mp4`, `.mkv`, `.webm`, `.mov`, `.avi` ;
- fichier audio : `.m4a` (ecrit par Raton), `.mp3` (anciens telechargements), `.opus`, `.ogg`, `.wav`, `.flac` ;
- vignette : `.jpg`, `.jpeg`, `.png`, `.webp` ;
- metadonnees : `metadata.json` ;
- copies reduites de la vignette : `thumbs/320.jpg` et `thumbs/640.jpg`
  (JPEG, jamais agrandies), dans un sous-dossier pour que la decouverte des
  fichiers du dossier ne les prenne pas pour la vignette d'origine. Creees par
  `ensure_video_thumbnails` (`back/services/media/thumbnails.py`, ffmpeg) apres chaque
  telechargement ou import, et par un rattrapage au demarrage ; supprimees avec
  le dossier ;
- sous-titres sources : `.vtt`, `.srt`, `.json3` ;
- transcript : `transcript.txt` ;
- notes structurees : `transcript.notes.txt` ;
- resume court (3 lignes) : `transcript.summary_short.txt` ;
- historique chat : `transcript.chat.json`.

## Staging

Tout telechargement passe par un dossier staging sibling :

```text
.<folder-name>.download.<uuid>
```

Creation d'une nouvelle fiche :

1. telecharger/ecrire dans staging ;
2. calculer les chemins finaux ;
3. deplacer staging vers dossier final ;
4. commit DB ;
5. rollback supprime le dossier final si le commit echoue.

Import de metadonnees alors que le dossier final existe deja sans fiche
(chaine supprimee, fichiers conserves) : le dossier est reutilise sur place,
sans staging. Les medias (video, audio), sous-titres et miniature deja
presents sont conserves et rattaches a la nouvelle fiche ; seuls les
sous-titres ou la miniature manquants sont telecharges, et `metadata.json` /
`transcript.txt` sont reecrits. Le dossier n'est jamais supprime si l'import
echoue.

Suppression d'une fiche par la personne : la ligne est supprimee et commitee,
puis le dossier final est efface, seulement s'il est strictement a l'interieur
du dossier media (voir « Suppression d'une fiche » dans
[02 Fonctionnalites](02-fonctionnalites.md)).

Ajout d'un format sur fiche existante :

1. telecharger dans staging ;
2. merger les fichiers staging dans le dossier final ;
3. remplacer les fichiers de meme nom avec backup temporaire ;
4. commit DB ;
5. rollback restaure les fichiers remplaces.

## Taille disque

`Video.file_size_bytes` doit representer la taille du dossier final complet
apres operation, pas seulement le dernier fichier telecharge.

## Nettoyage

Il n'y a pas de nettoyage par quota ou par limite de chaine : le quota global
ne fait qu'arreter les telechargements automatiques quand il reste moins de 20 %
de marge (`back/services/media/storage.py:has_auto_download_headroom`). Les fichiers
ne sont supprimes que par la retention ci-dessous ou a la main.

### Retention des medias vus (purge)

Les fichiers audio/video du serveur sont soumis a une retention
(`purge_watched_media`, `back/services/media/media_storage.py`) :

- une video est « vue » quand la lecture atteint 90 % de la duree
  (`videos.watched_at`, voir [08 Medias et lecteurs](08-medias-et-lecteurs.md)) ;
- 7 jours apres `watched_at`, les fichiers sont supprimes ;
- `rating >= 4` archive la video : ses fichiers ne sont jamais supprimes. Une
  baisse de note a 3 ou moins ne change pas `watched_at` ; si la date a plus de
  7 jours, la purge a lieu au passage suivant ;
- les deux formats (`video_path` et `audio_path`) sont supprimes ensemble, des
  que l'un des deux a atteint 90 % ; la verification `is_relative_to(folder)`
  s'applique a chaque suppression ;
- la ligne `videos`, la miniature, `metadata.json`, le transcript, les
  sous-titres et les notes sont conserves ; `video_path`, `audio_path`,
  `media_type` et `file_size_bytes` sont mis a jour ;
- `watched_at` est remis a `NULL` quand un telechargement ajoute un format
  (un retelechargement relance le decompte de 7 jours) ;
- pas de retroactivite : une video sans `watched_at` n'est jamais purgee ;
- pas de retelechargement automatique : noter 4 ou 5 une video deja purgee ne
  retelecharge rien, le bouton « Retelecharger » (telechargement manuel) reste
  disponible ;
- chaque purge est journalisee dans `download_jobs` (`purged`, ou `failed` en cas
  d'erreur sur une video, sans interrompre les autres).

---
title: "17 Roadmap et limites connues"
---
# 17 Roadmap et limites connues

## Limites actuelles

- Pas d'authentification generale (voir [15 Securite](15-securite.md)).
- Lecteur video natif uniquement ; seul le mini-lecteur audio persistant a une
  interface de controle propre (voir [08 Medias et lecteurs](08-medias-et-lecteurs.md)).
- Pas de gestion fine multi-utilisateur.
- Pas de file de jobs persistante externe : jobs dans la DB + background tasks.
- Les telechargements longs dependent du processus web.
- Les cartes de liste ne montrent pas de lien vers YouTube ; les URL YouTube
  restent accessibles depuis les pages de chaine et de playlist.
- `media_type` reste un champ historique derive ; les chemins `video_path` et
  `audio_path` font autorite.
- Segments sponsorises : limites assumees (fondu audio sans effet sur iOS, pas
  de marqueurs sur la barre de progression, pas de vote ni d'envoi vers
  SponsorBlock, pas de backfill de masse, fondu non reglable) — detail dans
  [08 Medias et lecteurs](08-medias-et-lecteurs.md).

## Ameliorations possibles

- Worker dedie pour telechargements longs.
- Auth locale optionnelle sur toutes les pages.
- Page d'administration media plus detaillee.
- Recherche plein texte dans les transcripts (la recherche dans les notes est
  decrite dans [19](19-indexation-et-recherche-notes.md)).
- Resume/retry plus robuste des telechargements.
- Nettoyage configurable par type media.
- Export/import de configuration.
- Tests navigateur Playwright pour les players.
- Categories SponsorBlock additionnelles (`preview`, `filler`,
  `music_offtopic`, `poi_highlight`), hors perimetre a ce jour.

## Regle pour roadmap

Toute amelioration future doit etre decrite ici si elle n'est pas implementee
immediatement. Les fichiers de specification fonctionnelle ne doivent decrire
comme comportement garanti que ce qui est implemente et teste.

---
title: "00 Vision"
---
# 00 Vision

## Objectif produit

Raton est une application FastAPI locale qui permet de constituer un
catalogue personnel de contenus YouTube consultable depuis un navigateur.

L'application doit :

- gerer une liste de chaines YouTube ;
- importer les metadonnees des videos d'une chaine sans telecharger le media ;
- telecharger a la demande la video, l'audio (M4A), ou les deux, pour une meme
  video YouTube ;
- afficher localement les pages video sans renvoyer l'utilisateur vers YouTube ;
- afficher, copier et discuter le transcript d'une video, et en tirer
  des notes indexees ;
- signaler les nouveautes des chaines suivies (une cloche par chaine) ;
- chercher et discuter dans toute la bibliotheque (recherche par mots,
  recherche semantique dans les notes, chat) ;
- suivre le visionnage : position de lecture, notes, historique, temps d'ecran ;
- conserver un historique de jobs et d'erreurs.

## Principes non negociables

- L'application est locale/LAN-first : pas de service public expose a Internet,
  donc pas d'authentification generale tant qu'elle reste sur un LAN de
  confiance (voir `15-securite.md`).
- Une video YouTube doit etre representee par un seul enregistrement `Video`,
  meme si elle possede a la fois un fichier video et un fichier audio.
- Les fichiers media restent sur le disque hote dans une arborescence stable.
- Les lecteurs audio/video doivent fonctionner avec Safari desktop et iPhone.
  Les routes media doivent donc supporter les requetes HTTP `Range`.
- Les modifications de comportement doivent etre couvertes par des tests.

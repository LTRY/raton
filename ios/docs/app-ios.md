---
title: "L'app iOS"
---

# L'app iOS

L'app iOS est le code de `ios/` : une app native pour iPhone (Swift, SwiftUI),
cinquieme unite du depot apres `back/`, `front/`, `ops/` et `monitoring/`. Elle
est cliente de l'API JSON `/api`, comme le front, et ne decide rien : les regles
(ce qui est Nouveau, le Vu a 90 %, la purge...) restent dans le back. Un ecran
qui a besoin d'une valeur que l'API ne donne pas obtient un nouveau champ ou
endpoint calcule par un service de `back/services/`, jamais une copie de la
regle en Swift.

**Etat : migration quasi complete du front telephone.** Le projet se genere et se compile avec Xcode, et tourne
dans le simulateur iPhone (iOS 18) sur les donnees de demo (`make demo`). La
lecture d'un fichier audio (m4a), la reprise, le rapport `/activity` et la
lecture en arriere-plan y ont ete essayes ; la video, l'ecran verrouille et le
reseau local d'un iPhone reel ne l'ont pas ete.

## Construire et lancer

Sur un Mac avec Xcode et [XcodeGen](https://github.com/yonaskolb/XcodeGen) :

```bash
cd ios && xcodegen && open Raton.xcodeproj
```

`ios/project.yml` decrit le projet (cible iOS 16, `ios/Raton/` en sources) ;
`*.xcodeproj` n'est pas versionne. Choisir son equipe de signature dans Xcode
(Signing & Capabilities) pour installer l'app sur un iPhone.

## Un seul serveur : l'URL du front

L'app ne parle qu'a une URL, celle du front (par exemple
`http://192.168.1.20:8000`). Le front relaie tous les appels `/api/*` vers le
back (`front/proxy.py`), flux video et audio compris (`Range`). Raton reste sur
un LAN de confiance, en HTTP et sans authentification
(`docs/spec/15-securite.md`) : `URLSession` n'envoie ni `Origin` ni
`Sec-Fetch-Site`, donc le controle de meme origine du back laisse passer les
ecritures (`back/core/same_origin.py`).

L'utilisateur est nomme par l'en-tete `X-Raton-User` (son id), que
`RatonAPI.swift`, le jumeau Swift de `front/api.py`, envoie sur chaque appel.

`Info.plist` porte `NSAllowsLocalNetworking` et `NSAllowsArbitraryLoads`
(l'URL est saisie par l'utilisateur, ce peut etre un nom de domaine du LAN),
`NSLocalNetworkUsageDescription` en francais, et `UIBackgroundModes` = `audio`.

## Apparence

L'app reprend le style des pages du front, a partir de ses jetons
(`front/static/css/tailwind.input.css`, `@theme` et `:root`), copies dans
`ios/Raton/Theme.swift` : fond creme `#fbf6ee`, surfaces blanches, texte brun
`#2b2018`, terracotta `#c2410c` pour l'accent, police Plus Jakarta Sans
(`ios/Raton/Resources/PlusJakartaSans.ttf`, la police variable du front
convertie de woff2 en ttf, licence OFL), la mascotte `raccoon-empty.png`, la
barre d'onglets en pilule flottante, des boutons ronds blancs pour le retour,
des lignes de liste a vignette a gauche (duree, barre de progression),
etoiles ambre. Clair seulement (`UIUserInterfaceStyle` = `Light`). Un changement
de jeton cote front se reporte a la main dans `Theme.swift`.

## Ecrans

Cinq onglets, comme la barre du front : Accueil, Chaines, Bibliotheque, Playlists, Reglages.

| Ecran | Role | Appels |
| --- | --- | --- |
| Adresse du serveur (premier lancement, puis Reglages) | Saisie de l'URL, validee avant d'etre gardee dans `UserDefaults` | `GET /api/users` (200 attendu) |
| Choix de l'utilisateur | Liste des utilisateurs ; dans Reglages, creer (+) et supprimer (appui long) | `GET/POST /api/users`, `DELETE /api/users/{id}` |
| Accueil | Raton et sa ligne de la visite, le bouton vers les Nouveautes ou l'Historique, la barre de discussion ; menu : Nouveautes, Historique, Recherche | `POST /api/raton/visit`, `/static/img/raton/<art>` |
| Discussion | Discussion avec la bibliotheque : les reponses citent des fiches (toucher ouvre la fiche), choix, nouvelle et suppression de discussion | `GET/POST /api/chat`, `GET/DELETE /api/chat/conversations/{id}`, `GET /api/llm-jobs/{id}` |
| Nouveautes | Les fiches Nouvelles, une pile par chaine, dix chaines par page ; tirer pour rafraichir ; bouton Historique | `GET /api/nouveautes?page=N`, `GET /api/videos/{id}/thumbnail` |
| Historique | Ce qui a ete lu, par jour | `GET /api/historique?page=N` |
| Recherche | Videos et chaines YouTube ; importer une video (video ou audio) ou ajouter une chaine | `GET /api/youtube/videos\|channels`, `POST /api/videos/import`, `POST /api/channels` |
| Chaines | Liste avec recherche, cloche rouge si l'une des deux est active ; ajout par adresse ; menu vers la Recherche | `GET /api/channels?q=&page=`, `POST /api/channels` |
| Chaine | Cloches videos et shorts, note, categories, actualiser le profil, supprimer, puis ses fiches | `PUT /api/channels/{id}/bells/{section}`, `.../rating`, `.../categories`, `POST .../refresh-profile`, `DELETE`, `GET /api/library?channel_id=` |
| Bibliotheque | Toutes les fiches, recherche, 50 par page ; feuille de filtres : vues enregistrees, tri, section (videos, shorts), types de fichier et categories a trois etats (inclus, exclu, neutre) avec mode « un des » ou « tous les », notees, sans categorie, « Tout voir » | `GET /api/library` (`sort`, `section`, `asset`, `exclude_asset`, `category`, `exclude_category`, `rated`, `uncategorized`, `hide`, modes, `q`), `GET /api/library/views`, `GET /api/categories` |
| Playlists | Liste ; creer, importer une playlist YouTube | `GET/POST /api/playlists`, `POST /api/playlists/import-url` |
| Playlist | Fiches dans l'ordre ; renommer, categories, ecoute libre, trier, dupliquer, supprimer ; appui long sur une fiche : monter, descendre, retirer | `GET/DELETE /api/playlists/{id}`, `PUT .../title`, `.../categories`, `.../free-listening`, `POST .../sort`, `.../duplicate`, `.../items/{item}/move`, `DELETE .../items/{item}` |
| Fiche | Lecteur, note, categories, Vu et Indesiree, onglets, menu | voir ci-dessous |
| Reglages | Nom, changer d'utilisateur, temps d'ecran (minutes par jour, usage du jour), couvre-feu, « Raton et toi », adresse du serveur | `GET/PUT /api/settings`, `GET /api/screen-time`, `PUT /api/users/{id}` |

La fiche :

- ouvrir une fiche appelle `POST .../open` : c'est ce qui retire le label
  Nouveau, comme la page du front ;
- le selecteur video / audio suit `media_urls` (les deux fichiers peuvent
  coexister) ; sans fichier, un bouton de telechargement (qualite au choix pour
  la video) lance `POST .../media/{type}/download` puis relit la fiche jusqu'a
  l'arrivee du fichier ; le menu supprime un fichier ;
- les boutons Vu et Indesiree basculent comme ceux du front, a partir de
  `shown_state` (l'etat affiche, calcule par le back) ; apres chaque action
  l'app relit la fiche au lieu de deviner le nouvel etat ;
- les etoiles envoient `rating` (0 a 5) ; toucher l'etoile deja choisie remet 0 ;
- categories : feuille de choix parmi celles du back (`PUT .../categories`) ;
- onglets : Plus d'informations (description, tags, chapitres qui font
  avancer le lecteur, playlists), Segments (segments sponsors), Transcript
  (lignes horodatees qui font avancer le lecteur), Notes structurees (resume et
  notes, rendu Markdown simple), Commentaire (`PUT .../comment`), Discussion
  sur la fiche (`POST .../chat`, la reponse est attendue en relisant
  `GET /api/llm-jobs/{id}`) ;
- menu : playlists (ajouter, retirer, creer), generer les notes
  (`POST .../notes/generate`), telecharger le transcript, ouvrir sur YouTube ;
- les erreurs sont des messages francais : serveur injoignable, acces au
  reseau local refuse (renvoie vers Reglages → Raton → Reseau local), adresse
  invalide, ou le `detail` envoye par le back.

## Lecteur

Un seul `AVPlayer` (`PlayerController`) vit au-dessus des ecrans : l'audio
continue quand on quitte la fiche ou qu'on verrouille l'ecran
(`AVAudioSession` `.playback`, `UIBackgroundModes` = `audio`), avec les
commandes de l'ecran verrouille (`MPNowPlayingInfoCenter`,
`MPRemoteCommandCenter` : lecture, pause, ±15 s, position). Une barre sous
les onglets permet de mettre en pause ou d'arreter l'audio hors de sa fiche.
Une video s'arrete en quittant sa fiche.

Il rapporte sa progression comme le JavaScript du front
(`reportPlayback` dans `front/static/js/app.js`) : `POST
/api/videos/{id}/activity` avec `{media_type, position_seconds,
duration_seconds, watched_seconds}`, a la pause, a la fin et a l'arret du
lecteur, si au moins une seconde a ete regardee. Les secondes regardees
s'accumulent par pas de moins de 5 s (un saut est une avance, pas du
visionnage). Le Vu a 90 % est decide par le back. Si `sponsor_skip_enabled`, le lecteur saute les `skip_segments` que le back donne.

## Pas encore

Ce que le front a et pas l'app : les reglages d'administration (racine des
medias, quota, categories et sous-bibliotheques, segments sponsors, notes
automatiques), les pages Statistiques, Journaux et RAG, les imports CSV
(abonnements, playlists), l'envoi d'un fichier video, les pages de variations
de Raton, la banniere du couvre-feu (l'app affiche simplement le refus du back),
le mini-lecteur persistant du web (l'app a la barre audio sous les onglets), le
mode hors ligne et la publication sur l'App Store.

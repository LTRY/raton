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

**Etat : jalon 1, jamais compile.** Le code a ete ecrit sans Xcode ni Swift :
il n'a ete ni compile ni lance. Le premier build peut demander de petites
corrections.

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

## Ecrans (jalon 1)

| Ecran | Role | Appels |
| --- | --- | --- |
| Adresse du serveur (premier lancement, puis Reglages) | Saisie de l'URL, validee avant d'etre gardee dans `UserDefaults` | `GET /api/users` (200 attendu) |
| Choix de l'utilisateur (puis Reglages) | Liste des utilisateurs, l'id choisi est gardé | `GET /api/users` |
| Nouveautes | Les fiches Nouvelles, une pile par chaine, dix chaines par page ; tirer pour rafraichir | `GET /api/nouveautes?page=N`, `GET /api/videos/{id}/thumbnail` |
| Fiche | Titre, chaine, description, boutons Vu et Indesiree, etoiles, boutons de lecture | `GET /api/videos/{id}`, `POST /api/videos/{id}/open`, `PUT /api/videos/{id}/list-state`, `PUT /api/videos/{id}/rating` |
| Lecteur | Video dans la fiche, audio avec commandes ; la lecture reprend a la derniere position connue du serveur | `/api/videos/{id}/video` ou `/audio` (`media_urls` de la fiche : les deux fichiers peuvent coexister), `POST /api/videos/{id}/activity` |

Details :

- ouvrir une fiche appelle `POST .../open` : c'est ce qui retire le label
  Nouveau, comme la page du front ;
- les boutons Vu et Indesiree basculent comme ceux du front, a partir de
  `shown_state` (l'etat affiche, calcule par le back, comme sur les cartes des
  listes) ; apres chaque action l'app relit la fiche au lieu de deviner le
  nouvel etat ;
- les etoiles envoient `rating` (0 a 5) ; toucher l'etoile deja choisie remet 0 ;
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
visionnage). Le Vu a 90 % est decide par le back.

## Pas dans le jalon 1

Exploration, chaines et cloche, playlists, Historique, discussions (chat),
notes, imports, mode hors ligne, publication sur l'App Store.

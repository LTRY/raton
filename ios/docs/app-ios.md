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

**Etat : jalons 1 et 2.** Le projet se genere et se compile avec Xcode, et tourne
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

| Ecran | Role | Appels |
| --- | --- | --- |
| Adresse du serveur (premier lancement, puis Reglages) | Saisie de l'URL, validee avant d'etre gardee dans `UserDefaults` | `GET /api/users` (200 attendu) |
| Choix de l'utilisateur (puis Reglages) | Liste des utilisateurs, l'id choisi est gardé | `GET /api/users` |
| Nouveautes | Les fiches Nouvelles, une pile par chaine, dix chaines par page ; tirer pour rafraichir | `GET /api/nouveautes?page=N`, `GET /api/videos/{id}/thumbnail` |
| Fiche | Titre, chaine, description, boutons Vu et Indesiree, etoiles, boutons de lecture | `GET /api/videos/{id}`, `POST /api/videos/{id}/open`, `PUT /api/videos/{id}/list-state`, `PUT /api/videos/{id}/rating` |
| Chaines | Liste des chaines avec recherche ; la cloche en rouge si l'une des deux est active | `GET /api/channels?q=&page=` |
| Chaine | Cloche videos et cloche shorts, puis les fiches de la chaine | `PUT /api/channels/{id}/bells/{section}` (`videos`, `shorts`), `GET /api/library?channel_id=` |
| Bibliotheque | Toutes les fiches (ce que la liste laisse de cote, Vu et Indesiree, est le defaut du back), recherche, 50 par page | `GET /api/library?q=&page=` |
| Playlists | Les playlists de l'utilisateur, puis les fiches d'une playlist dans l'ordre (toucher ouvre la fiche) | `GET /api/playlists`, `GET /api/playlists/{id}` |
| Historique | Ce qui a ete lu, par jour, du plus recent au plus ancien (bouton a droite du titre de Nouveautes) | `GET /api/historique?page=N` |
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

## Pas encore

Accueil (la ligne de Raton et la barre de discussion), filtres de la
Bibliotheque (categories, tris, vues enregistrees), Recherche YouTube, notes de
chaines, categories, commentaire, creation et edition des playlists, discussion
(chat), notes et quiz LLM, imports, telechargements, couvre-feu et temps
d'ecran, mode hors ligne, publication sur l'App Store.

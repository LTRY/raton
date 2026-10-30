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

`ios/project.yml` decrit le projet (cible iOS 26 minimum, `ios/Raton/` en sources) ;
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

L'app reprend le style des pages du front sur telephone, a partir de ses jetons
(`front/static/css/tailwind.input.css`, `@theme` et `:root`), copies dans
`ios/Raton/Theme.swift` : fond creme `#fbf6ee`, surfaces blanches a fine
bordure sable, texte brun `#2b2018`, terracotta `#c2410c` pour l'accent, police
Plus Jakarta Sans (`ios/Raton/Resources/PlusJakartaSans.ttf`, la police variable
du front convertie de woff2 en ttf, licence OFL), la mascotte
`raccoon-empty.png`, etoiles ambre. Clair seulement (`UIUserInterfaceStyle` =
`Light`). Un changement de jeton cote front se reporte a la main dans
`Theme.swift`.

- **Surfaces** : un seul point d'entree, `surface(in:tint:interactive:)` (et
  `surfaceCard`), dans `Theme.swift` : fond blanc, bordure fine, et pour
  l'etat actif le lavis terracotta pale avec une bordure terracotta. Les
  bascules (Video / Audio, Videos / Shorts, tout voir / masquer) ont la piste
  sable du web (`sandTrack`) avec un segment actif blanc.
- **Barre d'onglets** (`TabPill`, `ios/Raton/RatonApp.swift`) : une capsule en
  vrai Liquid Glass d'iOS 26 (`glassEffect`), comme les barres d'Apple et celle
  de Deezer, qui flotte sur les pages. Une bulle de verre teintee de terracotta
  est sous l'onglet actif et glisse vers l'onglet touche ; icones de 28 pt, sans
  libelle comme sur le web ; elle s'efface quand le clavier est ouvert. Elle est
  a 14 pt des cotes et a 21 pt du bord bas de l'ecran (`TabPill.margin`,
  `TabPill.bottomGap`), soit la distance des barres flottantes d'Apple : au-dessus
  de l'indicateur d'accueil, qui reste visible en dessous. Sa forme suit les coins
  arrondis du telephone (`ConcentricRectangle`), donc elle est aussi ronde sur un
  iPhone 17e que sur un 18 Pro. La distance se compte depuis le bord de l'ecran
  et non depuis la zone de securite : `RootView` pose la barre dans un `ZStack`
  qui ignore la zone de securite du bas, au-dessus des pages. Chaque page defile
  au-dessus d'elle grace a `barClearance()`, pose sur son `ScrollView` : une marge
  basse (`contentMargins`) egale a la hauteur de la barre et du mini-lecteur,
  plus 21 pt, que `RootView` donne par l'environnement (`barClearance`). Un
  encart de zone de securite pose a la racine (`safeAreaInset`) se comptait
  autrement dans le simulateur et sur un iPhone : le bas de la page restait
  derriere le mini-lecteur. Une nouvelle page a defilement l'appelle ; une feuille
  (`sheet`) n'en a pas besoin. La page change avec
  l'onglet (`.id(tab)`).
- **Mini-lecteur** (`NowPlayingBar`) : au-dessus de la barre d'onglets tant qu'un
  audio est charge, comme celui de Spotify : une pilule de verre fume sombre, de
  la forme et de la largeur de la barre d'onglets, posee 6 pt au-dessus, avec pause/lecture a gauche,
  le titre au-dessus de sa chaine (ou du nom de la playlist quand une playlist joue), puis « suivant » (dans une playlist) et
  fermer. Un toucher sur le titre ouvre la page de la playlist qui joue, sinon la
  fiche du media (`RootView.openPlayer` remplace la pile de l'onglet Playlists ou
  Bibliotheque et y bascule).
- **Texte, toucher, retour** : les polices suivent le reglage « Taille du texte »
  d'iOS (`Font.raton`), plafonne a `xxxLarge` a la racine pour que les lignes
  et pastilles tiennent ; les cibles de toucher font 44 pt au moins (les cinq
  etoiles se partagent la ligne) ; un retour haptique leger accompagne le
  changement d'onglet, les cloches, les etoiles et la bascule « tout voir » ;
  le changement d'onglet se fait en fondu de 0,15 s. Pas de mode sombre : le
  theme est clair uniquement, comme le front (`docs/spec/11-interface-html.md`).
- **Chargement et erreurs** : une liste montre une roue (`LoadingRow`) jusqu'a sa
  premiere reponse, puis « Aucune ... » si elle est vide ; une erreur de reseau
  ou de serveur s'affiche avec un bouton « Reessayer » (`ErrorMessage`).
- **Ecrans** : barre d'onglets en pilule flottante, boutons ronds blancs pour
  le retour et les menus, lignes de liste pleine largeur a vignette a gauche
  (duree, barre de progression), cartes blanches pour les chaines et les
  reglages, champs blancs a bordure fine (`webField`), pile de cartes et pastille
  de source sur les tuiles de playlist.
- **Animations du web** : les cinq icones de la barre d'onglets sont celles du
  front (`ios/Raton/TabIcons.swift`, dessinees a partir des SVG de `base.html`)
  et rejouent leur animation (saut de la maison, antenne qui se dessine,
  livre qui saute, lignes de la playlist qui se tracent puis triangle qui
  apparait, curseurs des reglages qui se croisent) quand on touche l'onglet ;
  les tuiles de playlist entrent en fondu depuis 14 pt plus bas, decalees de
  50 ms (jusqu'a la sixieme), comme `pl-card-in`. La couverture a toujours le format 16:9 : une vignette d'un autre format (4:3 avec bandes noires) est recadree et ne change jamais la hauteur de la tuile. Un toucher joue d'abord le survol du web (260 ms) puis ouvre la playlist ; un doigt qui reste pose le joue aussi, apres 90 ms ; un doigt qui glisse pour defiler ne le declenche pas. Ce survol (`.pl-card:hover`) : la tuile monte de 4 pt, la couverture est un peu plus vive, le titre passe en terracotta et les deux cartes de la pile s'eventaillent en pivotant. Rien ne bouge avec
  « Reduire les animations ».
- **Defilement vertical seulement** : le balayage depuis le bord gauche qui ramene en arriere en emportant la page est coupe (`UINavigationController`, `RatonApp.swift`) ; chaque ecran a son bouton de retour.
- Le Liquid Glass sert a la barre d'onglets seulement (voir « Barre d'onglets ») ; les cartes, boutons et feuilles gardent les surfaces blanches du web.

## Ecrans

Cinq onglets, comme la barre du front : Accueil, Chaines, Bibliotheque, Playlists, Parametres.

Une entree de menu (« ⋮ », ☰, +) qui ouvre un ecran est un `Button` qui leve un etat lu par `navigationDestination(isPresented:)` : un `NavigationLink` pose dans un `Menu` ne fait rien au toucher.

| Ecran | Role | Appels |
| --- | --- | --- |
| Adresse du serveur (premier lancement, puis Parametres) | Saisie de l'URL, validee avant d'etre gardee dans `UserDefaults` | `GET /api/users` (200 attendu) |
| Choix de l'utilisateur | Liste des utilisateurs ; dans Parametres, creer (+) et supprimer (appui long) | `GET/POST /api/users`, `DELETE /api/users/{id}` |
| Accueil | Raton et sa ligne de la visite, le bouton vers les Nouveautes ou l'Historique (rien d'autre : ni menu ni barre de discussion) | `POST /api/raton/visit`, `/static/img/raton/<art>` |
| Nouveautes | Comme sur le web, la page d'Exploration sur les chaines suivies : une seule liste de fiches, les plus recentes d'abord (pas de pile par chaine), avec la recherche, les filtres et la bascule « tout voir » ; fleche de retour et bouton Historique | `GET /api/library?followed=true`, `GET /api/videos/{id}/thumbnail` |
| Historique | Ce qui a ete lu, par jour | `GET /api/historique?page=N` |
| Recherche | Videos et chaines YouTube ; importer une video (video ou audio) ou ajouter une chaine | `GET /api/youtube/videos\|channels`, `POST /api/videos/import`, `POST /api/channels` |
| Chaines | Titre avec le nombre de chaines, recherche, « ★ Notees » (actif par defaut) et tri (dernier media joue par defaut) ; chaque chaine est une carte comme sur le web : banniere avec l'avatar par-dessus, nom, nombre de fiches, derniere activite, cloches et note qui s'utilisent depuis la liste ; menu « + » vers l'ajout par adresse et la Recherche | `GET /api/channels?q=&page=&sort=&rated=`, `PUT .../bells/{section}`, `PUT .../rating`, `POST /api/channels` |
| Chaine | Comme la page du front : banniere (degrade terracotta sans banniere) avec l'avatar par-dessus, nom qui ouvre YouTube, cloches videos et shorts avec leur pastille, note (toucher l'etoile deja choisie remet 0, pas de ×), menu « ⋯ » (statistiques, categories, rafraichir le profil, supprimer) ; description (« Voir plus ») et mots-cles (+N) ; bascule Videos / Shorts, bouton de recherche des nouveautes sur YouTube, recherche, bascule « tout voir » / « masquer les vues », tri (publication recente par defaut) et Filtres ; ses fiches avec la date de publication (les shorts en mosaique de tuiles portrait : 3 colonnes, grande tuile 2×2 avec le titre pour un short nouveau ou note 5, comme le front ; toucher une tuile lit le short en plein ecran dans le lecteur natif, apres l'avoir telecharge en 1080p s'il n'a pas de fichier, avec un cercle de chargement sans texte sur la tuile ; la petite fleche de la tuile ouvre la fiche) ; « Explorer la suite » | `GET /api/channels/{id}`, `PUT /api/channels/{id}/bells/{section}`, `.../rating`, `.../categories`, `POST .../refresh-profile`, `POST .../import-metadata` puis `GET /api/jobs/{id}`, `DELETE`, `GET /api/library?channel_id=` (`counts`, `explore_next_page`, `explore_page_size`) |
| Bibliotheque | Comme la page « Exploration » du front : bouton ☰ (Exploration, Nouveautes, Historique : les vues enregistrees du web n'y figurent pas, ni dans la feuille « Filtres », ce serait la meme chose qu'Exploration) et titre « Exploration » suivi du nombre de fiches dans une pastille (pas de titre « Bibliotheque » ni de compteur plus bas), recherche, « Filtres » avec le nombre de filtres actifs et, a sa droite sur la meme ligne, la bascule « tout voir » / « masquer les vues » (pas de pastilles sous le bouton : les filtres se retrouvent et s'effacent dans la feuille « Filtres ») ; chaque fiche a un menu « ⋮ » (Vu, Indesiree) et, sur iOS 27, se balaie vers la gauche pour les memes deux actions (`swipeActionsContainer`, absent avant : le menu reste) ; feuille de filtres : tri, section, types de fichier et categories a trois etats, notees, sans categorie | `GET /api/library` (`sort`, `section`, `asset`, `exclude_asset`, `category`, `exclude_category`, `rated`, `uncategorized`, `hide`, modes, `q`), `GET /api/categories`, `PUT /api/videos/{id}/list-state` |
| Hors ligne (Parametres, « Audios sur ce telephone ») | Les audios gardes sur le telephone depuis le menu « ⋮ » d'une fiche (« Ecouter hors ligne » / « Retirer de l'ecoute hors ligne ») : lecture sans serveur ni historique, suppression par la corbeille. Les fichiers sont des copies dans `Application Support/Offline`, hors sauvegarde iCloud ; une purge sur le serveur n'y touche pas | `GET /api/videos/{id}/audio` (au telechargement seulement) |
| Playlists | Titre avec le nombre, recherche (sur le titre), grille a deux colonnes de tuiles comme le web (le titre reserve toujours deux lignes, pour que les tuiles d'une rangee restent alignees ; marge sous la derniere rangee pour passer au-dessus de la barre d'onglets ; pile de cartes, pastille de source (seulement pour une playlist importee, YouTube ou CSV : une playlist manuelle n'en a pas), nombre de videos, menu « ⋯ » : dupliquer, supprimer) ; menu « + » : creer, importer une playlist YouTube | `GET/POST /api/playlists`, `POST /api/playlists/import-url`, `POST .../duplicate`, `DELETE` |
| Playlist | Barre du haut comme celle d'une fiche (retour, bouton video / audio, menu « ⋯ »), lecteur de file en tete (voir « Lecteur de playlist »), fiches dans l'ordre (ni coche ni compte de « vu » : une playlist n'affiche pas l'etat Vu, et son titre ne dit « Playlist YouTube » ou « Playlist CSV Takeout » que pour une playlist importee, jamais « manuelle ») : un toucher joue la piste, le « i » ouvre la fiche ; menu « ⋯ » : format par defaut (video ou audio), telecharger tout l'audio, telecharger toute la video, renommer, categories, ecoute libre, trier, dupliquer, supprimer ; appui long sur une fiche : monter, descendre, retirer | `GET/DELETE /api/playlists/{id}`, `POST .../download/{audio|video}`, `PUT .../title`, `.../categories`, `.../free-listening`, `POST .../sort`, `.../duplicate`, `.../items/{item}/move`, `DELETE .../items/{item}` |
| Fiche | Lecteur, note, categories, Vu et Indesiree, onglets, menu | voir ci-dessous |
| Parametres | Pas de bouton « Enregistrer » : un interrupteur, un pas ou une heure s'enregistre seul peu apres avoir bouge (retour haptique). En tete, l'avatar et le nom de l'utilisateur, avec un menu discret « ⋯ » (renommer, changer d'utilisateur). Cartes groupees a rangees : temps d'ecran par jour (une rangee par type, minutes avec un pas, usage du jour dessous) ; couvre-feu sur une ou deux lignes (l'interrupteur, puis « De … a … » une fois actif) ; « Sur ce telephone » : audios hors ligne (avec leur nombre) et serveur (son adresse). Pas de reglage « Raton et toi » dans l'app | `GET/PUT /api/settings`, `GET /api/screen-time`, `PUT /api/users/{id}` |

La fiche :

- ouvrir une fiche appelle `POST .../open` : c'est ce qui retire le label
  Nouveau, comme la page du front ;
- le selecteur video / audio suit `media_urls` (les deux fichiers peuvent
  coexister) ; sans fichier, un bouton de telechargement (qualite au choix pour
  la video) lance `POST .../media/{type}/download` puis relit la fiche jusqu'a
  l'arrivee du fichier ; le menu supprime un fichier ; la video et la carte audio
  sont cote a cote dans un carrousel, comme sur le web : elles suivent le doigt, avec un
  effet elastique aux extremites, puis se calent sur la plus proche (un quart de largeur
  ou un geste rapide suffit) ; le bouton video / audio du haut anime le meme
  deplacement ; sur la video seule la moitie haute lance le glissement, pour laisser la
  barre de progression native au sien ;
- cote audio (`AudioSlide.swift`), la fiche reprend la carte du front sur telephone :
  carte 16:9 sur un degrade radial terracotta vers brun, sans pastille ni bouton
  « Supprimer » (la suppression est dans le menu « ⋯ »), pochette carree de 168 pt au centre (la vignette, ou un
  carre brun sans vignette), bouton lecture / pause (ou telechargement) en verre au
  milieu, ±15 s de chaque cote et « Telechargement… » dessous ; sous la carte, la barre
  de progression du front (piste fine, remplissage terracotta, curseur 4×22, bulle
  du temps pendant le glissement, temps courant et duree), grisee tant que cet audio
  n'est pas la piste chargee ;
- Vu et Indesiree sont les deux premieres entrees du menu « ⋯ » en haut a droite
  (« Marquer comme vu / non vu », « Marquer indesiree / Ne plus masquer ») ; elles
  basculent comme celles du front, a partir de `shown_state` (l'etat affiche,
  calcule par le back) ; apres chaque action l'app relit la fiche au lieu de
  deviner le nouvel etat ;
- avant la lecture, la zone du lecteur montre la vignette de la fiche (assombrie) derriere le bouton lecture ;
- le lecteur video est celui du systeme (`AVPlayerViewController`, `NativeVideoPlayer` dans `Components.swift`) avec ses controles natifs : lecture, ±10 s, curseur, AirPlay, sourdine et le bouton plein ecran (agrandir ou reduire la video ne la met pas en pause : si elle jouait, la lecture reprend a la fin de la transition) ; un balayage vers le bas quitte le plein ecran ;
- « + Categories » a la taille des etiquettes de sa ligne ;
- plus d'onglets : les sections sont les unes sous les autres, chacune avec son
  titre, dans l'ordre : « Description » (depliant), Notes structurees (si elles
  existent), Discussion ; ni segments ni transcript n'y figurent (le
  lecteur saute toujours les segments sponsors quand le back l'active)
- les etoiles envoient `rating` (0 a 5) ; toucher l'etoile deja choisie remet 0 ;
- categories : feuille de choix parmi celles du back (`PUT .../categories`) ;
- sections : « Description » d'abord, un depliant ferme par defaut (chevron) qui contient
  la description et ses hashtags ; ni vues, ni j'aime, ni nombre de commentaires, ni nom
  de la chaine, deja sous le titre ; les chapitres dans ce meme depliant, apres les hashtags (un chapitre fait
  avancer le lecteur), puis les playlists, Notes structurees (resume et notes, rendu
  Markdown simple), le commentaire personnel n'est plus une section : « Ecrire un commentaire personnel » est une entree du menu « ⋯ » qui ouvre une feuille (`PUT .../comment`), Discussion
  sur la fiche, sans titre, dans l'esprit de l'app Claude : le message de l'utilisateur dans une bulle sable
  a droite, la reponse de Raton en texte simple sur la page avec une petite etincelle
  terracotta dessous (elle tourne pendant qu'il repond), questions suggerees en pastilles
  a contour fin, saisie sur une seule ligne dans une capsule blanche avec le bouton d'envoi rond a droite (Retour envoie aussi et ferme le clavier ; faire glisser la page ferme le clavier ; la fiche garde de la marge sous le dernier bloc pour passer au-dessus de la barre d'onglets),
  « Effacer la conversation » en lien discret (`POST .../chat`, la reponse est attendue en relisant
  `GET /api/llm-jobs/{id}`) ;
- menu : playlists (ajouter, retirer, creer), generer les notes
  (`POST .../notes/generate`), telecharger le transcript, ouvrir sur YouTube ;
- les erreurs sont des messages francais : serveur injoignable, acces au
  reseau local refuse (renvoie vers Reglages → Raton → Reseau local), adresse
  invalide, ou le `detail` envoye par le back.

## Pret pour l'App Store

Deja la : l'icone (`Raton/Assets.xcassets/AppIcon.appiconset`, le Raton au pop-corn sur le fond creme, 1024 px), le manifeste de confidentialite (`PrivacyInfo.xcprivacy` : pas de suivi, aucune donnee collectee, `UserDefaults` pour l'URL du serveur et l'utilisateur) et les commandes de l'ecran de verrouillage. la politique de confidentialite a publier est dans `ios/docs/confidentialite.md` (les captures d'ecran se refont depuis le simulateur avec la base de demo, dans `ios/appstore/`, hors git) ; `NSAllowsArbitraryLoads` reste actif parce que le serveur est une adresse libre du reseau local, souvent en `http` : a revoir avant une soumission (equipe de signature, captures, politique de confidentialite).

## Partager vers Raton

Depuis Safari ou l'app YouTube, la feuille de partage propose « Raton » (extension `ios/RatonShare/`, cible `app-extension`). Elle envoie le lien a `POST /api/videos/share-import` (le back importe la fiche, sans fichier media, et repond quand c'est fait), puis affiche « Ajoutee a Raton » ou le message du serveur (lien qui n'est pas YouTube, import en echec, serveur injoignable). C'est ce que faisait le raccourci iOS decrit dans `docs/spec/12-api-et-routes.md`, sans rien a construire a la main.

L'extension lit l'adresse du serveur dans l'App Group `group.fr.raton.app` ; l'app l'y recopie a chaque lancement et a chaque changement de serveur (`AppState`). Il faut donc avoir ouvert l'app une fois. Pour un iPhone reel, l'equipe de signature de l'app et celle de l'extension doivent avoir la capacite « App Groups » (Xcode la cree avec la signature automatique).

## Widget Nouveautes

Le widget « Nouveautes » (`ios/RatonWidget/`, petit et moyen format) montre Raton et le nombre de fiches des chaines suivies (`total` de `GET /api/library?followed=true`, l'en-tete `X-Raton-User` portant l'utilisateur), en creme et terracotta comme l'app. « Ouvrez Raton » tant qu'aucun serveur n'est choisi, « Hors ligne » quand il ne repond pas. Il lit l'adresse du serveur et l'utilisateur dans l'App Group `group.fr.raton.app` (comme l'extension de partage) ; l'app demande son rechargement quand elle passe en arriere-plan et quand le serveur ou l'utilisateur change, et iOS le rafraichit seul toutes les 30 minutes environ.

## Tests

`ios/RatonUITests/` tape la barre d'onglets et le menu ☰ de la Bibliotheque comme
un doigt (XCUITest). Il lui faut le back et le front de demo (`make demo`, front
sur `localhost:8000`) ; l'app y est pointee par les arguments de lancement
`-serverURL` et `-userID`. Lancer :
`xcodebuild test -project ios/Raton.xcodeproj -scheme Raton -destination 'platform=iOS Simulator,name=<iPhone>'`.
`make ci` ne les lance pas (rien dans ce conteneur ne compile l'app).

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

## Lecteur de playlist

Le haut d'une playlist est un lecteur de file, avec les regles du lecteur du
front (`front/static/js/playlist-player.js`, `docs/spec/08-medias-et-lecteurs.md`,
« File d'une playlist »), presente comme celui d'une fiche : le bouton video /
audio est dans la barre du haut, la video et la carte audio (vignette de la piste)
sont cote a cote dans le meme carrousel (`MediaPager`) et suivent le doigt, la
barre de progression est dans la vignette de la scene audio (blanche, au bas,
avec le temps ecoule et la duree ; la fiche garde la sienne sous la pochette), puis vient le titre de la piste
(il n'y a pas de ligne « N pistes a lire » quand rien ne joue). Les boutons de la
file (aleatoire, precedent, lecture, suivant, boucle) sont sur la scene audio en
mode audio : la vignette de la piste remplit toute la scene (pas de pochette
carree dans une playlist), sous un voile sombre, et la rangee est centree dessus,
en blanc, repartie sur toute la largeur de l'ecran (24 pt de marge, boutons de
44 pt) ; le bouton lecture est un disque en Liquid Glass, un seul bouton lecture.
Sans vignette, c'est le degrade brun de la scene ; sans piste lisible, la rangee
disparait. La fiche garde sa pochette carree de 168 pt. En mode video, la video a ses
commandes natives et la rangee de boutons reste sous l'image :

- le format par defaut se choisit par playlist dans le menu « ⋯ » (« Format par
  defaut »), garde sur l'iPhone (`UserDefaults`, une cle par playlist) : la page
  s'ouvre sur ce format, sauf si une file joue deja ; « Telecharger tout l'audio »
  et « Telecharger toute la video » appellent `POST /api/playlists/{id}/download/{type}`
  (un telechargement par fiche qui n'a pas le fichier) et disent combien sont lances ;

- le choix Video / Audio, l'aleatoire et la boucle sont gardes d'un lancement a
  l'autre (`UserDefaults`) ; une fiche sans le fichier du mode choisi est
  grisee (« Ignoree ») et sautee ;
- a la fin d'une piste la suivante demarre ; sans boucle la lecture s'arrete
  apres la derniere ; l'aleatoire ne rejoue rien avant d'avoir tout joue ;
  « precedent » apres 3 s revient au debut de la piste, sinon rejoue la
  piste d'avant ;
- une piste demarre a 0 (pas de reprise) et son activite est rapportee par
  piste (`POST /api/videos/{id}/activity`), sauf en ecoute libre ;
- la file (`PlaylistQueue`) vit dans `PlayerController` : elle continue quand on
  quitte la playlist, la barre sous les onglets propose pause, suivante et
  fermer, l'ecran verrouille propose piste precedente / suivante a la place des
  sauts de 15 s ; lancer une fiche seule ou fermer la barre vide la file ;
- changer l'ordre, retirer une fiche ou trier relit la playlist et met la file
  a jour sans couper la piste.

La barre ne ramene pas a la page de la playlist, et ouvrir depuis la playlist
la fiche d'une video en cours de lecture la coupe en la quittant.

## Pas encore

Ce que le front a et pas l'app : la periodicite d'une chaine, les reglages d'administration (racine des
medias, quota, categories et sous-bibliotheques, segments sponsors, notes
automatiques), les pages Statistiques, Journaux et RAG, les imports CSV
(abonnements, playlists), l'envoi d'un fichier video, les pages de variations
de Raton, la banniere du couvre-feu (l'app affiche simplement le refus du back),
le mini-lecteur persistant du web (l'app a le mini-lecteur audio sous les onglets), la
publication sur l'App Store.

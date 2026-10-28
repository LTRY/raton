---
title: "15 Securite"
---
# 15 Securite

## Hypothese LAN

Raton est opere sur un LAN de confiance.

Les pages principales ne sont pas authentifiees dans cet etat cible actuel.
Cette absence d'authentification n'est pas un bug tant que l'app n'est pas
exposee hors LAN.

Les utilisateurs (voir [20 Glossaire](20-glossaire.md), « Utilisateur ») ne
sont pas des comptes : aucun mot de passe, et n'importe qui sur le LAN peut
choisir n'importe quel utilisateur (bouton du tiroir « Discussions » sur ordinateur, cookie
`raton_user`, en-tete `X-Raton-User`), en ajouter, en renommer ou en
supprimer. Ils separent ce que chacun garde pour soi (Vu, etoiles, playlists,
discussions...), pas ce que chacun a le droit de voir.

La page des previews (conteneur `raton-ops`, `make previews`, port `8999`) n'est pas authentifiee non
plus, alors que son bouton **Deployer main en production** reconstruit la vraie
instance : sur ce LAN, n'importe qui peut la redeployer. Garde-fous : origine
verifiee sur chaque formulaire, confirmation, un seul deploiement a la fois, et
`scripts/deploy.sh` ne deploie que `origin/main` (voir
[04 Configuration et deploiement](04-configuration-et-deploiement.md),
« Deploiement de main »).

Ce conteneur tourne en **root** avec le socket Docker de l'hote monte : qui
atteint la page ou le conteneur controle le Docker de l'hote. Il recoit aussi
`GH_TOKEN`. C'est le prix de l'automatisation des previews et du deploiement ;
la page reste donc sur l'interface d'`APP_BIND` (loopback par defaut).

La page de monitoring (conteneur `raton-monitoring`, `make monitoring`, port
`8998`) n'est pas authentifiee non plus par defaut (`MONITORING_TOKEN` l'active).
Elle ne deploie rien et son conteneur n'a pas le socket Docker, mais il recoit
`ANTHROPIC_API_KEY` (la revue quotidienne des journaux, voir
[13](13-jobs-logs-planification.md)) et peut donc depenser au token : le bouton
**Analyser maintenant** est plafonne par `MONITORING_REVIEW_MAX_USD`. Il ne lit
que le journal, en lecture seule.

Une preview tourne avec la cle Anthropic du `.env` et le mot de passe de la DB
reelle (voir « Previews des PR » dans [04](04-configuration-et-deploiement.md)) :
le code d'une PR non mergee peut donc utiliser la cle et lire ou modifier les
vraies donnees. D'ou le refus des PR de fork, et le
deploiement d'une preview reste un geste manuel.

## Garde-fous sans authentification

- **Separation front/back** : seul le back (conteneur `api`, sans port
  publie) lit la DB, le dossier media et les secrets ; le front n'a rien de
  tout cela et ne fait qu'appeler l'API. Le seul point d'entree publie est le
  front, dont le relais `/api/*` transmet les requetes du navigateur au back.
- **CSRF** : `back/core/same_origin.py` (pour `/api`) et sa copie
  `front/same_origin.py` (pour les formulaires du front) refusent (403) toute requete d'ecriture
  (hors `GET`/`HEAD`/`OPTIONS`) venue d'un autre site : `Sec-Fetch-Site` autre
  que `same-origin`/`none`, ou hote d'`Origin` (a defaut `Referer`) different du
  `Host`. Le relais du front transmet au back le `Host`, l'`Origin` et les
  `Sec-Fetch-*` du navigateur : la meme verification s'y applique. Les appels
  du front lui-meme (replis sans JavaScript, rendu des pages) n'ont pas ces
  en-tetes et passent. Sans ces en-tetes (curl, scripts) la requete passe. Derriere un
  reverse proxy qui change le `Host`, lister l'hote public dans
  `APP_TRUSTED_ORIGINS` (separes par des virgules).
- **SSRF** : `back/services/youtube/url_guard.py` refuse les URL non http(s) ou visant une
  adresse locale/privee (loopback, 10/8, 172.16/12, 192.168/16, 169.254/16, IPv6
  locale), pour les URL de chaine, de video, de playlist et d'image de profil
  (redirections comprises). Un nom qui ne se resout pas est laisse a l'outil
  qui l'appelle ; le DNS rebinding n'est pas couvert.

- **Serveur MCP** : le port `8002` (`mcp`, voir
  [21 Serveur MCP](21-serveur-mcp.md)) n'est pas authentifie non plus ; il est
  publie sur `127.0.0.1` par defaut (`MCP_BIND=0.0.0.0` l'ouvre au LAN) et ses
  outils sont en lecture seule.

Si exposition Internet :

- ajouter authentification ;
- ajouter protection CSRF sur routes write ;
- revoir CORS, cookies, headers ;
- proteger PostgreSQL ;
- auditer routes media.

## Routes media

Les routes `/api/videos/{id}/thumbnail`, `/audio`, `/video`, `/subtitles` et
`/api/channels/{id}/avatar`, `/banner` (`back/api/media.py`) doivent :

- charger l'objet `Video` ;
- refuser si chemin absent ;
- resoudre `folder_path` ;
- resoudre chemin media ;
- verifier `is_file()` ;
- verifier `media.is_relative_to(folder)` ;
- retourner `404` sinon.

Objectif : empecher de servir un fichier arbitraire via chemin modifie en DB.

## Redirections

Les formulaires avec `next` ou `return_to` doivent limiter les retours aux
chemins internes : `internal_return_path` (`front/pages.py`) n'accepte qu'un
chemin qui commence par `/` et pas par `//` (qui designerait un autre hote),
sinon il renvoie la page de repli de la route. Toute redirection construite
a partir d'un parametre de formulaire passe par cette fonction.

## Appel sortant SponsorBlock

Seul appel reseau sortant vers un tiers de toute l'app (le reste est
strictement LAN/local, voir "Hypothese LAN" ci-dessus) : la recherche de
segments sponsorises envoie l'identifiant YouTube de la video (`videoID`,
aucune autre metadonnee) a `sponsor.ajay.app`, a la fois automatiquement a
la fin de chaque telechargement reussi et via le bouton manuel
"Rechercher les segments sponsors" de l'onglet Segments de `/videos/{id}`
(`back/services/youtube/sponsorblock.py`). C'est la seule source de segments.

Cet appel peut etre evite entierement en decochant toutes les categories
dans `/settings` (`sponsor_segment_categories`) : `fetch_sponsorblock_segments`
retourne `[]` sans requete reseau des que la liste de categories est vide
(`back/services/youtube/sponsorblock.py`).

SponsorBlock propose une variante de requete par prefixe de hash, plus
respectueuse de la vie privee (l'API ne voit alors qu'un prefixe partage par
de nombreuses videos, pas l'identifiant exact). Cette implementation ne
l'utilise pas et interroge directement par `videoID` complet
(`GET /api/skipSegments` avec `videoID` en clair), par choix de simplicite.

## Secrets

Ne pas committer :

- `.env` ;
- `ANTHROPIC_API_KEY`.


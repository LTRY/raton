---
title: "15 Securite"
---
# 15 Securite

## Hypothese LAN

Raton est opere sur un LAN de confiance.

Les pages principales ne sont pas authentifiees dans cet etat cible actuel.
Cette absence d'authentification n'est pas un bug tant que l'app n'est pas
exposee hors LAN.

## Garde-fous sans authentification

- **CSRF** : `app/web/same_origin.py` refuse (403) toute requete d'ecriture
  (hors `GET`/`HEAD`/`OPTIONS`) venue d'un autre site : `Sec-Fetch-Site` autre
  que `same-origin`/`none`, ou hote d'`Origin` (a defaut `Referer`) different du
  `Host`. Sans ces en-tetes (curl, scripts) la requete passe. Derriere un
  reverse proxy qui change le `Host`, lister l'hote public dans
  `APP_TRUSTED_ORIGINS` (separes par des virgules).
- **SSRF** : `app/services/youtube/url_guard.py` refuse les URL non http(s) ou visant une
  adresse locale/privee (loopback, 10/8, 172.16/12, 192.168/16, 169.254/16, IPv6
  locale), pour les URL de chaine, de video, de playlist et d'image de profil
  (redirections comprises). Un nom qui ne se resout pas est laisse a l'outil
  qui l'appelle ; le DNS rebinding n'est pas couvert.

Si exposition Internet :

- ajouter authentification ;
- ajouter protection CSRF sur routes write ;
- revoir CORS, cookies, headers ;
- proteger PostgreSQL ;
- auditer routes media.

## Routes media

Les routes `/videos/{id}/thumbnail`, `/audio`, `/video` doivent :

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
chemins internes : `internal_return_path` (`app/web/shared.py`) n'accepte qu'un
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
(`app/services/youtube/sponsorblock.py`). C'est la seule source de segments.

Cet appel peut etre evite entierement en decochant toutes les categories
dans `/settings` (`sponsor_segment_categories`) : `fetch_sponsorblock_segments`
retourne `[]` sans requete reseau des que la liste de categories est vide
(`app/services/youtube/sponsorblock.py`).

SponsorBlock propose une variante de requete par prefixe de hash, plus
respectueuse de la vie privee (l'API ne voit alors qu'un prefixe partage par
de nombreuses videos, pas l'identifiant exact). Cette implementation ne
l'utilise pas et interroge directement par `videoID` complet
(`GET /api/skipSegments` avec `videoID` en clair), par choix de simplicite.

## Secrets

Ne pas committer :

- `.env` ;
- `ANTHROPIC_API_KEY`.


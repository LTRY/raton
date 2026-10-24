---
title: "21. Serveur MCP"
---
# 21. Serveur MCP

Le serveur MCP (`mcp_server/`) permet à un client MCP (Claude Desktop, Claude
Code...) de lire la bibliothèque. C'est un **troisième client de l'API
`/api`**, au même titre que le front : il ne contient aucune règle métier,
n'accède ni à la DB, ni au dossier media, ni aux secrets, et n'importe rien de
`back/` ni de `front/` (`tests/test_code_structure.py`). Chaque outil est un
appel `GET` de l'API ; les règles (filtres, tri, pagination, état Vu) sont
calculées par le back.

## Déploiement

Service Compose `mcp` (conteneur `raton-mcp`, image `raton-mcp:local`, étape
`mcp` du `Dockerfile`), sur le réseau interne de Compose : il appelle
directement le back (`RATON_API_URL=http://api:8001`), sans passer par le
front. Il parle MCP en HTTP (`MCP_TRANSPORT=streamable-http`) sur le port
`8002`, publié sur `127.0.0.1` par défaut ; `MCP_BIND=0.0.0.0` l'ouvre au LAN.
L'URL à donner au client est `http://<hôte>:8002/mcp`.

Hors Docker, `python -m mcp_server` parle MCP en stdio ; `RATON_API_URL` donne
l'adresse du back (défaut `http://127.0.0.1:8001`, celle de `make demo`).

## Outils

Tous en lecture seule : aucun ne modifie la bibliothèque, ne lance de
téléchargement ni d'appel au LLM.

| Outil | Appel `/api` |
|---|---|
| `search_library` | `GET /library` (`q`, `channel_id`, `section`, `sort`, `page`) |
| `get_video` | `GET /videos/{id}` (sans `transcript_lines`) ; ne marque pas la fiche Vu |
| `list_channels` | `GET /channels` |
| `get_channel` | `GET /channels/{id}` |
| `list_playlists` | `GET /playlists` |
| `get_playlist` | `GET /playlists/{id}` |
| `get_nouveautes` | `GET /nouveautes` |
| `get_library_stats` | `GET /stats` |

Un appel refusé par le back lève une erreur portant son message (`detail`).

Le serveur n'envoie ni cookie ni en-tête `X-Raton-User` : il lit la
bibliothèque comme l'utilisateur par défaut, le plus ancien (ses notes en
étoiles, ses Nouveautés, ses playlists ; voir
[12 API et routes](12-api-et-routes.md), « Utilisateur d'une requête »).

## Limites

- Pas d'outil d'écriture (ajouter une chaîne, marquer Vu, générer des notes,
  poser une question au chat) : ces actions déclenchent des jobs ou des appels
  facturés au LLM et demandent d'abord de décider de leurs garde-fous.
- Pas d'authentification : voir [15 Sécurité](15-securite.md).

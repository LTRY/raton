---
title: "19. Indexation et recherche dans les notes"
---
# 19. Indexation et recherche dans les notes

Ce document réunit tout ce qui touche à la recherche sémantique dans les notes
des vidéos (outil `chercher_dans_les_notes` du chat bibliothèque) : ce qu'on a
compris du problème, ce qui est implémenté, pourquoi, et les pistes écartées
ou reportées. Les contrats précis (champs, routes, formats) restent dans
[05 Modèle de données](05-modele-de-donnees.md) et
[09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md) ; ici on
garde le raisonnement, pour ne pas le redécouvrir à chaque changement.

## 1. Le problème

Le chat bibliothèque répond à des questions du genre « trouve la vidéo de
Underscore qui parle de reverse engineering ». Le modèle ne connaît pas la
bibliothèque : il lui faut des outils. Deux familles de recherche existent :

- **textuelle** (`chercher_chaines`, `chercher_videos`) : mots-clés dans les
  titres, noms de chaînes, labels, commentaires
  (`app/services/common/search.py`) ;
- **sémantique** (`chercher_dans_les_notes`) : trouver ce qui *parle de* un
  sujet même avec d'autres mots (« rétro-ingénierie » pour « reverse
  engineering »), dans le contenu des vidéos.

Ce document traite la seconde. Elle ne voit que les vidéos dont les **notes
structurées** ont été générées (Faits, Dates, Lieux, Acteurs, Concepts,
Relations causales, voir 09).

## 2. Ce qu'on a compris

### Recherche vectorielle (bi-encodeur)

Un modèle d'embedding transforme un texte en vecteur de 1024 nombres. Deux
textes qui parlent de la même chose ont des vecteurs proches (distance
cosinus). On calcule le vecteur de chaque chunk une fois, à l'indexation, et
celui de la question à la requête ; pgvector trie les chunks par distance.

- **Atout** : c'est rapide, parce que les vecteurs des chunks sont
  précalculés.
- **Limite** : chaque chunk est compressé en 1024 nombres *avant* de savoir
  quelle question sera posée. Le chunk et la question ne se « voient »
  jamais : le score mesure une proximité globale, pas « ce texte répond-il à
  cette question ? ». Un chunk sur la rétro-ingénierie d'un firmware peut finir
  25ᵉ derrière des chunks d'« ingénierie logicielle ».

### Reranking (cross-encodeur)

Un cross-encodeur reçoit la question **et** le chunk dans la même entrée et
produit un score de pertinence. Chaque mot de la question peut « regarder »
chaque mot du chunk (attention croisée) : bien plus précis. Mais rien n'est
précalculable, il faut une passe de modèle par paire : inutilisable sur toute
la table.

### La cascade

```
N chunks (toute la table)
   │  vecteurs + pgvector (rapide, approximatif)  → vise le RAPPEL
   ▼
K candidats (CANDIDATE_CHUNKS = 50)
   │  reranker (lent, précis)                      → vise la PRÉCISION
   ▼
au plus TOP_K_CHUNKS = 8, au plus 2 par vidéo, score ≥ MIN_RELEVANCE_SCORE
```

Conséquences à garder en tête :

- le reranker **ne peut pas récupérer** ce que l'étape vectorielle a écarté :
  `CANDIDATE_CHUNKS` est le plafond de rappel ;
- il fournit un score exploitable, donc un **seuil** : mieux vaut ne rien
  renvoyer que des notes hors sujet, qui poussent le modèle à broder ;
- c'est un raffinement : s'il tombe en panne, la recherche continue avec
  l'ordre vectoriel.

### Un chunk sans contexte est pauvre

Une puce comme « - La dichotomie du contrôle » ne dit ni de quelle vidéo ni de
quelle chaîne elle vient. On préfixe donc le texte **embeddé et rerankéé**
d'un en-tête `Titre — Chaîne — Section`. Le contenu **stocké** et montré au
modèle reste le texte nu.

## 3. Ce qui est implémenté

| Élément | Où | Détail |
|---|---|---|
| Découpage | `app/services/llm/prompts.py:split_notes_sections` | un chunk par section Markdown des notes ; sections vides ignorées ; repli `Notes` |
| Texte embeddé | `app/services/rag/embeddings.py:contextualized_text` | `Titre — Chaîne — Section\ncontenu` |
| Embedding | `app/services/rag/embeddings.py` | API Voyage, `EMBEDDING_MODEL` (`voyage-3.5`), 1024 dimensions, `input_type` `document` (notes) / `query` (question) |
| Stockage | `video_note_chunks` | `vector(1024)`, sans index vectoriel (scan exact) |
| Indexation | `app/services/rag/indexing.py:index_video_notes` | au `generate` appliqué (tâche de fond `run_notes_indexing_job`) ; embed **avant** de supprimer les anciens chunks |
| Chunk de résumé | `rag_indexing.py:index_video_notes`, `backfill_summary_chunks` | le résumé court (`transcript.summary_short.txt`) est indexé comme une section « Résumé » ; rattrapage des vidéos déjà indexées sans ce chunk (embeddings seuls, aucun appel LLM) |
| Génération des notes | `app/services/rag/auto_notes.py` | lot nocturne (Message Batches, moitié prix, effort `low`) : notes + résumé court pour les vidéos sans notes, 100 par nuit, hors shorts et hors catégories exclues ; voir [13](13-jobs-logs-planification.md) |
| Rattrapage | `rag_indexing.py:backfill_note_chunks` | au démarrage et à chaque passage du lot nocturne : vidéos avec `transcript.notes.txt` et sans chunk ; no-op sans clé ; s'arrête à la première panne API |
| Recherche | `app/services/rag/retrieval.py:retrieve_relevant_chunks` | 50 plus proches (cosinus) → reranking → seuil → au plus 2/vidéo → 8 |
| Reranking | `embeddings.py:rerank`, `rag_retrieval.py:rerank_chunks` | `RERANK_MODEL` (`rerank-2.5`), `MIN_RELEVANCE_SCORE = 0.2`, repli sur l'ordre vectoriel si l'API échoue |

Configuration : `VOYAGE_API_KEY`, `EMBEDDING_MODEL`, `RERANK_MODEL` (voir
[04](04-configuration-et-deploiement.md)). Sans clé, l'outil renvoie l'erreur
au modèle, qui l'explique ; le reste de l'app n'est pas affecté.

### Tableau de bord

`GET /rag` (voir [11](11-interface-html.md), section "Indexation RAG") rend
cet etat lisible : etape de chaque video, contenu du prochain lot, lot en
cours, activite, cout et echecs. Il ne lit que la DB ; il ne declenche rien.

### Réindexation

Changer ce qui est embeddé rend les anciens vecteurs incomparables. La règle :
une migration **vide** `video_note_chunks`, et `backfill_note_chunks` la
reconstruit au démarrage depuis les fichiers de notes. Précédents :
ancienne migration (changement de modèle et de dimension),
ancienne migration (ajout du contexte au texte embeddé). Un
changement de `EMBEDDING_MODEL` par variable d'environnement seule **ne
déclenche pas** de réindexation : voir « Pistes » ci-dessous.

## 4. Décisions et raisons

- **Voyage plutôt que torch local.** Le modèle MiniLM chargé sur CPU rendait la
  première recherche après chaque redémarrage très lente (import de torch,
  chargement, et téléchargement du modèle à chaque nouveau conteneur).
  Voyage est le fournisseur d'embeddings recommandé par Anthropic. Voyage
  plutôt qu'OpenRouter : pour un seul modèle d'embedding, une passerelle
  n'apporte rien, et changer de modèle d'embedding oblige à tout ré-embedder
  de toute façon.
- **Notes uniquement, pas le transcript.** Quand elles existent, les notes
  sont meilleures que le transcript : denses, sans bruit oral, peu de chunks.
  Indexer aussi le transcript créerait deux sources de vérité. On travaille sur les notes déjà générées.
- **Reranking plutôt que tout miser sur le vecteur.** Gain de précision sans
  changer le modèle de données, même fournisseur, coût négligeable à
  l'échelle d'une bibliothèque personnelle.
- **Au plus 2 chunks par vidéo.** Une vidéo a plusieurs sections ; sans
  plafond la vidéo la plus proche occupe tous les emplacements.

### Génération automatique des notes

- **Périmètre** : toute la bibliothèque éligible, pas seulement les chaînes à
  cloche : la recherche n'a de valeur que si la couverture est large. Les
  exclusions (shorts et labels réglables, voir [13](13-jobs-logs-planification.md))
  évitent d'encombrer l'index de contenus sans intérêt pour une recherche par
  sujet, qui occuperaient des places parmi les 50 candidats vectoriels.
- **Exclure ne retire rien** : un label exclu ajouté plus tard ne supprime pas
  les chunks déjà écrits (l'utilisateur a pu générer ces notes exprès).
- **Notes + résumé court seulement** : le résumé complet, les questions et
  l'analyse sont des aides à la lecture, pas de la matière de recherche ; ils
  restent derrière le bouton robot. Le résumé court coûte ~155 tokens de
  sortie par vidéo.
- **Lot asynchrone plutôt qu'appels synchrones** : moitié prix, et le travail
  survit à un redémarrage de l'application (un balayage synchrone de 100
  vidéos dans le processus web est coupé par un `make up`). Le prix à payer :
  deux phases (collecter, puis soumettre) et un état (l'identifiant du lot).
- **Effort `low`** : l'extraction de notes demande peu de raisonnement, et les
  tokens de réflexion sont facturés comme de la sortie (les jobs `generate`
  mesurés sur Haiku 5.5 en consomment ~6,8 k en moyenne, résumé complet et
  analyse compris).
- **Mesuré sur un petit lot** de vidéos ayant déjà des notes : réponses
  exploitables, résumé de 3 lignes à chaque fois, notes généralement plus
  longues que les anciennes. Coût réel : de l'ordre de **0,002 $ par vidéo**
  (environ 10 k tokens en entrée, 4 k en sortie, au demi-tarif du lot). Le français pèse environ
  **2,4 caractères par token**, soit plus que les 3,1 de la table de tarifs :
  les estimations d'entrée faites avec 3,1 étaient ~25 % trop basses.
- **Coût projeté** : quelques dollars pour amorcer une bibliothèque de
  quelques centaines de vidéos, puis quelques centimes par mois pour les
  nouvelles. Le résumé et l'indexation d'une
  chaîne (résumé de chaîne à partir des résumés courts, index des chaînes) sont
  une étape suivante, non faite ici.

## 5. Limites connues

- **La couverture n'est plus un clic par vidéo, mais reste partielle** : le lot
  nocturne génère les notes de toutes les vidéos éligibles, à raison de 100 par
  nuit (la bibliothèque existante se rattrape donc en une dizaine de nuits).
  Restent invisibles pour cette recherche les vidéos exclues (shorts, labels
  exclus dans `/settings`), celles dont le transcript est absent ou trop court,
  et celles qui ont échoué 3 fois. La note de couverture du widget donne
  `indexed_video_count` / `total_video_count` ; une réponse « aucune vidéo ne
  parle de X » doit être relativisée tant que ce rapport n'est pas proche de 1.
- **Les notes sont lossy** : le schéma filtre. Une démonstration pas à pas,
  une opinion ou une anecdote n'y sont pas forcément.
- **`CANDIDATE_CHUNKS = 50` est prudent, pas mesuré** : c'est le plafond de
  rappel du reranking. Passer à 100 est probablement utile (au plus 6 sections
  par vidéo : 50 candidats peuvent ne couvrir que ~9 vidéos avant le plafond de
  2 par vidéo ; le coût du rerank reste négligeable). À décider avec les scores
  journalisés : si peu de candidats dépassent le seuil, 50 suffit.
- **`MIN_RELEVANCE_SCORE` n'est pas calibré** : 0,2 est une valeur de départ.
  Les scores sont journalisés (`rerank_chunks`) pour l'ajuster sur de vraies
  questions. Trop haut, on perd des résultats ; trop bas, on revient au
  comportement d'avant.
- **Un titre de vidéo modifié** laisse des vecteurs calculés avec l'ancien
  titre jusqu'à la prochaine génération des notes.
- **Pas de version du modèle par chunk** : on ne sait pas, ligne par ligne,
  avec quel modèle/texte elle a été embeddée.
- **Pas de recherche mixte** : un nom propre ou un acronyme rare passe mal en
  sémantique pure.
- **L'appel Voyage n'a pas été exercé contre l'API réelle** lors de
  l'implémentation (clé absente) : formats vérifiés sur la documentation et
  par des tests avec un client HTTP simulé.

## 6. Pistes futures

Classées par rapport gain / effort, pas encore décidées.

1. **Calibrer le seuil et `K`** à partir des scores journalisés, avec un petit
   jeu de questions réelles (« bonne vidéo attendue »). Prérequis de tout le
   reste : sans jeu d'évaluation, on règle à l'aveugle.
2. **Version d'embedding par chunk** : une colonne (modèle + version du
   gabarit de texte) pour que `backfill_note_chunks` réindexe de lui-même
   quand on change `EMBEDDING_MODEL` ou `contextualized_text`, au lieu d'une
   migration qui vide la table.
3. **Couverture** : ~~générer les notes automatiquement~~ (fait, voir plus bas).
   Reste : indexer le transcript en secours pour les seules vidéos exclues ou
   en échec (aucun appel LLM, mais plus de chunks, un index HNSW nécessaire,
   résultats plus bruités).
4. **Recherche mixte** (mots-clés + vecteur) : fusionner les résultats de
   `search.py` et de la recherche vectorielle (par exemple *reciprocal rank
   fusion*) avant le reranking, pour les noms propres et le jargon.
5. **Index HNSW** sur `embedding` : inutile jusqu'à quelques dizaines de
   milliers de chunks ; à ajouter si on indexe les transcripts.
6. **Requêtes multiples** : laisser le modèle (ou le code) émettre plusieurs
   formulations (« reverse engineering », « rétro-ingénierie », « décompiler »)
   et fusionner.
7. **Chunks plus riches** : inclure dans l'en-tête les labels de la vidéo ou
   la description de la chaîne ; essayer un modèle d'embedding contextuel de
   Voyage.
8. **Rafraîchir au changement de titre** : réindexer les chunks d'une vidéo
   dont le titre ou la chaîne change.

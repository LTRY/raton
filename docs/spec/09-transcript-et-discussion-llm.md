---
title: "09 Transcript et discussion LLM"
---
# 09 Transcript et discussion LLM

## Emplacement UI

Le transcript, les notes et la discussion sont tous integres sur `/videos/{id}`
— aucun des documents LLM n'a de page dediee.

En plus de ces documents, un resume court (3 lignes, genere en meme temps que
les notes, voir section Génération ci-dessous) s'affiche directement sous le
titre de la video (`#video-short-summary`), visible sans ouvrir d'onglet. Il
n'existe pas de resume complet : il a ete supprime, et un ancien
`transcript.summary.txt` laisse sur le disque n'est plus lu.

L'ancienne page `/videos/{id}/transcript` ne doit plus rendre de page dediee.
Elle redirige vers :

```text
/videos/{id}#transcript
```

Si une query string existe, elle est preservee avant l'ancre.

## Section transcript

La section a l'id :

```html
<section id="transcript" class="transcript-section">
```

Elle n'a plus de titre `<h2>` visible : la barre d'onglets (`.transcript-tabs`,
role `tablist`) sert d'en-tete et est **toujours rendue**, meme sans transcript
ni sous-titre. Chaque section affichable sur `/videos/{id}` (au sens large, pas
seulement les documents LLM) est un onglet de cette barre — "Plus d'informations"
(anciennement un `<details>` place apres les lecteurs) est au meme niveau que Transcript/Notes
structurees/etc. **Convention** : toute nouvelle section demandee sur `/videos/{id}` doit
etre ajoutee ici, comme un onglet supplementaire, plutot que comme un bloc a
part dans la page.

Onglets (`.transcript-tab`, `data-tab="..."`), dans l'ordre :

- `Plus d'informations` (`data-tab="info"`) : premier onglet a gauche ;
  toujours present ; panneau HTML independant regroupant metadonnees
  enrichies, chapitres, tags, description, et le bloc
  Publication/Telechargement/Taille/Transcript, puis le bouton « Supprimer la
  fiche » (voir [02 Fonctionnalites](02-fonctionnalites.md)) ;
- `Segments` (`data-tab="segments"`) : toujours present (jamais `hidden`,
  c'est le seul point d'entree du bouton "Rechercher les segments sponsors") ;
  libelle suffixe du nombre de segments affiches (`Segments (3)`) ; panneau
  HTML independant listant les segments SponsorBlock — voir
  [08 Medias et lecteurs](08-medias-et-lecteurs.md), section "Segments
  sponsorisés" ;
- `Transcript` (`data-tab="raw"`, anciennement libelle `Brut`) : onglet masque
  (`hidden`) si aucun `transcript.txt` n'existe ; il n'y a plus d'onglet `.vtt`
  montrant le fichier de sous-titres brut : ses horodatages servent au
  transcript ligne par ligne (voir plus bas) ;
- `Notes structurees` (`data-tab="notes"`) : onglet masque tant que
  `transcript.notes.txt` n'existe pas ;
- `Commentaire` (`data-tab="personal-notes"`, `id="personal-notes"`) :
  toujours present ; le formulaire renvoie vers `/videos/{id}#personal-notes`
  pour rouvrir l'onglet apres enregistrement ;

Les deux onglets `Transcript`/`Notes structurees`
partagent un seul `pre#transcript-content.transcript-content` (le contenu
affiche est echange cote client au clic, pas rechargee depuis le serveur), a
l'interieur d'un conteneur `[data-tab-panel="text"]` qui n'existe dans le DOM
que si `transcript.txt` existe (les autres onglets sont chacun un
`.transcript-panel[data-tab-panel="..."]` toujours present dans le DOM, meme
masque). **Aucun onglet n'est actif au chargement** : le HTML rendu par le
serveur n'a aucun bouton `.transcript-tab.active`, aucun `aria-selected="true"`
et tous les panneaux (y compris `[data-tab-panel="text"]`) sont `hidden` — on
arrive sur la page avec la seule barre d'onglets visible, et c'est un clic qui
ouvre un panneau.

Seule exception : l'ancre de l'URL, utilisee par les redirections apres action,
ouvre l'onglet correspondant cote client au chargement :

| ancre | onglet ouvert |
| --- | --- |
| `#transcript` | `Transcript` (aucun si pas de transcript) |
| `#personal-notes` | `Commentaire` |
| `#segments-sponsors` | `Segments` |

Affichage additionnel dans le panneau `text` :

- longueur en caracteres du document affiche + son libelle (`Transcript` /
  `Notes structurees`) ;
- icone de copie discrete en haut a droite de la zone de texte (copie le
  texte du document actuellement affiche — pour l'onglet `Transcript`, le
  contenu de `transcript.txt`, jamais le fichier `.vtt` ni les horodatages ;
  passe brievement en coche pour confirmer).

#### Transcript ligne par ligne

Quand les sous-titres de la fiche sont un fichier `.vtt` lisible
(`video.subtitle_path`) et que la fiche a un lecteur (fichier video ou
audio), l'onglet `Transcript` montre, a la place du `pre#transcript-content`,
un `div#transcript-lines` : une ligne `p.transcript-line` par ligne de
`transcript.txt`, chacune avec son heure de debut.

- Les lignes viennent de `GET /api/videos/{id}` (`transcript_lines`,
  `{start_seconds, text}`), lues dans le `.vtt` par le meme decoupage que
  celui qui ecrit `transcript.txt` (`read_transcript_lines`,
  `back/services/youtube/subtitles.py`) : memes lignes, memes doublons
  consecutifs retires ; une ligne repetee par les sous-titres automatiques
  garde l'heure du premier cue ou elle apparait.
- Au survol d'une ligne (souris), elle se surligne et propose un bouton
  `.transcript-line-seek` « ▶ m:ss » en fin de ligne ; sur ecran tactile
  (pas de survol), c'est un appui sur la ligne qui le fait apparaitre. Le
  bouton garde sa place masque (`visibility: hidden`) : le texte ne bouge pas
  quand il apparait.
- Le bouton porte `data-seek-time` : comme un timestamp de segment, il
  reprend la lecture du lecteur de la fiche a ce moment (voir
  [08 Medias et lecteurs](08-medias-et-lecteurs.md)).
- Sans `.vtt` (sous-titres d'un autre format, import manuel), sans lecteur ou
  si le fichier est illisible, le transcript reste le texte brut du `pre`.

### Bouton robot (generation IA)

Le declencheur de la generation (notes + résumé) ne vit pas dans la
barre d'outils du transcript mais **en haut de la page**, sur la meme ligne
que les actions formats Audio/Vidéo (`.video-detail-action-bar`), pour rester
visible sans defiler jusqu'a la section transcript. Sous 800 px, cette barre
est masquee et le menu « ⋮ » de la fiche porte un item « Generer avec l'IA »
qui relaie son clic vers ce bouton (voir « Detail video » dans
[11 Interface HTML](11-interface-html.md)) :

- bouton icone `.ai-generate-button` (robot SVG, rond, sans libelle) qui
  soumet `#generate-form` : le script appelle `POST /api/videos/{id}/notes/generate`
  (`POST /videos/{id}/transcript/generate` sans JavaScript) ; il n'est
  rendu que si `transcript.txt` existe ;
- au survol (ou au focus clavier, via `:hover`/`:focus-within` sur
  `.ai-generate`), une infobulle `#ai-generate-tooltip` resume ce que le
  bouton produit : notes structurees, résumé court et questions
  suggerees ; une passerelle CSS comble l'ecart bouton/infobulle ;
- pendant la generation, le bouton est desactive et son icone est remplacee
  par un spinner (`.ai-generate-loading`) : le libelle ne peut pas etre
  echange comme sur les autres actions LLM, ce qui effacerait le SVG ;
  l'infobulle est masquee tant que le spinner tourne ;
- **la page n'est jamais rechargee** et ne defile pas : des que le job est en
  file, le résumé court s'ecrit **mot par mot** sous le titre
  (`#video-short-summary`) au fil de la reponse du LLM, sans ouvrir d'onglet ;
  - le client interroge `GET /api/llm-jobs/{job_id}` toutes
    les 400 ms (2 s pour les autres jobs LLM) et lit `partial_short_summary`
    (voir section Jobs LLM asynchrones) ;
  - `createWordStream` (script de `video_detail.html`) revele le texte recu a
    un rythme regulier, decouple du rythme des polls : au moins 14 mots/s,
    plus vite quand le retard grandit ; chaque mot est un `span.stream-word`
    qui apparait en fondu, et un curseur clignotant (`.word-stream.is-streaming`)
    marque l'endroit ou le texte s'ecrit ; avec `prefers-reduced-motion`, les
    mots apparaissent sans fondu ;
  - le spinner du bouton continue de tourner une fois le résumé court ecrit, tant
    que les notes (generees ensuite) ne sont pas terminees ;
- a la fin du job, les onglets textuels, le résumé court et les questions
  suggerees sont mis a jour sur place a partir des `documents` de la
  reponse, sans changer l'onglet affiche ;
- une notification `.toast` (`window.showToast`, voir
  `11-interface-html.md`) annonce la fin : succes (`Notes et résumé
  générés par l'IA.`) ou erreur ; en cas d'erreur, le résumé court
  retrouve son contenu d'avant, et le message est aussi
  affiche dans `#generate-status`, sous le bouton, et dans
  `#transcript-action-status`.

Le statut asynchrone (`#transcript-action-status`) et la barre de progression
(`#transcript-progress`) sont partages par toutes les actions LLM de la page
(generation) — ils sont rendus juste sous la barre
d'onglets, hors du panneau `text`, pour rester disponibles meme quand ce
panneau n'existe pas dans le DOM.

## Barre de progression

Les jobs `generate` n'ont pas d'estimation fiable de duree ni de cout (voir
« Génération » ci-dessous) : l'UI affiche une barre de progression
indeterminee (`<progress>` sans attribut `value`, animation native du
navigateur).

## Génération : notes et résumé

Les notes structurées sont l'onglet `Notes structurees` de `/videos/{id}` (pas de
page dédiée). Le résumé court (3 lignes) est toujours visible sous le titre de
la vidéo (`#video-short-summary`, hors des onglets), pour donner une idée du
contenu sans ouvrir d'onglet, et les questions suggérées s'affichent dans la
discussion. Un seul bouton (le bouton robot en haut de la page, voir "Bouton robot
(generation IA)" ci-dessus) déclenche les deux documents à la fois, en un
seul appel LLM — il n'y a pas de route ni de bouton pour en régénérer un seul
en isolation.

`POST /api/videos/{id}/notes/generate` :

- source : `transcript.txt` ;
- crée systématiquement un job dans la DB (`llm_jobs`, `kind="generate"`) et
  répond immédiatement `202 {job_id, status, status_url}` (aucune estimation
  de durée ni de coût : la sortie combinée n'est pas corrélée à la longueur
  d'entrée) — planification asynchrone par `BackgroundTasks` ;
- **un seul appel LLM produit les deux documents**, pour n'envoyer le
  transcript qu'une seule fois (`back/services/llm/prompts.py:build_generation_prompt`) :
  le prompt combine les instructions des notes et du résumé (les anciens
  prompts séparés, inutilisés, ont été supprimés) sous deux titres Markdown de **niveau 1**
  exacts et dans cet ordre — `# Résumé`, `# Notes` (le résumé d'abord : c'est lui qui s'affiche pendant que la
  réponse arrive) — chacun suivi des mêmes sous-sections de niveau 2 qu'avant :
  - La règle « rien d'autre avant le premier titre » n'est énoncée qu'une fois,
    pour les titres de niveau 1 : les blocs de notes et de résumé imbriqués
    n'en portent pas (deux consignes imbriquées faisaient parfois écrire
    `## Notes` au lieu de `# Notes`) ;
  - chaque builder (`build_generation_prompt`, `build_auto_notes_prompt`, `build_chat_prompt`,
    `build_library_chat_prompt`) renvoie un `Prompt(system, messages)` : les
    consignes vont dans le paramètre `system` de l'API, les données (le
    transcript, la question) dans les messages `user`. Le job stocke ce
    `Prompt` en JSON (`llm_jobs.prompt`), le runner l'exécute tel quel :
    `complete(messages, system=...)`, `complete_with_tools(...)`, ou
    `submit_batch` pour le lot nocturne ;
  - le transcript est toujours placé entre `<transcript>` et `</transcript>`
    (`prompts.py:_transcript_block`), dans les prompts de notes, de résumé, de
    génération, de notes automatiques et de chat par vidéo ; les consignes
    précisent que son contenu est de la matière à analyser, jamais des
    instructions. Un `</transcript>` présent dans le texte est neutralisé
    (`</ transcript>`) pour ne pas fermer le bloc. Les titres de la réponse
    restent en Markdown : seul le transcript en entrée est balisé ;
  - Notes (apres le résumé dans la réponse) : exactement 6 sections (`NOTES_SECTION_NAMES`) — `## Faits`,
    `## Dates`, `## Lieux`, `## Acteurs`, `## Concepts`, `## Relations
    causales` — chacune en puces, sans rien inventer ; une section sans
    élément pertinent contient le texte fixe "Aucun élément identifié."
    plutôt que d'être omise. Le prompt définit le contenu de chaque section
    (`NOTES_SECTIONS`) pour qu'un élément n'atterrisse que dans une seule, et
    impose que chaque puce se comprenne seule, hors du reste des notes (noms
    propres plutôt que pronoms ou « cette vidéo »), car chaque section est
    indexée comme un chunk à part ; le transcript étant automatique, un nom
    propre écrit de plusieurs façons garde sa graphie la plus fréquente ;
  - Résumé : `## Résumé court` (exactement 3 lignes, sujet + conclusion
    principale), `## Questions suggérées` (3 à 5 questions concrètes en
    puces, pas génériques) ;
- `back/services/llm/prompts.py:split_generation_result(text)` découpe
  d'abord la réponse sur les deux titres de niveau 1, puis délègue chaque
  bloc au split_* à usage unique correspondant (`split_notes_sections` en
  interne via l'indexation RAG ci-dessous, `split_summary_result`) ; un titre de niveau 1 absent (modèle
  n'ayant pas suivi le format) dégrade proprement vers un résultat vide pour
  ce seul document, sans deviner, comme chaque split_* individuel ;
- le client interroge `GET /api/llm-jobs/{job_id}` jusqu'à
  résolution, qui applique le résultat complet en une fois : écrit
  `transcript.notes.txt`, `transcript.summary_short.txt`,
  `transcript.questions.txt` (une
  question par ligne) ; répond avec les `documents` de la fiche ; peut être
  régénéré à volonté, ce qui écrase les quatre fichiers ;
- sans JavaScript, `POST /videos/{id}/transcript/generate` met le même job en
  file et redirige vers `/videos/{id}?message=...#transcript` (`level=error`
  en cas d'erreur).

**Génération automatique** : le bouton robot n'est plus le seul moyen d'obtenir
des notes. Un lot nocturne (`auto_notes`, voir
[13 Jobs, logs et planification](13-jobs-logs-planification.md)) produit, pour
les vidéos qui n'en ont pas, **les notes structurées et le résumé court
seulement** (`back/services/llm/prompts.py:build_auto_notes_prompt`, mêmes instructions
de notes et de résumé court que ci-dessus, sans questions) et écrit `transcript.notes.txt` et `transcript.summary_short.txt`
(jamais écrasé s'il existe déjà : un résumé généré à la main prévaut). Le
résultat est appliqué par le service lui-même, pas par le polling de cette
route. Le résumé court s'affiche donc sous le titre sans clic ; le bouton robot
reste le seul moyen d'obtenir les questions, et il regénère
tout, y compris ces deux fichiers.

**Indexation RAG cross-video** : dès que le job `generate` est appliqué, une
tâche `BackgroundTasks` découpe le seul bloc `# Notes` (pas le texte combiné
entier) en chunks par section (`back/services/llm/prompts.py:split_notes_sections`,
sections vides/placeholder ignorées), les embed via l'API Voyage
(`back/services/rag/embeddings.py`, `EMBEDDING_MODEL`, 1024 dimensions,
`VOYAGE_API_KEY`), chaque section précédée du titre de la vidéo et de sa
chaîne, et remplace les lignes existantes de `video_note_chunks`
pour cette vidéo (`back/services/rag/indexing.py:index_video_notes`) ; le **résumé court**
(`transcript.summary_short.txt`) y ajoute un chunk de section « Résumé », qui
donne le fil de la vidéo là où les notes donnent des faits isolés.
`backfill_summary_chunks` ajoute ce chunk aux vidéos indexées avant qu'il
existe. Les embeddings sont calculés **avant** de supprimer les anciens chunks : une
panne de l'API garde l'index précédent. Au démarrage,
`backfill_note_chunks` (job `backfill_note_index`) indexe les vidéos qui ont
un `transcript.notes.txt` mais aucun chunk — reconstruction après la
migration `0040`, ou notes écrites sans clé ; sans `VOYAGE_API_KEY` c'est un
no-op, et la première panne de l'API interrompt le passage (réessayé au
démarrage suivant). Une vidéo ne devient
recherchable depuis le chat cross-video que lorsqu'elle a au moins un chunk
ici — regénérer des notes déjà au format libre (anciennes notes) ne les
indexe pas rétroactivement, il faut recliquer sur "Générer notes, résumé". Voir [05 Modèle de données](05-modele-de-donnees.md).

## Jobs LLM asynchrones

`GET /api/llm-jobs/{job_id}` (voir [12 API et routes](12-api-et-routes.md))

La mise en file (lecture du transcript, prompt, question vide refusee) et
la resolution d'un job (en attente, echec, ecriture du resultat au premier
poll) sont dans `back/services/jobs/llm_requests.py`.

- s'applique a tous les jobs `llm_jobs`, quel que soit le fournisseur
  (traites en tache de fond dans le process web via
  `back/services/jobs/llm_jobs.py:run_llm_job`) ;
- tant que le job est `queued`/`running`, repond `status: "pending"` ;
  pour un job `generate` dont la reponse a commence a arriver, la reponse
  porte en plus `partial_short_summary` : le résumé court tel qu'ecrit
  jusque-la (`back/services/llm/prompts.py:partial_generation_summary`). Cette valeur ne fait
  que s'allonger d'un poll au suivant (un titre Markdown en cours d'ecriture
  n'y apparait jamais), ce qui permet au client de n'ajouter que la suite ;
  `run_llm_job` enregistre pour cela le texte recu dans `llm_jobs.result`
  toutes les 0,4 s pendant que le job `generate` est `running` — `result`
  n'est la reponse complete qu'une fois le job `done` ;
- si le job a echoue, repond `status: "failed"` avec un message d'erreur
  explicite (`Génération` ou `Réponse` selon `kind`) ;
- des que le job est termine (`done`), applique le resultat une seule fois
  (ecrit `transcript.notes.txt`/`transcript.summary_short.txt`/
  `transcript.questions.txt` pour
  `generate` ; ajoute question/reponse a `transcript.chat.json` pour `chat` —
  voir sections Génération/Discussion ci-dessus), passe le job a
  `applied`, puis repond `status: "done"` avec `documents` (`generate` :
  transcript, notes, résumé court, questions et discussion, pour que la page
  resynchronise ses onglets et le résumé sous le titre en une fois) ou
  `chat_messages` (`chat`). Un nouveau poll sur un job deja `applied`
  renvoie l'etat courant sans ré-appliquer (idempotent).

## Cout reel des jobs LLM

`back/services/jobs/llm_jobs.py:run_llm_job` enregistre le cout **reel** sur chaque `LlmJob` des
que la completion reussit, a partir de l'usage exact renvoye par le
fournisseur lui-meme (`response.usage` du SDK Anthropic,
`back/services/llm/provider.py:CompletionResult`) :

- `model`, `input_tokens`, `output_tokens` : tels que rapportes par l'API,
  peu importe le nombre reel de caracteres du prompt/de la reponse ;
  `input_tokens` = tout ce qui est envoye (tokens non caches + lectures et
  ecritures de cache), `output_tokens` inclut les tokens de reflexion
  (adaptive thinking), factures comme de la sortie ;
- `cost_usd` : somme **appel par appel** (`back/services/llm/provider.py:UsageTally`,
  `back/services/llm/usage.py:compute_call_cost_usd`) contre le tarif du modele
  **effectivement utilise** pour ce job (pas le reglage courant — evite que
  changer de modele ne fausse retroactivement le cout des anciens jobs).
  Appel par appel parce que le tarif de Haiku 5.5 depend de la taille du
  prompt de *chaque* requete (<= 100 000 tokens : 0,10 $ entree / 0,50 $
  sortie par million ; au-dela : 0,50 $ / 2,50 $, sur toute la requete) : une
  boucle d'outils (`library_chat`) ne peut pas etre chiffree depuis ses totaux.
  Les tokens de cache sont chiffres a leurs propres tarifs. `null` pour un
  modele absent de la table de tarifs (`ANTHROPIC_MODEL_PRICING`) ;
- un job `queued`/`running` n'a jamais ces champs remplis. Un job `failed` ne
  les a que si l'API a repondu mais que la reponse est inutilisable (tronquee
  par `max_tokens`, ou vide : `back/services/llm/provider.py:CompletionFailed`) — ces
  tokens sont factures meme si le job echoue, donc comptes. Un echec reseau
  ou API en cours de route n'est pas reconstitue.

Le plafond de tokens de sortie (`max_tokens`) depend du modele
(`back/services/llm/usage.py:max_output_tokens` : 64 000 pour Haiku 4.5 qui
refuse davantage, 128 000 pour les autres modeles connus, 64 000 pour un
modele inconnu). Avec Haiku 5.5, la reflexion adaptative (effort `medium` par
defaut) consomme une partie de ce plafond et du cout de sortie.

`/settings` (section "Couts LLM") affiche le cumul par type de job puis par
modele (`back/services/llm/usage.py:llm_usage_summary`) : nombre de jobs,
tokens entree/sortie, cout, plus un total general et un compte des jobs "non
mesures" (en attente, echoues avant toute reponse, ou sans tarif connu). Ce total ne couvre que
l'activite depuis l'ajout de ce suivi (une ancienne migration,
voir [05 Modele de donnees](05-modele-de-donnees.md)) — les jobs plus anciens
n'ont pas ete retro-estimes.

## Discussion

La section discussion a l'id :

```html
<section id="discussion" class="discussion">
```

Elle affiche le widget de chat partage (voir
[11 Interface HTML](11-interface-html.md)) titre `Discuter du contenu` :

- historique des messages en bulles (`Vous` a droite, `Assistant` a
  gauche) ;
- aucun message d'etat vide pour la portee video : tant qu'il n'y a pas de
  message, la zone d'historique est repliee et le champ de saisie remonte
  sous l'en-tete (la portee `library` garde le sien) ;
- formulaire textarea `question`.

`POST /api/videos/{id}/chat` `{question}` (le widget n'a pas de repli sans
JavaScript)

- refuse les questions vides (`400`) ;
- lit `transcript.txt` ;
- charge `transcript.chat.json` ;
- construit le `Prompt` (`prompts.py:build_chat_prompt`) : consignes dans
  `VIDEO_CHAT_SYSTEM`, puis le transcript balisé en tête du premier message
  `user`, les 10 derniers messages de la discussion en vrais tours
  `user`/`assistant` (l'alternance exigée par l'API est imposée, comme pour le
  chat bibliotheque) et la question ;
- cree systematiquement un job dans la DB (`kind="chat"`, la question brute est
  conservee a part pour etre ajoutee a l'historique une fois la reponse
  obtenue) et repond immediatement `202 {job_id, status, status_url}`, sans
  jamais bloquer la requete ;
- planifie `back/services/jobs/llm_jobs.py:run_llm_job` via `BackgroundTasks` ; voir la section
  jobs LLM asynchrones ci-dessus pour la resolution.

`DELETE /api/videos/{id}/chat` supprime `transcript.chat.json` si present
(`204`).

## Chat cross-video (bibliotheque)

Barre de saisie de l'assistant sur le dashboard, et portee "Toute la
bibliotheque" du widget de chat de `/videos/{id}` (voir
[11 Interface HTML](11-interface-html.md)). Contrairement au chat par-video
(tout le transcript en contexte, sans recherche), le prompt ne contient aucun
contenu de la bibliotheque : le modele va chercher lui-meme ce dont il a
besoin en appelant des **outils**, et choisit lesquels selon la question
(retrouver une chaine, lister des videos, repondre sur le contenu, ajouter
une chaine YouTube a la bibliotheque).

### Outils

Definis dans `back/services/library_chat/schema.py` (`LIBRARY_CHAT_TOOLS`),
executes par `LibraryChatToolbox` (`back/services/library_chat/tools.py`) :

- `chercher_chaines(requete)` : recherche textuelle par mots, insensible a la
  casse et aux accents, sur le nom, les labels, l'URL et l'identifiant YouTube
  des chaines — la meme que le champ de recherche de `/channels`
  (`back/services/common/search.py:channel_search_rank`). Sans requete, liste toutes
  les chaines (60 au plus), ce qui permet au modele de retenir lui-meme celles
  qui correspondent a un theme. Chaque chaine est renvoyee avec ses labels, sa
  note, son nombre de videos et l'etat de sa cloche ;
- `chercher_videos(requete, chaine_id)` : meme recherche textuelle que
  `/videos` (`video_search_rank` : titre, chaine, labels, commentaire,
  URL), sur toutes les videos y compris celles sans
  notes structurees, restreinte a une chaine si `chaine_id` est fourni. Avec
  `chaine_id` seul, renvoie les videos les plus recentes de la chaine. 20
  resultats au plus ;
- `chercher_dans_les_notes(requete)` : recherche semantique (RAG).
  `back/services/rag/retrieval.py:retrieve_relevant_chunks` embed la requete
  (API Voyage, `input_type="query"` face aux vecteurs `document` de
  l'indexation ; sans cle ou en cas de panne, l'outil renvoie l'erreur au
  modele, qui l'explique, sans faire echouer le job), prend les 50
  `video_note_chunks` les plus proches par distance cosinus, les **reordonne
  avec le reranker Voyage** (`RERANK_MODEL`, meme texte contextualise que
  l'indexation), ecarte ceux sous `MIN_RELEVANCE_SCORE` puis garde les 8
  meilleurs, toutes videos confondues, avec au plus 2 chunks par video
  (`diversify_chunks`) : si le reranker echoue, l'ordre vectoriel est conserve
  sans seuil. Le raisonnement et les pistes futures sont dans
  [19 Indexation et recherche dans les notes](19-indexation-et-recherche-notes.md) ;
  une video a plusieurs sections de notes, et sans ce plafond la video la
  plus proche occuperait toutes les places et masquerait les autres. Chaque
  chunk est renvoye avec sa video et sa chaine. Ne couvre que les videos indexees (voir
  [05 Modele de donnees](05-modele-de-donnees.md)) ;
- `consulter_historique(jours, requete)` : historique de lecture (les
  `download_jobs` `played`, voir [11 Interface HTML](11-interface-html.md)),
  du plus recent au plus ancien, **une ligne par video** comme la page
  d'historique (`back/services/videos/playback.py:dashboard_media_activity_logs`). `jours`
  (30 par defaut) borne la fenetre, `requete` filtre sur le titre ou la
  chaine. Chaque ligne donne la reference de la video et de sa chaine, la date
  et l'heure de lecture, la position (ou « terminee »), la duree et le temps
  regarde ; une video supprimee de la bibliotheque reste listee par le titre
  enregistre, sans reference. 30 resultats au plus ; 500 lectures lues au
  plus avant regroupement ;
- `chercher_sur_youtube(requete)` : cherche sur YouTube des chaines par nom
  (`back/services/youtube/channel_info.py:search_channels`, voir
  [07 YouTube et telechargements](07-youtube-et-telechargements.md)). Chaque
  candidate est renvoyee avec un identifiant `[youtube:ID]`, son handle, son
  nombre d'abonnes et le debut de sa description ; celles deja dans la
  bibliotheque sont signalees avec leur reference `[chaine:ID]` ;
- `ajouter_chaine(youtube_id)` : cree la chaine (note 1, cloches eteintes,
  comme l'ajout depuis `/channels`) a partir d'une candidate de
  `chercher_sur_youtube`. Seul un identifiant renvoye par cette recherche
  **pendant le meme job** est accepte : le modele ne peut pas ajouter une
  chaine a partir d'un identifiant invente. Une chaine deja presente n'est pas
  dupliquee : l'outil renvoie sa reference. La confirmation d'ajout repete le
  handle et le nombre d'abonnes de la chaine.

Le prompt cadre l'ajout : uniquement sur demande explicite de l'utilisateur ;
si une candidate correspond nettement (meme nom, bien plus d'abonnes que ses
homonymes) le modele l'ajoute et le confirme avec son handle et son nombre d'abonnes
(pour que l'utilisateur verifie que c'est la bonne), sinon il presente les candidates et
demande laquelle ajouter, puis relance la recherche avec le handle choisi au
message suivant (les candidates ne survivent pas a un job).

Les deux recherches textuelles exigent que tous les mots de la requete soient
presents ; si aucun resultat ne les contient tous, l'outil se rabat sur les
resultats qui en contiennent au moins un et le signale dans sa reponse.

Une erreur dans un outil n'echoue pas le job : elle est renvoyee au modele
comme resultat de l'outil (`Erreur de l'outil ...`), qui peut alors le dire
ou essayer autrement.

### References et puces

Chaque chaine ou video renvoyee par un outil porte une reference
`[chaine:ID]` ou `[video:ID]`. Les consignes
(`back/services/llm/prompts.py:LIBRARY_CHAT_SYSTEM`, envoyées en `system`) demandent au modele d'ecrire,
a l'endroit ou il en parle, le nom de chaque chaine ou video qu'il retient
sous la forme `[[chaine:ID|Nom]]` / `[[video:ID|Titre]]` : le texte affiche
est le nom, la syntaxe disparait a l'affichage (voir
[11](11-interface-html.md)). `LibraryChatToolbox.extract_sources` valide
ensuite ces references, **sans les retirer** : une reference vers un id
« garanti » reste dans `content`, vers un autre id (le modele ne peut pas
faire apparaitre un element invente) elle est remplacee par son seul libelle
(supprimee s'il n'y en a pas). Un id est garanti quand un outil l'a renvoye
pendant ce job **ou** qu'une reponse precedente de la **meme** discussion l'a deja cite
(`library_chat_messages.sources` / `channel_sources`) : le modele recoit
l'historique avec ses `[[...]]` et peut les reprendre au tour suivant. Le
libelle ecrit par le modele n'est qu'un repli : l'interface affiche le nom
stocke dans la DB (voir [11](11-interface-html.md)). Le libelle va jusqu'au
premier `]]` non suivi d'un `]`, donc un titre comme `[FR] Python [2024]`
passe. La forme nue `[chaine:ID]` / `[video:ID]` (anciens prompts, ou recopie
de la sortie d'un outil) est retiree du texte mais compte dans la liste des
elements cites, dans l'ordre de premiere mention. Les identifiants `[youtube:ID]` ne designent pas un element de la
bibliotheque : ils sont simplement retires du texte si le modele les recopie.

Le prompt impose aussi la forme de la reponse : vouvoiement, texte brut sans
Markdown (la bulle affiche le texte tel quel), et ne jamais presenter les
resultats comme une liste complete — les outils plafonnent leurs resultats et
la recherche dans les notes ne voit que les videos indexees.

Ces listes (`sources`, `channel_sources`) donnent le nom et la cible de chaque
lien du texte ; ce que le texte ne mentionne pas (messages enregistres avant
ce format) reste affiche en puces sous la reponse : les
chaines d'abord (vers `/videos?channel_id={id}`), puis les videos (vers
`/videos/{id}`).

### Discussions

Le chat bibliotheque garde plusieurs discussions
(`library_chat_conversations`, voir [05](05-modele-de-donnees.md)) : chaque
question suit une discussion, et le modele ne relit que celle-ci. Une
question posee sans discussion en ouvre une nouvelle, nommee d'apres cette
question (`conversation_title` : sur une ligne, 80 caracteres au plus). Une
discussion dont la premiere question n'a jamais eu de reponse (job echoue)
n'a aucun message : elle n'est pas listee, et la question suivante du widget
la reprend. La liste donne les 50 discussions les plus recemment repondues ;
les plus anciennes restent dans la DB. Supprimer une discussion supprime ses
messages ; un job encore en cours pour elle echoue au poll
(`Discussion supprimée`) au lieu d'ecrire sa reponse ailleurs.

### Routes

`POST /api/chat` `{question, conversation_id}` :

- refuse les questions vides (`400`) et une discussion inconnue (`404
  Discussion introuvable.`) ;
- sans `conversation_id`, ouvre une nouvelle discussion
  (`history.py:start_conversation`) ;
- construit le prompt a partir des 10 derniers messages de la discussion
  (`library_chat_messages`) et de la question — aucune recherche n'est faite
  dans la requete HTTP ;
- cree un job (`llm_jobs`, `kind="library_chat"`, `video_id=null`,
  `conversation_id`) et repond `202 {job_id, status, status_url,
  conversation_id}`, meme mecanique asynchrone (`BackgroundTasks`) que les
  autres jobs LLM.

Les messages envoyes au modele sont construits par
`prompts.py:build_library_chat_prompt` : les 10 derniers messages de la
discussion en vrais tours `user`/`assistant`, puis la question. L'API exige des
tours qui alternent et commencent par `user` : un message qui rompt
l'alternance (question restee sans reponse) est ignore. `llm_jobs.prompt`
contient le `Prompt` en JSON (voir [05](05-modele-de-donnees.md)).

Execution (`back/services/jobs/llm_jobs.py:run_llm_job`) : pour
`kind="library_chat"`, le job passe par
`AnthropicProvider.complete_with_tools(messages, ..., system=...)`, qui boucle tant que le modele
demande un outil. Au-dela de `MAX_TOOL_TURNS` (4) tours d'outils, l'appel
suivant interdit les outils (`tool_choice: none`) pour forcer une reponse.
Chaque tour est un appel API complet : les tokens de tous les appels sont
additionnes dans `input_tokens`/`output_tokens`, donc `cost_usd` couvre
l'echange entier. Le texte, references validees comprises, va dans `llm_jobs.result`, les ids
cites dans `llm_jobs.sources`.

`GET /api/llm-jobs/{job_id}` pour un job `library_chat` :

- meme cycle `pending`/`failed`/`done`→`applied` que les autres jobs LLM ;
- tant que le job est `pending`, la reponse porte
  `tool_calls: [{label, result}]` : les appels
  d'outils faits jusque-la (`llm_jobs.tool_calls`, ecrit par
  `LibraryChatToolbox` a chaque appel via le callback `on_progress` de
  `run_llm_job`). `label` decrit la recherche en cours (« Recherche de la
  chaine « x »… », « Recherche dans les notes generees… »), `result` reste
  `null` tant que l'outil tourne puis devient un resume d'une ligne
  (« Chaine Underscore_ trouvee. », « Aucune video trouvee. ») ;
- a l'application (`done`), insere un message `user` et un message
  `assistant` dans la discussion du job (`library_chat_messages`), ce dernier
  avec les videos (`sources`) et les chaines (`channel_sources`) lues dans
  `llm_jobs.sources`, et avance son `updated_at` ;
- reponse : `library_chat` `{conversation_id, title, messages: [{role,
  content, channels: [{channel_id, name}], citations: [{video_id, title}]},
  ...], conversations: [{id, title, updated_at}], indexed_video_count,
  total_video_count}`, comme `GET /api/chat`. Les chaines et videos
  supprimees depuis la reponse sont retirees de `channels`/`citations`.
  `indexed_video_count`/`total_video_count` disent combien de videos la
  recherche dans les notes peut voir (le widget ne les affiche pas) (une
  video n'est indexee que si ses notes ont ete (re)generees au format a
  sections, voir la section Notes structurees ci-dessus).

`GET /api/chat` : aucune discussion ouverte (`conversation_id` `null`, pas de
message : l'ecran de Raton de l'accueil), meme reponse avec la liste des
discussions. `GET /api/chat/conversations/{id}` : une discussion donnee.
`DELETE /api/chat/conversations/{id}` : supprime la discussion et ses
messages (`204`). Pas de portee par utilisateur.

## Fournisseur LLM

Le fournisseur est choisi uniquement par la variable d'environnement
`LLM_PROVIDER` (voir [04](04-configuration-et-deploiement.md)), lue par
`back/services/llm/provider.py:get_llm_provider` et
`back/services/common/settings.py:get_llm_provider_name`. `anthropic` est la seule
valeur acceptee : `AnthropicProvider` (`back/services/llm/provider.py`) est appele par
`back/services/jobs/llm_jobs.py:run_llm_job`, en tache de fond dans le process
web juste apres la reponse `202` de la demande, jamais de facon
synchrone dans le handler de la requete.

Le client Anthropic est cree avec
  `max_retries=6` (`back/services/llm/provider.py:LLM_MAX_RETRIES`, contre 2 par defaut
  dans le SDK) : ces jobs tournent toujours en tache de fond, donc pas de cout
  UX a retenter plus longtemps sur des erreurs transitoires (429, 5xx, y
  compris `overloaded_error` — HTTP 529, surcharge temporaire cote Anthropic).

L'UI interroge `GET /api/llm-jobs/{job_id}`
jusqu'a resolution (voir plus haut) — la reponse n'est jamais immediate, quel
que soit le fournisseur.

Pendant l'attente, le message de statut affiche quel assistant traite la
demande (`back/services/common/settings.py:get_llm_provider_display_label`, passe au
template via `llm_provider_label`) : `Claude API (claude-haiku-4-5)`
selon le modele configure (`ANTHROPIC_MODEL`).

Les prompts LLM doivent rester orientes transcript et ne doivent pas modifier
le depot.

### Trace des appels dans les logs du conteneur

`back/services/llm/provider.py` ecrit chaque appel a l'API sur le logger
`raton.llm`, envoye sur stderr par
`back/core/logging.py:configure_app_logging` (appele au demarrage) — donc
visible avec `make logs`. Ces lignes ne vont pas dans la page `/logs`, qui
n'affiche que `download_jobs`.

- Appels simples (generation, chat par video) : une ligne avec le
  modele, la taille du prompt, le `stop_reason` et les tokens. Le prompt
  lui-meme n'est pas ecrit (il contient le transcript entier).
- Chat cross-video : la boucle d'outils est tracee tour par tour — le prompt
  complet, puis pour chaque appel API le nombre de messages envoyes, le
  `tool_choice`, le `stop_reason` et les tokens, le texte produit par le
  modele, chaque outil demande avec ses arguments, et le resultat renvoye au
  modele (tronque a 1500 caracteres). Une ligne finale donne le nombre
  d'appels et le total des tokens.

Ces logs contiennent donc les questions posees et des extraits de la
bibliotheque, ce qui est acceptable sur un LAN de confiance (voir
[15 Securite](15-securite.md)).

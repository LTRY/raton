---
title: "09 Transcript et discussion LLM"
---
# 09 Transcript et discussion LLM

## Emplacement UI

Le transcript, le resume et la discussion sont tous integres sur `/videos/{id}`
— aucun des documents LLM n'a de page dediee.

En plus de ces documents, un resume court (3 lignes, genere en meme temps que
le resume complet, voir section Génération ci-dessous) s'affiche directement
sous le titre de la video (`#video-short-summary`), visible sans ouvrir
l'onglet Resume.

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
  Publication/Telechargement/Taille/Transcript ;
- `Segments` (`data-tab="segments"`) : toujours present (jamais `hidden`,
  c'est le seul point d'entree du bouton "Rechercher les segments sponsors") ;
  libelle suffixe du nombre de segments affiches (`Segments (3)`) ; panneau
  HTML independant listant les segments SponsorBlock — voir
  [08 Medias et lecteurs](08-medias-et-lecteurs.md), section "Segments
  sponsorisés" ;
- `Transcript` (`data-tab="raw"`, anciennement libelle `Brut`) : onglet masque
  (`hidden`) si aucun `transcript.txt` n'existe ;
- `Notes structurees` (`data-tab="notes"`) : onglet masque tant que
  `transcript.notes.txt` n'existe pas ;
- `Résumé` (`data-tab="summary"`) : onglet masque tant que
  `transcript.summary.txt` n'existe pas ;
- `.vtt` (`data-tab="vtt"`) : onglet masque si aucun sous-titre `.vtt` lisible
  n'existe pour la video (`video.subtitle_path`) ; panneau HTML independant
  affichant le contenu brut du fichier `.vtt` dans un `pre.transcript-content` ;
- `Commentaire` (`data-tab="personal-notes"`, `id="personal-notes"`) :
  toujours present ; le formulaire renvoie vers `/videos/{id}#personal-notes`
  pour rouvrir l'onglet apres enregistrement ;
- `Analyse IA` (`data-tab="analysis"`) : onglet masque si aucun
  `transcript.txt` n'existe (l'analyse depend du transcript).

Les trois onglets `Transcript`/`Notes structurees`/`Résumé`
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
| `#transcript-analysis` | `Analyse IA` |
| `#personal-notes` | `Commentaire` |
| `#segments-sponsors` | `Segments` |

Affichage additionnel dans le panneau `text` :

- longueur en caracteres du document affiche + son libelle (`Transcript` /
  `Notes structurees` / `Résumé`) ;
- icone de copie discrete en haut a droite de la zone de texte (copie le
  document actuellement affiche ; passe brievement en coche pour confirmer).

### Bouton robot (generation IA)

Le declencheur de la generation (notes + résumé + analyse) ne vit pas dans la
barre d'outils du transcript mais **en haut de la page**, sur la meme ligne
que les actions formats Audio/Vidéo (`.video-detail-action-bar`), pour rester
visible sans defiler jusqu'a la section transcript :

- bouton icone `.ai-generate-button` (robot SVG, rond, sans libelle) qui
  soumet `#generate-form` (`POST /videos/{id}/transcript/generate`) ; il n'est
  rendu que si `transcript.txt` existe ;
- au survol (ou au focus clavier, via `:hover`/`:focus-within` sur
  `.ai-generate`), une infobulle `#ai-generate-tooltip` resume ce que le
  bouton produit : notes structurees, résumé (+ résumé court et questions
  suggerees), analyse de pertinence (clickbait, contenu utile, titres et
  categories suggeres) ;
- l'infobulle contient aussi la case a cocher `Inclure la miniature` (decochee
  par defaut : sans action de l'utilisateur, la miniature n'est pas envoyee
  au LLM et le score clickbait n'est pas calcule ; visible uniquement si une
  miniature locale est disponible pour le fournisseur actif, voir section
  Génération) — elle fait partie du
  formulaire, d'ou l'infobulle interactive (une passerelle CSS comble l'ecart
  bouton/infobulle pour que la souris puisse y entrer) ;
- pendant la generation, le bouton est desactive et son icone est remplacee
  par un spinner (`.ai-generate-loading`) : le libelle ne peut pas etre
  echange comme sur les autres actions LLM, ce qui effacerait le SVG ;
  l'infobulle est masquee tant que le spinner tourne ;
- **la page n'est jamais rechargee** et ne defile pas : des que le job est en
  file, l'onglet `Résumé` s'ouvre (meme s'il n'existait pas encore) et le
  résumé s'y ecrit **mot par mot** au fil de la reponse du LLM ; le résumé
  court s'ecrit de la meme facon sous le titre (`#video-short-summary`) ;
  - le client interroge `GET /videos/{id}/transcript/jobs/{job_id}` toutes
    les 400 ms (2 s pour les autres jobs LLM) et lit `partial_short_summary`/
    `partial_summary` (voir section Jobs LLM asynchrones) ;
  - `createWordStream` (script de `video_detail.html`) revele le texte recu a
    un rythme regulier, decouple du rythme des polls : au moins 14 mots/s,
    plus vite quand le retard grandit ; chaque mot est un `span.stream-word`
    qui apparait en fondu, et un curseur clignotant (`.word-stream.is-streaming`)
    marque l'endroit ou le texte s'ecrit ; avec `prefers-reduced-motion`, les
    mots apparaissent sans fondu ;
  - le spinner du bouton continue de tourner une fois le résumé ecrit, tant
    que les notes et l'analyse (generees ensuite) ne sont pas terminees ;
- a la fin du job, les onglets textuels, le résumé court et les questions
  suggerees sont mis a jour sur place a partir de la reponse
  (`documents_payload`), sans changer l'onglet affiche ; le panneau `Analyse
  IA` est remplace par celui d'un rendu frais de `/videos/{id}` recupere en
  arriere-plan (ses formulaires `Appliquer` dependent des categories
  courantes de la video, d'ou le rendu serveur) ;
- une notification `.toast` (`window.showToast`, voir
  `11-interface-html.md`) annonce la fin : succes (`Notes, résumé et analyse
  générés par l'IA.`) ou erreur ; en cas d'erreur, l'onglet `Résumé` et le
  résumé court retrouvent leur contenu d'avant, et le message est aussi
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

## Génération : notes, résumé et analyse

Notes structurées, résumé (+ résumé court + questions suggérées) et analyse
IA sont les onglets `Notes structurees`, `Résumé` et `Analyse IA` de
`/videos/{id}` (pas de page dédiée). Un résumé court complémentaire (3 lignes) s'affiche en plus,
toujours visible sous le titre de la vidéo (`#video-short-summary`, hors des
onglets), pour donner une idée du contenu sans avoir à ouvrir l'onglet
Résumé. Un seul bouton (le bouton robot en haut de la page, voir "Bouton robot
(generation IA)" ci-dessus) déclenche les trois documents à la fois, en un
seul appel LLM — il n'y a pas de route ni de bouton pour en régénérer un seul
en isolation.

`POST /videos/{id}/transcript/generate` :

- source : `transcript.txt` ;
- champ de formulaire `include_image` (case à cocher `Inclure la miniature`
  côté client, dans l'infobulle du bouton robot) : quand cochée, une miniature locale est jointe à l'appel —
  mais seulement si le fournisseur actif est `anthropic` **et** qu'un fichier
  de miniature existe localement (`app/services/jobs/llm_jobs.py:video_analysis_has_image`) ;
  la case n'est même affichée côté client que si cette condition est vraie ;
  côté serveur, `has_image = bool(include_image) and
  video_analysis_has_image(video, provider)` — un `include_image` forgé
  sans miniature réelle ni fournisseur `anthropic` reste donc sans effet ;
  **la vision est réservée au fournisseur Anthropic**, via
  `AnthropicProvider.complete_with_image`, un bloc image natif de l'API
  Anthropic ; sinon la section clickbait n'est ni demandée ni affichée, sans
  erreur ;
- crée systématiquement un job dans la DB (`llm_jobs`, `kind="generate"`) et
  répond immédiatement `{"status":"queued", "job_id": ..., "estimated_seconds":
  null, "estimated_cost_usd": null}` (pas d'estimation fiable, la sortie
  combinée n'est pas corrélée 1:1 à la longueur d'entrée) — planification
  asynchrone par `BackgroundTasks` ;
- **un seul appel LLM produit les trois documents**, pour n'envoyer le
  transcript qu'une seule fois (`app/services/llm/prompts.py:build_generation_prompt`) :
  le prompt combine les instructions des trois anciens prompts à usage unique
  (`build_notes_prompt`/`build_summary_prompt`/`build_video_analysis_prompt`,
  conservés et toujours utilisables individuellement) sous trois titres
  Markdown de **niveau 1** exacts et dans cet ordre — `# Résumé`, `# Notes`,
  `# Analyse` (le résumé d'abord : c'est lui qui s'affiche pendant que la
  réponse arrive) — chacun suivi des mêmes sous-sections de niveau 2 qu'avant :
  - Notes (apres le résumé dans la réponse) : exactement 6 sections (`NOTES_SECTION_NAMES`) — `## Faits`,
    `## Dates`, `## Lieux`, `## Acteurs`, `## Concepts`, `## Relations
    causales` — chacune en puces, sans rien inventer ; une section sans
    élément pertinent contient le texte fixe "Aucun élément identifié."
    plutôt que d'être omise ;
  - Résumé : `## Résumé court` (exactement 3 lignes, sujet + conclusion
    principale), `## Résumé complet` (texte suivi en paragraphes qui
    restitue sujet/argumentation/conclusions dans un ordre logique, termine
    par 2 à 4 puces de points clés), `## Questions suggérées` (3 à 5
    questions concrètes en puces, pas génériques) ;
  - Analyse : `## Score clickbait` (uniquement si une image est jointe —
    compare miniature/titre au contenu réel), `## Pertinence du contenu`
    (part du contenu qui traite réellement le sujet annoncé, par opposition
    au remplissage), `## Suggestions` (3 titres alternatifs + 1 à 3
    catégories suggérées) ; n'invente rien dans les trois blocs ;
- `app/services/llm/prompts.py:split_generation_result(text, has_image)` découpe
  d'abord la réponse sur les trois titres de niveau 1, puis délègue chaque
  bloc au split_* à usage unique correspondant (`split_notes_sections` en
  interne via l'indexation RAG ci-dessous, `split_summary_result`,
  `split_video_analysis_result`) ; un titre de niveau 1 absent (modèle
  n'ayant pas suivi le format) dégrade proprement vers un résultat vide pour
  ce seul document, sans deviner, comme chaque split_* individuel ;
- le client interroge `GET /videos/{id}/transcript/jobs/{job_id}` jusqu'à
  résolution, qui applique le résultat complet en une fois : écrit
  `transcript.notes.txt`, `transcript.summary.txt` (complet),
  `transcript.summary_short.txt` (court), `transcript.questions.txt` (une
  question par ligne), et sérialise l'analyse dans `video.ai_analysis_json`
  (voir [05 Modèle de données](05-modele-de-donnees.md)) avec un champ
  `generated_at` ajouté à l'application ; répond avec
  `app/web/routes/transcript.py:documents_payload` **et** `app/web/routes/transcript.py:video_analysis_payload`
  fusionnés (`{"status": "generated", "message": "...", ...}`) ; peut être
  régénéré à volonté, ce qui écrase les quatre fichiers et le JSON précédent
  en entier ;
- redirige vers `/videos/{id}?message=...#transcript` (requêtes non-fetch) ;
- en cas d'erreur, redirige avec `level=error`.

**Génération automatique** : le bouton robot n'est plus le seul moyen d'obtenir
des notes. Un lot nocturne (`auto_notes`, voir
[13 Jobs, logs et planification](13-jobs-logs-planification.md)) produit, pour
les vidéos qui n'en ont pas, **les notes structurées et le résumé court
seulement** (`app/services/llm/prompts.py:build_auto_notes_prompt`, mêmes instructions
de notes et de résumé court que ci-dessus, sans résumé complet, questions ni
analyse) et écrit `transcript.notes.txt` et `transcript.summary_short.txt`
(jamais écrasé s'il existe déjà : un résumé généré à la main prévaut). Le
résultat est appliqué par le service lui-même, pas par le polling de cette
route. Le résumé court s'affiche donc sous le titre sans clic ; le bouton robot
reste le seul moyen d'obtenir le résumé complet et l'analyse, et il regénère
tout, y compris ces deux fichiers.

**Indexation RAG cross-video** : dès que le job `generate` est appliqué, une
tâche `BackgroundTasks` découpe le seul bloc `# Notes` (pas le texte combiné
entier) en chunks par section (`app/services/llm/prompts.py:split_notes_sections`,
sections vides/placeholder ignorées), les embed via l'API Voyage
(`app/services/rag/embeddings.py`, `EMBEDDING_MODEL`, 1024 dimensions,
`VOYAGE_API_KEY`), chaque section précédée du titre de la vidéo et de sa
chaîne, et remplace les lignes existantes de `video_note_chunks`
pour cette vidéo (`app/services/rag/indexing.py:index_video_notes`) ; le **résumé court**
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
indexe pas rétroactivement, il faut recliquer sur "Générer notes, résumé et
analyse". Voir [05 Modèle de données](05-modele-de-donnees.md).

`POST /videos/{id}/apply-title` : écrit `video.title` à partir d'un des 3
titres de `ai_analysis_json.suggested_titles` ou d'un titre tapé à la main
(`title_choice`/`title_custom`, un bouton radio par titre suggéré plus une option libre) ; ajoute un suffixe ` ✨` (choix
IA) ou ` ✏️` (choix manuel), en remplaçant un suffixe existant plutôt que de
l'empiler ; rejette une soumission vide (aucune écriture, redirection
`level=error`) ;
formulaire simple (pas de fetch/AJAX), comme le commentaire. Les catégories suggérées n'ont pas de route
dédiée : chaque catégorie suggérée est un bouton qui soumet le formulaire
existant `POST /videos/{id}/categories` avec la catégorie suggérée ajoutée à
la liste des catégories déjà cochées (union, jamais de remplacement). Le
panneau Analyse IA (voir « Section transcript » ci-dessus)
affiche un message d'invite à utiliser le bouton robot 🤖 en haut de la page
tant qu'aucune analyse n'a encore été générée pour cette vidéo.

## Jobs LLM asynchrones

`GET /videos/{id}/transcript/jobs/{job_id}`

- s'applique a tous les jobs `llm_jobs`, quel que soit le fournisseur
  (traites en tache de fond dans le process web via
  `app/services/jobs/llm_jobs.py:run_llm_job`) ;
- tant que le job est `queued`/`running`, repond `{"status": "pending"}` ;
  pour un job `generate` dont la reponse a commence a arriver, la reponse
  porte en plus `partial_short_summary` et `partial_summary` : le résumé court
  et le résumé complet tels qu'ecrits jusque-la
  (`app/services/llm/prompts.py:partial_generation_summary`). Ces deux valeurs ne font
  que s'allonger d'un poll au suivant (un titre Markdown en cours d'ecriture
  n'y apparait jamais), ce qui permet au client de n'ajouter que la suite ;
  `run_llm_job` enregistre pour cela le texte recu dans `llm_jobs.result`
  toutes les 0,4 s pendant que le job `generate` est `running` — `result`
  n'est la reponse complete qu'une fois le job `done` ;
- si le job a echoue, repond en 400 avec un message d'erreur explicite
  (`Génération` ou `Réponse` selon `kind`) ;
- des que le job est termine (`done`), applique le resultat une seule fois
  (ecrit `transcript.notes.txt`/`transcript.summary.txt`+`transcript.summary_short.txt`/
  `transcript.questions.txt` et serialise `video.ai_analysis_json` pour
  `generate` ; ajoute question/reponse a `transcript.chat.json` pour `chat` —
  voir sections Génération/Discussion ci-dessus), passe le job a
  `applied`, puis repond avec `documents_payload` **et** `video_analysis_payload`
  fusionnés (`generate`), ou `chat_payload` (`chat`). Un nouveau poll sur un
  job deja `applied` renvoie l'etat courant sans ré-appliquer (idempotent).

`documents_payload(video)` renvoie l'etat complet des 3 onglets textuels de
`/videos/{id}` a chaque reponse (generate), pour que le client
resynchronise tous ses onglets (et le resume court sous le titre) en une fois
quelle que soit l'action déclenchee :

```json
{
  "transcript": "...", "transcript_length": 0,
  "notes_transcript": "...", "notes_length": 0, "has_notes": false,
  "summary_transcript": "...", "summary_length": 0, "has_summary": false,
  "short_summary": "..."
}
```

## Cout reel des jobs LLM

`app/services/jobs/llm_jobs.py:run_llm_job` enregistre le cout **reel** sur chaque `LlmJob` des
que la completion reussit, a partir de l'usage exact renvoye par le
fournisseur lui-meme (`response.usage` du SDK Anthropic,
`app/services/llm/provider.py:CompletionResult`) :

- `model`, `input_tokens`, `output_tokens` : tels que rapportes par l'API,
  peu importe le nombre reel de caracteres du prompt/de la reponse ;
  `input_tokens` = tout ce qui est envoye (tokens non caches + lectures et
  ecritures de cache), `output_tokens` inclut les tokens de reflexion
  (adaptive thinking), factures comme de la sortie ;
- `cost_usd` : somme **appel par appel** (`app/services/llm/provider.py:UsageTally`,
  `app/services/llm/usage.py:compute_call_cost_usd`) contre le tarif du modele
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
  par `max_tokens`, ou vide : `app/services/llm/provider.py:CompletionFailed`) — ces
  tokens sont factures meme si le job echoue, donc comptes. Un echec reseau
  ou API en cours de route n'est pas reconstitue.

Le plafond de tokens de sortie (`max_tokens`) depend du modele
(`app/services/llm/usage.py:max_output_tokens` : 64 000 pour Haiku 4.5 qui
refuse davantage, 128 000 pour les autres modeles connus, 64 000 pour un
modele inconnu). Avec Haiku 5.5, la reflexion adaptative (effort `medium` par
defaut) consomme une partie de ce plafond et du cout de sortie.

`/settings` (section "Couts LLM") affiche le cumul par type de job puis par
modele (`app/services/llm/usage.py:llm_usage_summary`) : nombre de jobs,
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

`POST /videos/{id}/transcript/chat`

- refuse les questions vides par redirection simple ;
- lit `transcript.txt` ;
- charge `transcript.chat.json` ;
- cree systematiquement un job dans la DB (`kind="chat"`, la question brute est
  conservee a part pour etre ajoutee a l'historique une fois la reponse
  obtenue) et repond immediatement `{"status":"queued","job_id":...}`, sans
  jamais bloquer la requete ;
- planifie `app/services/jobs/llm_jobs.py:run_llm_job` via `BackgroundTasks` ; voir la section
  jobs LLM asynchrones ci-dessus pour la resolution ;
- redirige vers `/videos/{id}#discussion`.

`POST /videos/{id}/transcript/chat/clear`

- supprime `transcript.chat.json` si present ;
- redirige vers `/videos/{id}#discussion`.

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

Definis dans `app/services/rag/library_chat_tools.py` (`LIBRARY_CHAT_TOOLS`,
executes par `LibraryChatToolbox`) :

- `chercher_chaines(requete)` : recherche textuelle par mots, insensible a la
  casse et aux accents, sur le nom, les labels, l'URL et l'identifiant YouTube
  des chaines — la meme que le champ de recherche de `/channels`
  (`app/services/common/search.py:channel_search_rank`). Sans requete, liste toutes
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
  `app/services/rag/retrieval.py:retrieve_relevant_chunks` embed la requete
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
  d'historique (`app/services/videos/playback.py:dashboard_media_activity_logs`). `jours`
  (30 par defaut) borne la fenetre, `requete` filtre sur le titre ou la
  chaine. Chaque ligne donne la reference de la video et de sa chaine, la date
  et l'heure de lecture, la position (ou « terminee »), la duree et le temps
  regarde ; une video supprimee de la bibliotheque reste listee par le titre
  enregistre, sans reference. 30 resultats au plus ; 500 lectures lues au
  plus avant regroupement ;
- `chercher_sur_youtube(requete)` : cherche sur YouTube des chaines par nom
  (`app/services/youtube/channel_info.py:search_channels`, voir
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
`[chaine:ID]` ou `[video:ID]`. Le prompt
(`app/services/llm/prompts.py:build_library_chat_prompt`) demande au modele d'ecrire,
a l'endroit ou il en parle, le nom de chaque chaine ou video qu'il retient
sous la forme `[[chaine:ID|Nom]]` / `[[video:ID|Titre]]` : le texte affiche
est le nom, la syntaxe disparait a l'affichage (voir
[11](11-interface-html.md)). `LibraryChatToolbox.extract_sources` valide
ensuite ces references, **sans les retirer** : une reference vers un id
« garanti » reste dans `content`, vers un autre id (le modele ne peut pas
faire apparaitre un element invente) elle est remplacee par son seul libelle
(supprimee s'il n'y en a pas). Un id est garanti quand un outil l'a renvoye
pendant ce job **ou** qu'une reponse precedente de la discussion l'a deja cite
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

### Routes

`POST /chat` (`question` en form-data) :

- refuse les questions vides (`{"status":"failed",...}`, 400) ;
- construit le prompt a partir des 10 derniers messages du fil
  (`library_chat_messages`) et de la question — aucune recherche n'est faite
  dans la requete HTTP ;
- cree un job (`llm_jobs`, `kind="library_chat"`, `video_id=null`) et repond
  `{"status":"queued","job_id":...}`, meme mecanique asynchrone
  (`BackgroundTasks`) que les autres jobs LLM.

Execution (`app/services/jobs/llm_jobs.py:run_llm_job`) : pour
`kind="library_chat"`, le job passe par
`AnthropicProvider.complete_with_tools`, qui boucle tant que le modele
demande un outil. Au-dela de `MAX_TOOL_TURNS` (4) tours d'outils, l'appel
suivant interdit les outils (`tool_choice: none`) pour forcer une reponse.
Chaque tour est un appel API complet : les tokens de tous les appels sont
additionnes dans `input_tokens`/`output_tokens`, donc `cost_usd` couvre
l'echange entier. Le texte, references validees comprises, va dans `llm_jobs.result`, les ids
cites dans `llm_jobs.sources`.

`GET /chat/jobs/{job_id}` :

- meme cycle `pending`/`failed`/`done`→`applied` que
  `GET /videos/{id}/transcript/jobs/{job_id}`, mais sans `video_id` dans
  l'URL — verifie `job.kind == "library_chat"` et `job.video_id is None` ;
- tant que le job est `pending`, la reponse est
  `{"status":"pending","tool_calls":[{"label","result"}]}` : les appels
  d'outils faits jusque-la (`llm_jobs.tool_calls`, ecrit par
  `LibraryChatToolbox` a chaque appel via le callback `on_progress` de
  `run_llm_job`). `label` decrit la recherche en cours (« Recherche de la
  chaine « x »… », « Recherche dans les notes generees… »), `result` reste
  `null` tant que l'outil tourne puis devient un resume d'une ligne
  (« Chaine Underscore_ trouvee. », « Aucune video trouvee. ») ;
- a l'application (`done`), insere un message `user` et un message
  `assistant` dans `library_chat_messages`, ce dernier avec les videos
  (`sources`) et les chaines (`channel_sources`) lues dans `llm_jobs.sources` ;
- reponse : `{"status":"ok","message":...,"messages":[{"role","content",
  "channels":[{"channel_id","name"}],"citations":[{"video_id","title"}]},...],
  "indexed_video_count":N,"total_video_count":M}`. Les chaines et videos
  supprimees depuis la reponse sont retirees de `channels`/`citations`.
  `indexed_video_count`/`total_video_count` alimentent la note de couverture
  du widget : combien de videos la recherche dans les notes peut voir (une
  video n'est indexee que si ses notes ont ete (re)generees au format a
  sections, voir la section Notes structurees ci-dessus).

`POST /chat/clear` : vide entierement `library_chat_messages` (fil unique,
pas de portee par utilisateur).

## Fournisseur LLM

Le fournisseur est choisi uniquement par la variable d'environnement
`LLM_PROVIDER` (voir [04](04-configuration-et-deploiement.md)), lue par
`app/services/llm/provider.py:get_llm_provider` et
`app/services/common/settings.py:get_llm_provider_name`. `anthropic` est la seule
valeur acceptee : `AnthropicProvider` (`app/services/llm/provider.py`) est appele par
`app/services/jobs/llm_jobs.py:run_llm_job`, en tache de fond dans le process
web juste apres la reponse `{"status":"queued",...}`, jamais de facon
synchrone dans le handler de la requete.

Le client Anthropic est cree avec
  `max_retries=6` (`app/services/llm/provider.py:LLM_MAX_RETRIES`, contre 2 par defaut
  dans le SDK) : ces jobs tournent toujours en tache de fond, donc pas de cout
  UX a retenter plus longtemps sur des erreurs transitoires (429, 5xx, y
  compris `overloaded_error` — HTTP 529, surcharge temporaire cote Anthropic).

L'UI interroge `GET /videos/{id}/transcript/jobs/{job_id}`
jusqu'a resolution (voir plus haut) — la reponse n'est jamais immediate, quel
que soit le fournisseur.

Pendant l'attente, le message de statut affiche quel assistant traite la
demande (`app/services/common/settings.py:get_llm_provider_display_label`, passe au
template via `llm_provider_label`) : `Claude API (claude-haiku-4-5)`
selon le modele configure (`ANTHROPIC_MODEL`).

Les prompts LLM doivent rester orientes transcript et ne doivent pas modifier
le depot.

### Trace des appels dans les logs du conteneur

`app/services/llm/provider.py` ecrit chaque appel a l'API sur le logger
`raton.llm`, envoye sur stderr par
`app/core/logging.py:configure_app_logging` (appele au demarrage) — donc
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

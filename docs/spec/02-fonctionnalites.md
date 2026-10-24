---
title: "02 Fonctionnalites"
---
# 02 Fonctionnalites

## Accueil

La page `/` ne contient que la barre de chat de la bibliotheque, en bas de
l'ecran.

## Bibliotheque : Nouveautes, Historique, Exploration

L'onglet central **Bibliotheque** regroupe trois vues (l'import se fait depuis le bouton rond en haut a droite,
voir [11 Interface HTML](11-interface-html.md)) :

- **Nouveautes** (`/dashboard/nouveautes`) : une pile de videos recentes par
  chaine suivie (au moins une des deux cloches active), pas seulement les fiches
  marquees `is_new` — une fiche deja visitee reste affichee tant qu'elle
  fait partie des plus recentes de sa chaine. Chaque cloche filtre son
  type : la pile ne montre les videos que si la cloche videos est active,
  et les shorts que si la cloche shorts est active. Paginee par chaine (10
  chaines par page) ;
- **Historique** (`/dashboard/historique`) : activite de lecture recente,
  groupee par journee, paginee ; une ligne montre la progression de lecture
  tant que la video n'est pas terminee, et une video vue en entier est grisee
  (regles dans [11 Interface HTML](11-interface-html.md)) ;
- **Exploration** (`/videos`) : la liste complete de la bibliotheque.

Les statistiques de la bibliotheque (nombre de chaines, fiches, transcripts,
stockage) et le temps de lecture par type de media sont dans `/settings`.

### Import d'un fichier local

La feuille d'import de la Bibliotheque (telechargement manuel d'une video
par URL, avec le choix des formats et de la qualite) accepte aussi un fichier video ou audio depose depuis
l'appareil (glisser-deposer ou selecteur). Il est range sous la chaine
`Fichiers locaux`, sans transcript ni metadonnees YouTube ; un contenu deja
importe n'est pas duplique. Voir `POST /videos/upload` dans
[12 API et routes](12-api-et-routes.md).

## Chaines

Fonctionnalites :

- lister les chaines ;
- ajouter une chaine depuis une URL ou un `@handle` (avec categories) ;
- chercher sur YouTube une chaine absente de la bibliotheque a partir de son
  nom, et choisir parmi les candidates (avatar, handle, abonnes) laquelle
  ajouter ;
- demander l'ajout d'une chaine a l'assistant du dashboard ("ajoute la chaine
  de X") ;
- importer en masse des chaines depuis un CSV d'abonnements YouTube (export
  Google Takeout) : depot du fichier, apercu des chaines trouvees avec
  detection de celles deja presentes dans la DB, selection/deselection, puis
  creation des chaines cochees ;
- noter une chaine sur 5 étoiles ;
- modifier les categories d'une chaine ;
- activer/desactiver les deux cloches de suivi quotidien (sur la liste des
  chaines et sur la page de chaque chaine) : une pour les
  videos (`auto_metadata_enabled`), une pour les shorts
  (`auto_shorts_enabled`) ;
- supprimer une chaine : bouton « Supprimer la chaîne » sur la page de la
  chaine (`/videos?channel_id={id}`), qui deplie d'abord un avertissement
  detaillant ce qui sera supprime (la chaine, ses fiches, leurs notes,
  discussions, transcriptions indexees, segments sponsor et entrees de
  playlist) et ce qui reste (fichiers deja telecharges sur le disque, journaux
  et historique de lecture) ; la suppression n'a lieu qu'apres confirmation.
  La page liste des chaines n'a pas de bouton de suppression ;
- naviguer vers `/videos?channel_id={id}` (voir « Page d'une chaine » dans
  [11 Interface HTML](11-interface-html.md)), dont le menu « ⋯ » affiche une
  estimation de periodicite de publication sous forme de taux compact ("~3,5/sem" ou
  "~1,3/mois" selon la frequence), calculee a partir de l'ecart median entre
  les `published_at` connus de la chaine ; `null`/non affichee s'il y a moins
  de deux fiches datees.

Il n'y a pas de toggle "activer/desactiver une chaine" independant des
cloches.

Contraintes :

- l'ajout de chaine depuis une URL doit extraire `name` et `yt_channel_id`
  avec `yt-dlp` ; l'import CSV, lui, n'appelle pas `yt-dlp` et prend
  directement `name`/`url`/`yt_channel_id` du fichier (deja canoniques dans
  un export Google Takeout) ;
- l'URL de chaine est unique ;
- supprimer une chaine supprime ses fiches par cascade DB, et ses
  fichiers de profil (avatar, banniere). Les fichiers audio/video deja
  telecharges ne sont pas touches : ils restent sur le disque, orphelins
  (invisibles dans l'application et hors quota), et ne s'effacent qu'a la main.

### Cloches de suivi quotidien

Chaque chaine a deux cloches independantes, desactivees par defaut : une pour
les videos (`auto_metadata_enabled`) et une pour les shorts
(`auto_shorts_enabled`). On peut suivre l'une, l'autre, ou les deux.

- Activer une cloche declenche immediatement un import metadata en
  arriere-plan pour la chaine (page 1, section de cette cloche : videos ou
  shorts) afin de synchroniser le catalogue existant ; ces fiches ne sont pas
  marquees `is_new`.
- Desactiver une cloche n'efface pas les fiches deja marquees `is_new`.
- Tant qu'une cloche est active, le scan quotidien planifie importe aussi les
  nouvelles fiches de sa section et les marque `is_new = true` (voir
  [13 Jobs, logs et planification](13-jobs-logs-planification.md)).
- Le label technique **Nouveau** est affiche sur une fiche tant que
  `is_new = true`. Visiter la page detail de la video (`/videos/{id}`) retire
  automatiquement ce label — la fiche reste neanmoins visible dans la pile de
  sa chaine (section Nouveautes), seul le label disparait.

## Playlists

Fonctionnalites :

- creer une playlist a la main (titre seul), puis en retirer/reordonner
  les videos depuis sa page ;
- previsualiser une playlist avant de l'importer par URL : nombre de
  videos, duree totale (minorant : YouTube ne donne pas toujours la duree de
  chaque entree), videos deja en bibliotheque, videos indisponibles et
  premiers titres ; l'import ne part qu'apres confirmation ;
- importer une playlist depuis une URL YouTube : cree la playlist
  immediatement, puis importe les metadonnees de chaque video en
  arriere-plan (jamais le media video/audio, qui reste un telechargement
  separe comme pour une chaine) ;
- importer une playlist depuis un CSV Google Takeout (un fichier
  `Vidéos de <Titre>.csv` a la fois — l'export complet en contient un par
  playlist, plus un `playlists.csv` global non exploite ici) ;
- ajouter une video a une playlist (existante ou creee a la volee) depuis la
  page detail de la video — seul moyen d'ajout manuel ;
- donner des categories a une playlist : les videos qui n'ont aucun label les
  recoivent, comme celles d'une chaine (voir
  [05 Modele de donnees](05-modele-de-donnees.md)) ;
- supprimer une playlist ne supprime jamais les videos qu'elle contenait,
  seulement le rattachement.

Contraintes :

- une playlist importee est un instantane : pas de re-synchronisation
  periodique ("cloche") comme pour les chaines ; relancer un import plus
  tard pour rattraper de nouveaux ajouts est une action manuelle ;
  l'import CSV comme l'import URL sont idempotents (relancer n'importe/ne
  duplique que ce qui manque, `import_video_metadata` reconnait une video
  deja connue par `yt_video_id`) ;
- une meme video peut appartenir a plusieurs playlists, et a la fois etre
  rattachee normalement a sa chaine — ce sont deux rattachements
  independants ;
- voir [05 Modele de donnees](05-modele-de-donnees.md),
  [07 YouTube et telechargements](07-youtube-et-telechargements.md) et
  [13 Jobs, logs et planification](13-jobs-logs-planification.md) pour le
  detail technique des deux flux d'import.

## Videos

La page `/videos` permet :

- telechargement manuel par URL (feuille d'import) ;
- choix du format initial : video ou audio (M4A) ;
- choix de la qualite video (`360p` a `2160p`/meilleure disponible, defaut
  `1080p`), sur le formulaire manuel et sur le formulaire "Telecharger video"
  de la page detail ;
- choix de telecharger le transcript ;
- filtrage par chaine ;
- recherche par mots (insensible aux accents) ;
- tri : import recent, publication recente, les plus vues ou les mieux notees ;
- etat Vu/Ecartee par video, et vues sauvegardees ;
- listing des fiches locales ;
- explorer une chaine : sur la page d'une chaine, le bouton « Explorer la
  suite » importe depuis YouTube les fiches suivantes (par pages), sans
  telecharger le media ;
- import metadata d'une video non locale (par URL, ou via le partage iOS) ;
- notes sur 5 étoiles.

Il n'y a pas de filtre min/max de vues ; le tri "les plus vues" couvre ce
besoin. Sur la page d'une chaine, les shorts sont presentes en mosaique (les
nouveaux et les notes 5 en grandes tuiles, plus une tuile sur 7, avec au moins
5 petites tuiles entre deux grandes)
et les videos en grille de cartes.
La page s'ouvre sur les shorts quand seule la cloche shorts de la chaine est
active (un `section` explicite dans l'URL l'emporte).
Les sous-bibliotheques configurables (`library_views`, reglables depuis
`/settings`) sont des liens du menu de la Bibliotheque (tiroir ☰ sur telephone, colonne
a gauche sur bureau, sur Nouveautes, Historique et Exploration), pas de la page
d'une chaine.

## Detail video

La page `/videos/{id}` est la page centrale d'un contenu.

Elle affiche :

- labels de disponibilite : Audio, Video, Metadonnees, Transcript ;
- titre, et sous lui le resume court de 3 lignes quand il existe ;
- chaine ou `Telechargement manuel` ;
- notation sur 5 étoiles ;
- lecteur video si `video_path` existe ;
- lecteur audio si `audio_path` existe (natif si combine avec une video, sinon
  bouton vers le mini-lecteur persistant — voir
  [08 Medias et lecteurs](08-medias-et-lecteurs.md)) ;
- publication, telechargement, taille, statut transcript ;
- boutons de telechargement des formats manquants ;
- une barre d'onglets (informations, segments, transcript, notes,
  commentaire…), detaillee dans
  [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md) ; l'onglet
  **Segments** est decrit ci-dessous ;
- section discussion LLM.

### Segments sponsorises

Les segments sponsorises (sponsor, auto-promotion, rappel abonnement/like,
intro, outro) ont leur propre onglet **Segments** sur `/videos/{id}`, toujours
visible, libelle avec le nombre de segments affiches (`Segments (3)`).

Source (SponsorBlock), recuperation, categories, saut automatique et seek
manuel : voir [08 Medias et lecteurs](08-medias-et-lecteurs.md), section
« Segments sponsorises ».

## Medias

Un meme enregistrement `Video` peut avoir :

- seulement des metadonnees ;
- metadonnees + transcript ;
- audio seulement ;
- video seulement ;
- audio + video ;
- audio + video + transcript.

Les bascules audio/video de la fiche et des cartes refletent toujours les
fichiers presents (voir « Ajouter audio et video » dans
[01 Parcours et utilisateurs](01-parcours-et-utilisateurs.md)).

## Transcript et LLM

Fonctionnalites :

- afficher 2 documents en onglets (Transcript / Notes structurees) ;
- compter les caracteres du document affiche ;
- copier le document affiche ;
- lancer la generation (bouton robot en haut de la fiche) : notes structurees,
  resume court et questions suggerees ;
- les notes structurees (faits, dates, lieux, acteurs, relations
  causales) sont produites a partir du transcript ;
  un label technique **Notes** s'affiche sur la carte video et sur la page
  detail des lors que `transcript.notes.txt` existe (voir
  [11 Interface HTML](11-interface-html.md)) ;
- generer un resume narratif (onglet Résumé) et un resume court de 3 lignes
  affiche en permanence sous le titre de la video, tous deux produits en un
  seul appel LLM toujours a partir du transcript ;
- discuter du contenu d'une video, ou de toute la bibliotheque (chat cross-video,
  voir [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)) ;
- generer chaque nuit les notes structurees et un resume court des videos qui
  n'en ont pas (lot Anthropic, 100 par nuit, reglable dans `/settings`, hors
  shorts et hors categories exclues) : c'est ce qui rend les videos
  cherchables par le chat bibliotheque sans cliquer sur le robot ;
- effacer la discussion d'une video ; pour le chat bibliotheque, ouvrir une
  nouvelle discussion, rouvrir ou supprimer une des precedentes.

Les fichiers associes :

- `transcript.txt` : transcript converti depuis les sous-titres ;
- `transcript.notes.txt` : notes structurees ;
- `transcript.summary_short.txt` : resume court (3 lignes) ;
- `transcript.questions.txt` : questions suggerees par l'IA (une par ligne) ;
- `transcript.chat.json` : historique de discussion.

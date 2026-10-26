---
title: "01 Parcours et utilisateurs"
---
# 01 Parcours et utilisateurs

## Utilisateurs

L'utilisateur principal est l'operateur local de Raton. Il utilise
l'application depuis la machine hote ou depuis une machine du LAN. Ses objectifs
sont ceux de [00 Vision](00-vision.md).

D'autres personnes du foyer peuvent partager l'instance : chacune a son
utilisateur, qui garde pour lui ce qui est personnel (Vu, etoiles, playlists,
discussions...) et partage les medias et les notes generees (voir
[02 Fonctionnalites](02-fonctionnalites.md), « Utilisateurs »). Les donnees
d'avant les utilisateurs appartiennent au premier, « Moi ».

### Changer d'utilisateur

1. Sur l'accueil `/`, l'utilisateur ouvre le tiroir « Discussions » (☰).
2. En bas a gauche, le bouton rond porte l'initiale de l'utilisateur courant ;
   il ouvre sa page `/user` (« Paramètres de l'utilisateur »), qui liste les
   utilisateurs sous « Changer d'utilisateur ».
3. Choisir un nom recharge l'accueil pour lui : ses discussions, sa phrase de
   Raton, et sur les autres pages ses Nouveautes, son historique, ses notes et
   ses playlists. Le choix est garde par le navigateur.
4. « Nouvel utilisateur » + « Ajouter » cree un utilisateur et le choisit.
5. Se renommer : carte « Nom » de `/user` ; renommer ou supprimer n'importe
   quel utilisateur : section « Utilisateurs » de `/settings`.

### Paramètres de l'utilisateur

La page `/user` porte ce qui est propre a l'utilisateur courant : son nom, le
changement d'utilisateur, la facon dont Raton lui parle dans le chat
bibliotheque (tutoiement ou vouvoiement, surnom) et son couvre-feu.

## Parcours principaux

### Ajouter une chaine

1. L'utilisateur ouvre `/channels`, puis la feuille d'import (bouton rond en
   haut a droite).
2. Il saisit l'URL ou le `@handle` de la chaine, ou son nom : pour un nom,
   l'application liste les chaines YouTube correspondantes et il choisit
   laquelle ajouter.
3. L'application extrait le nom et l'identifiant de chaine via `yt-dlp`.
4. La chaine apparait dans la liste, sans suivi automatique : ses deux cloches
   (videos, shorts) sont eteintes.
5. Activer une cloche lance tout de suite l'import des metadonnees du catalogue
   de cette section, puis le scan quotidien de 3h la surveille (voir
   « Suivre les nouveautes »).

### Parcourir la bibliotheque

1. L'utilisateur ouvre `/videos` : la liste des videos deja dans la DB, avec
   filtres, tri, recherche par mots et etat Vu/Indesiree.
2. Choisir une chaine ouvre sa page dediee (`/videos?channel_id=...`).
3. Sur la page d'une chaine, « Explorer la suite » importe depuis YouTube les
   fiches suivantes (par pages), sans telecharger les medias.
4. Une video absente de la DB s'ajoute aussi en collant son URL
   (feuille d'import) ou via le partage iOS (`/videos/share-import`).
5. Une video connue ouvre sa fiche `/videos/{id}`.

### Importer un fichier local ou une playlist

1. Dans la feuille d'import, l'utilisateur depose un fichier video ou audio de son
   appareil : il est range sous la chaine `Fichiers locaux`, sans transcript ni
   metadonnees YouTube.
2. Ou il colle l'URL d'une playlist YouTube : l'application en affiche un apercu
   (nombre de videos, duree, videos deja presentes) et n'importe qu'apres
   confirmation. Seules les metadonnees sont importees, jamais les medias.
3. Une playlist peut aussi etre creee a la main ou importee depuis un CSV Google
   Takeout.

### Ajouter audio et video

1. Sur la fiche `/videos/{id}` (et sur les cartes), l'audio et la video ont
   chacun une bascule.
2. Une bascule inactive lance le telechargement de ce format ; une bascule
   active indique que le format est deja present (la cliquer le supprime quand
   la suppression est autorisee).
3. Ajouter un format ne supprime jamais l'autre.
4. Apres telechargement, le format est disponible dans la fiche locale.

### Lire

1. L'utilisateur ouvre `/videos/{id}`.
2. Selon les formats presents, il lit la video ou l'audio directement dans la
   page, avec les lecteurs natifs du navigateur.
3. Sur iPhone/Safari, la lecture audio peut continuer ecran eteint lorsque
   Safari l'autorise.
4. La position de lecture est enregistree : elle alimente la barre de
   progression des cartes et l'historique.

Le detail technique (flux, `Range`, mini-lecteur) est dans
[08 Medias et lecteurs](08-medias-et-lecteurs.md).

### Utiliser le transcript

1. L'utilisateur ouvre `/videos/{id}`.
2. La section `Transcript` est sur la meme page, sous les lecteurs et les faits.
3. Si un transcript existe, l'utilisateur peut le copier.
4. S'il n'existe pas, il peut en generer un.
5. Il peut generer des notes, indexees pour la recherche de la bibliotheque.
6. Il peut poser des questions dans la section `Discuter du contenu`.
7. Les anciennes URLs `/videos/{id}/transcript` redirigent vers
   `/videos/{id}#transcript`.

### Discuter de la bibliotheque

1. L'utilisateur pose une question depuis la barre de chat de l'accueil `/`,
   ou en choisissant la portee « Toute la bibliotheque » sur une fiche.
2. Le modele cherche lui-meme ce dont il a besoin (chaines, videos, notes) et
   peut ajouter une chaine YouTube a la bibliotheque.
3. La reponse cite les chaines et videos concernees, qui renvoient vers leurs
   pages Raton.

### Suivre les nouveautes

1. L'utilisateur active la cloche videos et/ou shorts d'une chaine.
2. Chaque nuit, l'application importe les nouvelles fiches de ces chaines.
3. `Bibliotheque > Nouveautes` affiche les fiches des chaines suivies, avec la recherche et les filtres d'Exploration.
4. Ouvrir la fiche d'une video nouvelle la retire des nouveautes marquees.

### Noter et trier une video

1. Sur une fiche ou une carte, l'utilisateur donne une note sur 5 etoiles.
2. Il peut lui attribuer des categories et renseigner son intention de
   visionnage.
3. Il peut la marquer Vu ou la cacher de la liste.
4. Une note de 4 ou 5 protege ses fichiers de la purge (voir « Gerer le
   stockage »).

### Retrouver son historique

1. `Bibliotheque > Historique` liste les lectures recentes, groupees par jour.
2. Une carte ou une ligne montre sa progression tant que la video n'est pas
   terminee.
3. Le temps de lecture par type de media est dans `/settings`.

### Gerer le stockage

1. L'utilisateur configure le quota global dans `/settings`.
2. Pres du quota, les telechargements automatiques s'arretent.
3. Une video vue a 90 % voit ses fichiers audio/video supprimes 7 jours plus
   tard, sauf si elle est notee 4 ou 5. Le transcript, les notes et la fiche
   sont conserves.
4. L'utilisateur peut aussi supprimer un format a la main, ou retelecharger une
   video purgee.

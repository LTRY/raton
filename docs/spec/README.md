---
title: "Cahier des charges Raton"
slug: index
---
# Cahier des charges Raton

Ce dossier est la specification fonctionnelle et technique de Raton. Il
doit permettre de reconstruire l'application de zero sans surprise entre la
specification et le code.

## Regle de maintenance obligatoire

Avant toute modification fonctionnelle ou technique, la personne ou l'agent
LLM qui modifie le depot doit :

1. Lire les fichiers de `docs/spec/` concernes par le changement.
2. Modifier le code et la specification dans le meme changement.
3. Ajouter ou ajuster les tests qui prouvent le comportement attendu.
4. Executer les tests pertinents, puis la suite complete si le changement touche
   une surface partagee.
5. Executer `make ci`, puis ouvrir une pull request vers `main` sur le depot
   GitHub. Le changement n'est pas deploye a cette etape.

Chaque fichier de ce dossier commence par un frontmatter YAML avec un `title`
egal a son premier `# ...` (le site de documentation en depend) : une nouvelle
spec sans `title` fait echouer `tests/test_docs_spec.py`. Le site est decrit
dans [04 Configuration et deploiement](04-configuration-et-deploiement.md).

Une modification du code qui rend cette specification fausse est incomplete.
Une modification de specification qui n'est pas refletee dans le code est aussi
incomplete, sauf si elle est explicitement marquee comme cible future.

## Arborescence

- [00 Vision](00-vision.md)
- [01 Parcours et utilisateurs](01-parcours-et-utilisateurs.md)
- [02 Fonctionnalites](02-fonctionnalites.md)
- [03 Architecture](03-architecture.md)
- [04 Configuration et deploiement](04-configuration-et-deploiement.md)
- [05 Modele de donnees](05-modele-de-donnees.md)
- [06 Stockage fichiers](06-stockage-fichiers.md)
- [07 YouTube et telechargements](07-youtube-et-telechargements.md)
- [08 Medias et lecteurs](08-medias-et-lecteurs.md)
- [09 Transcript et discussion LLM](09-transcript-et-discussion-llm.md)
- [10 Services](10-services.md)
- [11 Interface HTML](11-interface-html.md)
- [12 API et routes](12-api-et-routes.md)
- [13 Jobs, logs et planification](13-jobs-logs-planification.md)
- [15 Securite](15-securite.md)
- [16 Tests et criteres d'acceptation](16-tests-et-criteres.md)
- [17 Roadmap et limites connues](17-roadmap-et-limites.md)
- [18 Raton : scénarios et répliques](18-raton-scenarios.md)
- [19 Indexation et recherche dans les notes](19-indexation-et-recherche-notes.md)
- [20 Glossaire](20-glossaire.md) : vocabulaire commun (cloche, fiche, Nouveautes, Lu, purge...), a lire avant de nommer quoi que ce soit

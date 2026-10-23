"""Transcripts of a few demo fiches (by title), so a demo instance can try the LLM features on them."""

DEMO_TRANSCRIPTS = {
    "Pâte à pizza : le secret de l'hydratation": """\
Bonjour à tous, aujourd'hui on parle de la pâte à pizza, et surtout d'un chiffre : l'hydratation.
L'hydratation, c'est le poids d'eau divisé par le poids de farine. Pour 1000 grammes de farine et
650 grammes d'eau, on est à 65 % d'hydratation.
Pourquoi c'est si important ? Parce que l'eau transforme la cuisson. Dans un four domestique qui
monte à 250 degrés, une pâte trop sèche durcit avant d'avoir gonflé. Une pâte plus hydratée, vers
70 %, produit plus de vapeur, et c'est cette vapeur qui fait gonfler les bulles de la croûte.
Mais attention, plus d'eau, c'est une pâte plus collante et plus difficile à façonner. Si vous
débutez, commencez à 60 % et montez de 2 % à chaque essai.
Deuxième point : la farine. Une farine riche en protéines, comme une farine de type 00 avec un W
autour de 300, forme un réseau de gluten assez solide pour retenir toute cette eau. Une farine
faible va s'affaisser.
Troisième point, le temps. Laissez la pâte maturer 48 heures au réfrigérateur. Le froid ralentit
la levure, mais les enzymes continuent de découper l'amidon en sucres : la pâte est plus digeste
et la croûte colore mieux.
Enfin, le sel : environ 2,5 % du poids de farine, ajouté après l'eau, jamais directement au
contact de la levure, parce qu'il la freine.
En résumé : 65 à 70 % d'eau, une farine forte, 48 heures au froid, et vous verrez la différence.
""",
    "La chute de l'Empire romain d'Occident": """\
On date souvent la chute de l'Empire romain d'Occident de 476, quand le chef germanique Odoacre
dépose le jeune empereur Romulus Augustule et renvoie les insignes impériaux à Constantinople.
Mais les historiens insistent : 476 est surtout un symbole. L'Empire était déjà très affaibli.
Première cause, la crise financière. Pour payer une armée de plus en plus nombreuse, les empereurs
ont dévalué la monnaie : au troisième siècle, le denier ne contient presque plus d'argent, ce qui
provoque une forte inflation.
Deuxième cause, la pression aux frontières. À partir de 376, les Goths, poussés par les Huns,
franchissent le Danube. En 378, à la bataille d'Andrinople, ils écrasent l'armée romaine et tuent
l'empereur Valens.
Troisième cause, la division de l'Empire. En 395, à la mort de Théodose, l'Empire est partagé
entre ses deux fils. L'Orient, plus riche et plus peuplé, résiste ; l'Occident s'épuise.
Les Romains font alors de plus en plus appel à des peuples fédérés pour défendre leurs frontières.
Ces chefs militaires finissent par détenir le vrai pouvoir. En 410, les Wisigoths d'Alaric
pillent Rome, un choc immense pour les contemporains : saint Augustin écrit La Cité de Dieu en
réponse.
L'Empire d'Orient, lui, continue jusqu'en 1453 et la prise de Constantinople par les Ottomans.
Retenez donc que la chute de l'Occident est un processus long, plus qu'un événement unique.
""",
    "Optimiser une requête SQL lente": """\
Votre page met trois secondes à s'afficher et vous soupçonnez la base de données. Voici la méthode
que j'applique, dans l'ordre.
Étape un : mesurer. Ne devinez pas. Activez le journal des requêtes lentes, ou comptez les
requêtes par page. Très souvent, le problème n'est pas une requête lente mais cent requêtes
rapides : c'est le problème du N plus 1, quand le code charge une liste puis fait une requête par
ligne pour aller chercher un élément lié. La solution, c'est de charger les éléments liés en une
seule requête, avec une jointure ou un chargement groupé.
Étape deux : lire le plan d'exécution avec EXPLAIN ANALYZE. Si vous voyez un Seq Scan sur une
grande table, la base lit toutes les lignes une par une.
Étape trois : l'index. Un index sur la colonne du WHERE permet de trouver les lignes sans tout
lire. Pour un filtre sur deux colonnes, un index composite fonctionne, mais l'ordre compte : la
colonne la plus filtrante en premier, et l'index ne sert que si la requête utilise sa première
colonne.
Attention, un index n'est pas gratuit : chaque insertion et chaque mise à jour doit aussi le
mettre à jour. N'en ajoutez pas sur toutes les colonnes.
Étape quatre : ne demandez que ce dont vous avez besoin. Un SELECT étoile sur une table avec un
gros champ texte transfère des mégaoctets pour rien. Et paginez avec LIMIT plutôt que de tout
charger pour n'en afficher que vingt.
Dernier conseil : mesurez de nouveau après chaque changement, sur des données de taille réaliste.
""",
}

"""The tools the library chat model may call (names, descriptions, input schemas) and their bounds.

Their code is `LibraryChatToolbox` (`library_chat_tools.py`).
"""

# Each tool turn is a full extra API call, so this bounds both the latency and
# the cost of one question.
MAX_TOOL_TURNS = 4


MAX_CHANNEL_RESULTS = 60


MAX_VIDEO_RESULTS = 20


MAX_HISTORY_RESULTS = 30


DEFAULT_HISTORY_DAYS = 30


# Playback rows read before they are folded to one per media; bounds the scan of
# the ever-growing download_jobs table.
HISTORY_SCAN_LIMIT = 500


LIBRARY_CHAT_TOOLS = [
    {
        "name": "chercher_chaines",
        "description": (
            "Cherche des chaînes de la bibliothèque par nom, label (catégorie), URL ou identifiant YouTube. "
            "La recherche est textuelle (insensible à la casse et aux accents), pas sémantique : utilise un ou deux "
            "mots-clés, pas une phrase. Sans requête, liste toutes les chaînes, ce qui permet de choisir toi-même "
            "celles qui correspondent à un thème."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "Mots-clés ; vide pour tout lister."}
            },
        },
    },
    {
        "name": "chercher_videos",
        "description": (
            "Cherche des vidéos de la bibliothèque par titre, nom de chaîne, label ou commentaire, y compris "
            "celles sans notes structurées. Recherche textuelle par mots-clés, pas sémantique. `chaine_id` restreint "
            "à une chaîne ; avec `chaine_id` seul, renvoie ses vidéos les plus récentes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "Mots-clés du titre ou du sujet."},
                "chaine_id": {
                    "type": "integer",
                    "description": "ID d'une chaîne renvoyée par chercher_chaines.",
                },
            },
        },
    },
    {
        "name": "chercher_dans_les_notes",
        "description": (
            "Recherche sémantique dans les notes structurées des vidéos (faits, concepts, acteurs...). À utiliser pour "
            "une question sur le contenu des vidéos, ou pour trouver quelles chaînes parlent d'un sujet. Ne couvre que "
            "les vidéos dont les notes ont été générées. Formule la requête comme une question ou une phrase complète."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "Question ou sujet en langage naturel.",
                }
            },
            "required": ["requete"],
        },
    },
    {
        "name": "consulter_historique",
        "description": (
            "Renvoie l'historique de lecture : les vidéos ou audios que l'utilisateur a regardés ou écoutés, du plus "
            "récent au plus ancien, une ligne par vidéo, avec la date, la progression et le temps regardé. À utiliser "
            "pour « qu'ai-je regardé récemment », « ai-je déjà vu telle vidéo », « qu'est-ce que je n'ai pas fini »."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "jours": {
                    "type": "integer",
                    "description": f"Fenêtre en jours à partir d'aujourd'hui (défaut {DEFAULT_HISTORY_DAYS}).",
                },
                "requete": {
                    "type": "string",
                    "description": "Mots-clés du titre ou de la chaîne pour ne garder qu'une partie de l'historique.",
                },
            },
        },
    },
    {
        "name": "chercher_sur_youtube",
        "description": (
            "Cherche sur YouTube des chaînes par nom, pour trouver une chaîne qui n'est pas encore dans la "
            "bibliothèque. Renvoie les candidates dans l'ordre de pertinence de YouTube, avec leur identifiant "
            "[youtube:ID], leur handle et leur nombre d'abonnés, et signale celles déjà présentes dans la bibliothèque."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "Nom de la chaîne ou du créateur, ou handle.",
                }
            },
            "required": ["requete"],
        },
    },
    {
        "name": "ajouter_chaine",
        "description": (
            "Ajoute à la bibliothèque une chaîne renvoyée par chercher_sur_youtube pendant cette même question. "
            "À n'appeler que si l'utilisateur demande explicitement d'ajouter une chaîne."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "youtube_id": {
                    "type": "string",
                    "description": "L'ID d'une référence [youtube:ID], sans les crochets.",
                }
            },
            "required": ["youtube_id"],
        },
    },
]

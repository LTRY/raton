# Politique de sécurité

Raton n'a **pas d'authentification** : il est conçu pour un réseau local de
confiance et ne doit jamais être exposé sur Internet (voir
[15 Sécurité](docs/spec/15-securite.md)). Un accès non authentifié depuis le LAN
est donc le comportement attendu, pas une faille.

## Signaler une vulnérabilité

Merci de ne **pas** ouvrir d'issue publique. Utilise le signalement privé de
GitHub : onglet *Security* → *Report a vulnerability*. Indique la version
(commit), les étapes de reproduction et l'impact. Tu auras une réponse sous
quelques jours.

Ne joins jamais de clé d'API réelle (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`) à un
signalement.

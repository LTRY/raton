# Contribuer à Raton

Merci de ton intérêt ! Le comportement de l'application est décrit dans
[`docs/spec/`](docs/spec/README.md) : lis les fichiers concernés avant de coder.

## Mise en place

```bash
make install   # dépendances (uv, Python 3.14)
make demo      # application sur une base SQLite jetable
make ci        # CSS, lint ruff, tests, validation Compose
```

`ffmpeg` est requis. Docker n'est nécessaire que pour `make up` et `make ci`
(validation Compose).

## Pull request

1. Ouvre d'abord une issue pour un changement important.
2. Mets à jour le code, les tests **et** la spec dans le même changement.
3. Lance `make ci` : il doit passer.
4. Titre : une ou plusieurs étiquettes de périmètre puis un résumé court à
   l'impératif, en anglais, par ex. `[FRONT] Stats: link channel names to their
   channel page` (voir [04](docs/spec/04-configuration-et-deploiement.md)).
5. Pour tout changement d'interface, joins des captures d'écran (bureau et
   téléphone).

Une migration Alembic est nécessaire pour tout changement de schéma ; il ne doit
y avoir qu'une seule tête (`tests/test_migration_single_head.py`).

En contribuant, tu acceptes que ta contribution soit publiée sous licence MIT.

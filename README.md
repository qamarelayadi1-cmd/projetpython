# Pipeline Log Analyser

Ce projet lit des journaux SSH au format `auth.log`, conserve les événements utiles
dans une base SQLite et produit trois graphiques pour explorer les tentatives de
connexion.

## Architecture

```text
log_analysis/
├── data/                       # auth.log.1, auth.log.2 et archives .gz
├── ingestion/raw.py            # lecteur d'origine, conservé sans modification
├── processing/                 # modules d'origine, conservés sans modification
├── pipeline/runner.py          # lecture complète, parsing et géolocalisation
├── storage/sqlite_storage.py   # événements et cache géographique SQLite
├── serving/dashboard.py        # agrégations et graphiques matplotlib
├── logger_config.py            # configuration des fichiers de logs rotatifs
├── main.py                     # point d'entrée
├── logs/                       # journaux d'exécution, créés au lancement
└── output/                     # base SQLite et graphiques PNG
```

Le pipeline utilise son propre lecteur pour parcourir tous les fichiers, y compris
les archives gzip. Les modules d'origine restent intacts. Le parseur local traite
les messages SSH de succès, d'échec et d'utilisateur invalide. Les dates syslog,
qui ne contiennent pas l'année, sont enregistrées avec l'année de lancement.

Les fichiers analysés suivent le format syslog Linux, par exemple :

```text
May 24 00:17:01 ns sshd[1351119]: Failed password for root from 203.0.113.8 port 22 ssh2
May 24 00:18:01 ns sshd[1351150]: Accepted publickey for alice from 203.0.113.9 port 22 ssh2
```

Le mois, le jour, l'heure, l'hôte, le PID sshd et le message sont lus. L'adresse
IP et l'utilisateur sont extraits pour les lignes d'authentification prises en
charge.

## Installation et lancement

Depuis le dossier `log_analysis`, avec `uv` installé (macOS, Linux ou Windows) :

```sh
uv sync
uv run main.py
```

Le dossier doit contenir les quatre fichiers d'exemple dans `data/`. Pour lancer
les tests sans appeler ipinfo :

```sh
uv run python -m unittest discover -s tests -v
```

La géolocalisation des adresses IP publiques utilise `ipinfo.io` et nécessite un
accès réseau. Pour éviter d'attendre les milliers de requêtes et de dépasser les
limites du service, au plus 20 IP publiques nouvelles sont géolocalisées par
lancement. Les autres sont regroupées sous `Unknown`. Les adresses non publiques
ne sont pas envoyées au service.

## Graphiques

Les images individuelles sont enregistrées dans `output/`. La fenêtre Matplotlib
reprend la disposition de la référence : les graphiques 1 et 2 côte à côte en haut,
puis le graphique 3 sur toute la largeur en dessous. Les barres sont horizontales,
avec un quadrillage léger et la valeur au bout de chaque barre :

1. `01_invalid_user_attempts.png` : les quinze noms d'utilisateurs invalides les
   plus fréquents.
2. `02_failed_attempts_by_country.png` : nombre d'événements `Failed` et
   `Invalid` par pays.
3. `03_successful_attempts_by_user.png` : authentifications `Accepted password`
   et `Accepted publickey` par utilisateur.

Les répétitions explicites de la forme `message repeated N times` sont comptées
N fois. Les adresses privées et locales sont regroupées sous `Private / local`.
Les échecs de géolocalisation sont regroupés sous `Unknown`. Une ligne d'utilisateur
invalide sans nom est comptée sous le nom `(empty)`.

## Stockage

`output/auth_events.sqlite3` contient les colonnes date, IP, utilisateur, statut,
pays, fichier source et nombre d'occurrences. Une seconde table conserve les pays
déjà résolus afin de limiter les appels répétés à ipinfo entre les exécutions.
SQLite fait partie de la bibliothèque standard ; aucune dépendance supplémentaire
n'a été ajoutée.

## Journaux de l'application

Chaque composant écrit dans son fichier sous `logs/` avec le format
`%(asctime)s|%(levelname)s|%(name)s|%(message)s`. Les fichiers sont renouvelés à
2 Mo et cinq sauvegardes sont conservées. Les erreurs de lecture, de parsing, de
géolocalisation, de base de données et de création des graphiques sont journalisées
et remontées à l'appelant : `ingestion.log`, `processing.log`, `storage.log`,
`serving.log` et `main.log`.

## Workflow Git

Les changements sont conçus pour être validés par module après les tests ciblés,
avec des messages comme `feat(logging): add per-module logger config`,
`feat(storage): add SQLite event store`, `feat(pipeline): parse all SSH logs`,
`feat(serving): add SSH dashboard` et `docs: add README`. Vérifier `git status`
avant chaque commit, puis pousser la branche avec `git push`.

## Limites connues

- `ingestion/raw.py` retourne depuis l'intérieur de sa boucle et ne lit donc pas
  tous les fichiers ; son annotation de chemin ne correspond pas à son usage,
  l'ouverture des fichiers non compressés n'est pas définie et ses erreurs sont
  traitées par des `print`. Le pipeline contourne ce lecteur sans le changer.
- `processing/extract_transforme.py` contient une erreur de syntaxe et son
  extraction appelle `print` au lieu de retourner les champs. Le pipeline utilise
  ses propres regex et ne l'importe pas.
- `processing/geo_location.py` n'impose ni délai réseau ni traitement des erreurs.
  Le pipeline fait sa propre requête avec timeout, journalisation et cache, sans
  appeler cette fonction.
- Le format syslog ne donne pas l'année ; l'année courante est utilisée. Les
  graphiques reflètent les messages pris en charge par le parseur, pas tous les
  messages sshd.
- Chaque nouvelle exécution ajoute les événements à la base existante. Pour refaire
  un calcul complet, supprimer manuellement `output/auth_events.sqlite3` avant de
  relancer.
- ipinfo peut limiter les requêtes ou être indisponible. Dans ce cas, le pays est
  enregistré comme `Unknown` dans le cache.

## Améliorations possibles

- Ajouter une option de ligne de commande pour sélectionner les fichiers, la base
  et le nombre d'utilisateurs affichés.
- Dédupliquer ou remettre à zéro les événements par fichier source lors d'une
  réexécution.
- Étendre les tests avec davantage de variantes de messages sshd et des fichiers
  représentatifs issus de rotations réelles.
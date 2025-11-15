POC - Système d'assignation en temps réel (Redis vs. MongoDB)
Ce projet est une Preuve de Concept (POC) pour un système d'assignation de livreurs en temps réel, simulant une plateforme de type UberEats. Il contient deux versions de l'application Flask : une utilisant Redis et l'autre MongoDB.

# 1. Installation (Commune)
Ce projet est développé en Python (testé sur Linux Ubuntu 24.04.3 LTS).

Clonez ce dépôt (si ce n'est pas déjà fait).

Créez un environnement virtuel et activez-le :

Bash

python3 -m venv venv
source venv/bin/activate
Installez les bibliothèques Python requises :

Bash

pip install Flask redis

# 2. Lancement de l'Application
Vous pouvez lancer la version Redis ou la version MongoDB.


Installer et compiler Redis (si non disponible localement) :

Bash

Télécharger la dernière version stable
wget https://download.redis.io/redis-stable.tar.gz

Extraire l'archive
tar -xvzf redis-stable.tar.gz

Compiler les sources
cd redis-stable
make
Démarrer le serveur Redis (dans un terminal) : Assurez-vous d'être dans le dossier redis-stable.

Bash

src/redis-server
(Vous devriez voir le logo Redis et un message indiquant que le serveur est prêt).

Lancer l'application Flask (dans un second terminal, à la racine du projet) : N'oubliez pas d'activer votre environnement virtuel (source venv/bin/activate) et puis lancer la commande python3 app_redis.py.

Bash

python app_redis.py

# 3. Lancer les Tests de Charge (Optionnel)
Le projet inclut un fichier locustfile.py pour simuler une charge d'utilisateurs avec Locust.

Installez Locust (s'il n'est pas déjà dans pip install) :

Bash

pip install locust
Assurez-vous que l'une des applications (Redis ou Mongo) est en cours d'exécution (sur http://127.0.0.1:5000).

Lancez Locust en pointant vers votre application :

Bash

locust -f locustfile.py --host http://127.0.0.1:5000
Ouvrez l'interface web de Locust dans votre navigateur (généralement http://localhost:8089) pour démarrer la simulation.

# Livraison Express - Application de Livraison de Nourriture

## Description
Application web de livraison de nourriture développée avec Flask et MongoDB. Le système permet aux clients de commander de la nourriture, aux restaurants de préparer les commandes, aux livreurs de livrer et aux managers de superviser le processus.

## Architecture
- Backend: Flask avec MongoDB comme base de données
- Frontend: Templates HTML avec Bootstrap
- Temps réel: Server-Sent Events (SSE) pour les mises à jour en direct

## Rôles Utilisateurs
1. Client - Passer des commandes et suivre leur statut
2. Restaurant - Préparer les commandes et les marquer comme prêtes
3. Livreur - Accepter et livrer les commandes
4. Manager - Superviser et assigner les livreurs ou assignation automatique après un certain temps

## Fonctionnalités Temps Réel
- Mise à jour automatique des statuts de commande
- Notifications en temps réel
- Fenêtres de temps pour l'acceptation des livreurs
- Attribution automatique des livreurs

## Prérequis
- Python 3.8+
- Redis Server

## Installation

### 1. Cloner le repository
- en utilisant SSH :
  git clone git@github.com:Rafi-Bettaieb/UberEats_mongo.git

- en utilisant HTTPS :
  https://github.com/Rafi-Bettaieb/UberEats_mongo.git

cd UberEats_redis

### 2. Activer l'environnement virtuel

Sur Windows:
venv\Scripts\activate

Sur Mac/Linux:
source venv/bin/activate

### 3. Installer les dépendances
pip install -r requirements.txt

### 4. Configuration MongoDB Atlas

Pour ce POC, une approche cloud-native a été privilégiée en utilisant MongoDB Atlas,
la version "Database-as-a-Service" (DBaaS) de MongoDB. La configuration du cluster a
suivi les étapes ci-dessous.

#### 4.1 Création d'un compte
La première étape a été de se rendre sur le site officiel de MongoDB Atlas pour créer un
compte (soit via Google, soit en remplissant le formulaire d'inscription).

#### 4.2 Création d'une Organisation
Une fois connecté, une "Organisation" a été créée pour héberger les projets.
- Accès via l'icône de profil → "Organisations".
- Clic sur "Create New Organization" et attribution d'un nom.

#### 4.3 Création d'un Projet
Au sein de l'organisation, un "Projet" a été créé pour contenir le cluster de base de
données. Un nom a été donné au projet (par ex. delivery-project).

#### 4.4 Création du Cluster
C'est l'étape de provisionnement de la base de données elle-même.
1. Clic sur le bouton "Create" pour démarrer l'assistant.
2. Configuration du Cluster : Le fournisseur de cloud, la région et les spécifications
ont été choisis. Pour ce POC, le niveau gratuit M0 a été sélectionné.

#### 4.5 Création d'un Utilisateur de Base de Données
Pour permettre à l'application Python de se connecter, un utilisateur de base de données
a été créé (différent du compte Atlas).
- Création d'un nom d'utilisateur et d'un mot de passe sécurisé, qui a été copié et
sauvegardé.

#### 4.6 Configuration de l'Accès Réseau
C'est une étape critique. Avant de pouvoir se connecter, l'adresse IP de la machine de
développement doit être autorisée.
- Dans le menu "Network Access" d'Atlas, l'adresse IP de la machine locale a été
ajoutée à la "IP Access List".

#### 4.7 Récupération de la Chaîne de Connexion (URI)
Une fois l'utilisateur créé et l'IP autorisée, la chaîne de connexion (URI) a été récupérée en
cliquant sur "Connect" → "Connect with MongoDB Compass". L'URI (mongodb+srv://...)
a été copié.

#### 4.8 Installation de MongoDB Compass 
L'interface graphique MongoDB Compass peut être installée localement pour interagir avec le cluster Atlas.

Sur Ubuntu/Debian :
wget https://downloads.mongodb.com/compass/mongodb-compass_1.44.4_amd64.deb
sudo dpkg -i mongodb-compass_1.44.4_amd64.deb
sudo apt --fix-broken install -y
mongodb-compass

#### 4.9 Connexion au Cluster via Compass
L'étape finale consiste à connecter l'outil local au cluster cloud :
- Au lancement de MongoDB Compass, l'URI de connexion (obtenu à l'étape 7) a
été collé dans le champ principal.
- Un clic sur "Connect" a permis d'établir la connexion et de visualiser les bases de
données hébergées sur Atlas.

#### 4.10 Tester la connexion
L'application se connecte automatiquement à MongoDB Atlas. Pour tester manuellement :

from pymongo import MongoClient

from pymongo.errors import ConnectionFailure

MONGO_URI = "mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/"

try:

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    
    client.server_info()
    
    print("Connexion a MongoDB reussie !")

except ConnectionFailure as e:

    print("ECHEC de la connexion.")

## Démarrage de l'Application
### 1. Lancer l'application Flask
python app_mongo.py

### 2. Initialiser les données de test
L'application va automatiquement charger les données depuis donnees_fusionnees_avec_menus.json au premier démarrage.

### 3. Accéder à l'application
Ouvrez votre navigateur et allez sur:
http://localhost:5000

## Comptes de Test

Client
- Username: client1
- Password: 123456
- Role: client

Restaurant
- Username: restaurant1
- Password: 123456
- Role: restaurant

Livreur
- Username: livreur1
- Password: 123456
- Role: livreur

Manager
- Username: manager1
- Password: 123456
- Role: manager

## Utilisation

Pour les Clients:
1. Connectez-vous avec un compte client
2. Cliquez sur "Passer une commande"
3. Sélectionnez un restaurant et des articles
4. Suivez le statut de votre commande en temps réel
5. Notez le livreur après livraison

Pour les Restaurants:
1. Connectez-vous avec un compte restaurant
2. Consultez les commandes en attente
3. Marquez les commandes comme "prêtes" quand elles sont préparées

Pour les Livreurs:
1. Connectez-vous avec un compte livreur
2. Consultez les commandes disponibles
3. Montrez votre intérêt pour les commandes
4. Mettez à jour votre position GPS
5. Marquez les commandes comme livrées

Pour les Managers:
1. Connectez-vous avec un compte manager
2. Supervisez toutes les commandes
3. Assignez manuellement des livreurs si nécessaire

## Lancer les Tests de Charge (Optionnel)
Le projet inclut un fichier locustfile.py pour simuler une charge d'utilisateurs avec Locust.

Installez Locust :

pip install locust

Assurez-vous que l'applications est en cours d'exécution (sur http://127.0.0.1:5000).

Lancez Locust en pointant vers votre application :

locust -f locustfile.py --host http://127.0.0.1:5000

Ouvrez l'interface web de Locust dans votre navigateur (http://localhost:8089) pour démarrer la simulation.


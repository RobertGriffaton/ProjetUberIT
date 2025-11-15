README — Projet « Ubeer » (version MongoDB)

POC qui simule une mini-plateforme de type UberEats avec une architecture basée sur MongoDB.
Objectif : comparer avec la version Redis en ajoutant la persistance naturelle des données dans une base NoSQL.

1️⃣ Objectif

Ce projet reproduit le même fonctionnement que la version Redis :

client.py → passe une commande, suit la livraison, note le livreur

manager.py → attribue les commandes (automatiquement ou manuellement)

coursier.py → accepte, effectue et signale la livraison

La différence principale :
👉 ici, toutes les informations sont stockées et consultables durablement dans MongoDB, via MongoDB Atlas.

2️⃣ Prérequis
🧩 Outils nécessaires

Python 3.9 ou supérieur

Un compte MongoDB Atlas
(gratuit)

Une base créée dans Atlas : ubeer

Le fichier menus.csv à la racine (même structure que Redis)

📦 Installer les dépendances
pip install -r requirements.txt

3️⃣ Configuration de la connexion à MongoDB

Crée un fichier .env dans le dossier du projet (UberMongo/) :

MONGO_URI=mongodb+srv://<USERNAME>:<PASSWORD>@uberit.c1vn27k.mongodb.net/?retryWrites=true&w=majority&appName=UberIT
DB_NAME=ubeer

➡️ Remplace <USERNAME> et <PASSWORD> par ceux de ton utilisateur Atlas.

4️⃣ Initialisation de la base

Tu peux (optionnellement) importer les restaurants du CSV vers MongoDB :

python import_csv_to_mongo.py

Cela va créer une collection restaurants contenant :

{
"restaurant": "Burger Place",
"latitude": 48.860,
"longitude": 2.345,
"menus": ["Cheeseburger", "Double Burger", "Menu Vegan", ...]
}

⚠️ Si tu veux simplement tester sans importer, le code fonctionne déjà avec le CSV directement.

5️⃣ Lancement de l’application

Comme pour Redis, tu as trois scripts à exécuter (dans trois terminaux séparés) :

Terminal A — Manager
python manager_mongo.py

Terminal B — Coursier (tu peux en ouvrir plusieurs)
python coursier_mongo.py

Terminal C — Client
python client_mongo.py

6️⃣ Fonctionnement (identique à Redis, mais persistant)

1️⃣ Le client choisit un restaurant et un plat → une commande est insérée dans MongoDB :

{
"\_id": "...",
"restaurant": "Sushi Tokyo",
"item": "California Roll",
"status": "pending",
"created_at": ISODate("2025-11-03T12:00:00Z")
}

2️⃣ Le manager diffuse l’annonce aux coursiers.
Les coursiers répondent avec leur position et leur note moyenne.
Le manager choisit :

manuellement (1..N)

ou automatiquement (ETA + meilleure note).

3️⃣ La commande est mise à jour :

{
"status": "assigned",
"courier": "Léa",
"eta_min": 8
}

4️⃣ Le coursier simule la livraison (progression 0–100 % sur 2 phases).

5️⃣ Le client suit la progression en temps réel et note le livreur à la fin :

{
"courier": "Léa",
"score": 5,
"order_id": "...",
"timestamp": ISODate("2025-11-03T12:10:00Z")
}

6️⃣ MongoDB met à jour automatiquement la moyenne du livreur :

{
"courier": "Léa",
"avg": 4.7,
"count": 8
}

7️⃣ Collections MongoDB créées
Collection Contenu Exemple
restaurants Liste des restaurants et menus {restaurant: "Sushi Tokyo", menus: [...]}
orders Commandes clients {restaurant: "Pizza Nova", item: "Margherita", courier: "Noa"}
couriers Infos et notes des livreurs {courier: "Léa", avg: 4.7, count: 8}
ratings_history Notes détaillées de chaque commande {courier: "Léa", score: 5, order_id: ...}
8️⃣ Requêtes Mongo utiles (via mongosh ou Compass)

Ouvre ton terminal :

mongosh "mongodb+srv://uberit.c1vn27k.mongodb.net/ubeer" --apiVersion 1 --username griffatonr_db_user

Voir toutes les collections :
show collections

Voir toutes les commandes :
db.orders.find().pretty()

Voir les notes moyennes des livreurs :
db.couriers.find({}, {courier:1, avg:1, count:1, \_id:0})

Voir l’historique des notes d’un livreur :
db.ratings_history.find({courier: "Léa"}).sort({timestamp:-1}).limit(5)

Lister les restaurants :
db.restaurants.find({}, {restaurant:1, \_id:0})

Top 3 livreurs :
db.couriers.find().sort({avg:-1, count:-1}).limit(3)

9️⃣ Différences clés entre Redis et MongoDB
Aspect Redis MongoDB
Stockage En mémoire (AOF pour persistance) Sur disque (natif)
Type de données Clés / Hash / Listes Documents JSON (collections)
Rapidité Extrême pour le temps réel Très bonne, mais moins instantanée
Idéal pour Messages, suivi en temps réel, cache Données persistantes, analytics
Persistance Doit être activée (AOF) Intégrée nativement
Requêtes analytiques Limitées (commandes manuelles) Puissantes (agrégations, tri, filtres)
🔍 Exemple de comparaison à présenter

« En Redis, les données sont stockées en mémoire et sauvegardées via un fichier AOF.
En MongoDB, elles sont écrites directement sur disque sous forme de documents JSON.
Redis est idéal pour la rapidité du Pub/Sub et le suivi en direct, tandis que MongoDB est plus adapté à l’analyse, à la persistance longue durée et aux statistiques comme les notes moyennes, le nombre de commandes ou les restaurants les plus commandés. »

🔚 En résumé
Élément Redis MongoDB
Données conservées Notes des coursiers Notes, commandes, restaurants
Persistance Fichier .aof Native
Lecture après reboot Nécessite relancer Redis avec AOF Automatique
Accès analytique Manuel (via redis-cli) Requêtes complexes possibles
Usage dans le projet Système en temps réel Système de stockage structuré

import csv
from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Chargement des variables d'environnement
load_dotenv()
URI = os.getenv("MONGODB_URI")
DBNAME = os.getenv("DB_NAME", "ubeer")

client = MongoClient(URI)
db = client[DBNAME]

# Nom de ta collection MongoDB
collection = db.restaurants

csv_file = "menus.csv"  # ton fichier CSV local

# Vider la collection avant de réimporter (optionnel)
collection.delete_many({})

with open(csv_file, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    data = list(reader)

# Conversion automatique des nombres
for d in data:
    if "latitude" in d:
        d["latitude"] = float(d["latitude"])
    if "longitude" in d:
        d["longitude"] = float(d["longitude"])
    if "price_eur" in d:
        d["price_eur"] = float(d["price_eur"])

if data:
    collection.insert_many(data)
    print(f"✅ {len(data)} documents insérés dans 'restaurants'")
else:
    print("⚠️ Aucun enregistrement trouvé dans le CSV.")

client.close()

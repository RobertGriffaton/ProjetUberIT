import os, time, uuid
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
URI = os.getenv("MONGODB_URI")
DBNAME = os.getenv("DB_NAME", "ubeer")

CLIENT_LAT = 48.8610
CLIENT_LON = 2.3450

def fetch_restaurants(db):
    coll = db.restaurants
    names = coll.distinct("restaurant")
    return sorted([n for n in names if isinstance(n, str)])

def fetch_menu_for_restaurant(db, resto_name):
    coll = db.restaurants
    cur = coll.find({"restaurant": resto_name}, {"_id": 0}).sort("item", 1)
    return list(cur)

def rate_courier(db, courier_id, order_id):
    while True:
        try:
            score = int(input("Notez le livreur (1 à 5) : "))
            if 1 <= score <= 5:
                break
        except Exception:
            pass
        print("Saisie invalide. Entrez un nombre entre 1 et 5.")

    comment = input("Commentaire (optionnel) : ")

    db.ratings.insert_one({
        "courier_id": courier_id,
        "order_id": order_id,
        "score": score,
        "comment": comment,
        "ts": int(time.time())
    })

    c = db.couriers.find_one({"courier_id": courier_id}) or {"avg_rating": 0, "ratings_count": 0}
    new_count = c["ratings_count"] + 1
    new_avg = (c["avg_rating"] * c["ratings_count"] + score) / new_count

    db.couriers.update_one(
        {"courier_id": courier_id},
        {"$set": {"avg_rating": new_avg, "ratings_count": new_count}},
        upsert=True
    )

    print(f"⭐ Merci ! Vous avez noté {score}/5 (moyenne actuelle du livreur ≈ {round(new_avg,2)})")

def main():
    client = MongoClient(URI)
    db = client[DBNAME]
    orders = db.orders
    assignments = db.assignments
    tracking = db.tracking

    names = fetch_restaurants(db)
    if not names:
        print("⚠️ Aucun restaurant trouvé dans MongoDB ('restaurants').")
        return

    print("Restaurants disponibles :")
    for i, name in enumerate(names, 1):
        print(f"{i}) {name}")
    while True:
        try:
            idx = int(input("Choisir un restaurant : ")) - 1
            if 0 <= idx < len(names): break
        except Exception:
            pass
        print("Saisie invalide.")

    resto = names[idx]
    menu = fetch_menu_for_restaurant(db, resto)
    if not menu:
        print(f"⚠️ Aucun plat trouvé pour '{resto}'.")
        return

    print(f"Menu de {resto} :")
    for j, row in enumerate(menu, 1):
        print(f"{j}) {row['item']} — {row['price_eur']}€")
    while True:
        try:
            k = int(input("Choisir un plat : ")) - 1
            if 0 <= k < len(menu): break
        except Exception:
            pass
        print("Saisie invalide.")

    chosen = menu[k]
    order_id = str(uuid.uuid4())
    orders.insert_one({
        "_id": order_id,
        "type": "ORDER",
        "restaurant": {"name": resto},
        "items": [{"sku": chosen["sku"], "qty": 1, "name": chosen["item"]}],
        "customer": {"name": "Client POC", "lat": CLIENT_LAT, "lon": CLIENT_LON},
        "created_at": int(time.time()),
        "status": "created"
    })
    print(f"[CLIENT] 🧾 Commande envoyée : {order_id}")

    with assignments.watch(
        [{"$match": {"operationType": "insert", "fullDocument.order_id": order_id}}],
        full_document="updateLookup"
    ) as s1:
        for ev in s1:
            sel = ev["fullDocument"]
            courier_id = sel["courier_id"]
            courier_name = sel.get("courier_name", courier_id)
            eta_min = sel.get("eta_min")
            print(f"[CLIENT] ✅ Livreur attribué : {courier_name} (ETA ≈ {eta_min} min)")
            break

    print("[CLIENT] 🚴 Suivi en temps réel…")
    try:
        with tracking.watch(
            [{"$match": {"operationType": "insert", "fullDocument.order_id": order_id}}],
            full_document="updateLookup"
        ) as s2:
            for ev in s2:
                t = ev["fullDocument"]
                status = t.get("status", "")
                progress = t.get("progress", 0)
                if status in ("vers_client_arrived", "livre"):
                    print(f"[CLIENT] 🎉 Livraison terminée ({progress}%)")
                    rate_courier(db, courier_id, order_id)
                    break
                else:
                    print(f"[SUIVI] {status} | prog={progress}%")
    except KeyboardInterrupt:
        print("\n[CLIENT] Arrêt du suivi.")
    finally:
        client.close()

if __name__ == "__main__":
    main()

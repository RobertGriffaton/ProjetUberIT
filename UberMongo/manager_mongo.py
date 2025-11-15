import os, time, math
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

load_dotenv()
URI = os.getenv("MONGODB_URI")
DBNAME = os.getenv("DB_NAME", "ubeer")

REWARD_EUR = 8.5
TIMEOUT_S = 15
VITESSE_KMH = 28.0
DELAI_FIXE_MIN = 0.5

def haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def eta_minutes_from(c_pos, pickup, drop):
    d1 = haversine_km(float(c_pos["lat"]), float(c_pos["lon"]),
                      float(pickup["lat"]), float(pickup["lon"]))
    d2 = haversine_km(float(pickup["lat"]), float(pickup["lon"]),
                      float(drop["lat"]), float(drop["lon"]))
    minutes = ((d1 + d2) / max(1e-6, VITESSE_KMH)) * 60.0 + DELAI_FIXE_MIN
    return max(1, int(round(minutes)))

def load_restaurants_from_mongo(db):
    mapping = {}
    coll = db.restaurants
    coll.create_index([("restaurant", ASCENDING)])
    for doc in coll.find({}, {"restaurant": 1, "latitude": 1, "longitude": 1}):
        name = doc.get("restaurant")
        if not name:
            continue
        try:
            lat = float(doc["latitude"])
            lon = float(doc["longitude"])
            mapping[name] = {"lat": lat, "lon": lon}
        except Exception:
            continue
    return mapping

def get_rating(db, courier_id):
    c = db.couriers.find_one({"courier_id": courier_id})
    return c.get("avg_rating", 3.0) if c else 3.0

def prompt_select_or_auto(cands_sorted):
    print("\n[MANAGER] 📊 Candidatures :")
    for i, c in enumerate(cands_sorted, 1):
        print(f" {i}) {c['courier_id']} | ETA={c['eta_min']} min | Note={c.get('rating', '?')}")
    try:
        raw = input("[MANAGER] Choisir un livreur (1..N) ou Entrée pour auto : ").strip()
    except EOFError:
        raw = ""
    if raw == "":
        return cands_sorted[0]
    try:
        idx = int(raw)
        if 1 <= idx <= len(cands_sorted):
            return cands_sorted[idx - 1]
    except Exception:
        pass
    print("[MANAGER] Choix invalide → sélection auto.")
    return cands_sorted[0]

def main():
    client = MongoClient(URI)
    db = client[DBNAME]
    orders, candidatures, assignments = db.orders, db.candidatures, db.assignments
    restos = load_restaurants_from_mongo(db)

    print("[MANAGER] En attente de commandes...")

    with orders.watch(
        [{"$match": {"operationType": "insert", "fullDocument.type": "ORDER"}}],
        full_document="updateLookup"
    ) as stream:
        for ch in stream:
            order = ch["fullDocument"]
            order_id = order["_id"]
            resto_name = order["restaurant"]["name"]
            customer = order["customer"]
            dropoff = {"lat": float(customer["lat"]), "lon": float(customer["lon"])}

            pickup = restos.get(resto_name)
            if not pickup:
                print(f"[MANAGER] ⚠️ Restaurant inconnu : {resto_name}")
                continue

            print(f"[MANAGER] 📣 Commande {order_id} ({resto_name})")
            start = time.monotonic()
            cands = []

            with candidatures.watch(
                [{"$match": {"operationType": "insert", "fullDocument.order_id": order_id}}],
                full_document="updateLookup"
            ) as cs:
                while time.monotonic() - start < TIMEOUT_S:
                    ev = cs.try_next()
                    if not ev:
                        time.sleep(0.2)
                        continue
                    cand = ev["fullDocument"]
                    pos = cand.get("position") or {}
                    cand["eta_min"] = eta_minutes_from(
                        {"lat": float(pos["lat"]), "lon": float(pos["lon"])}, pickup, dropoff
                    )
                    cand["rating"] = get_rating(db, cand["courier_id"])
                    cands.append(cand)
                    print(f"[MANAGER] 📥 Candidature {cand['courier_id']} (ETA={cand['eta_min']} min, Note={cand['rating']})")

            if not cands:
                print("[MANAGER] 😕 Aucune candidature reçue.")
                continue

            cands.sort(key=lambda c: (c["eta_min"], -c.get("rating", 3.0)))
            chosen = prompt_select_or_auto(cands)

            # ✅ Correction : ajout de pickup/dropoff pour éviter KeyError côté coursier
            assignments.insert_one({
                "type": "SELECTION",
                "order_id": order_id,
                "courier_id": chosen["courier_id"],
                "courier_name": chosen.get("name", chosen["courier_id"]),
                "eta_min": int(chosen.get("eta_min", 10)),
                "reward_eur": REWARD_EUR,
                "pickup":  {"lat": float(pickup["lat"]),  "lon": float(pickup["lon"])},
                "dropoff": {"lat": float(dropoff["lat"]), "lon": float(dropoff["lon"])},
                "assigned_at": int(time.time())
            })
            print(f"[MANAGER] ✅ Affecté : {chosen['courier_id']} (Note={chosen.get('rating', '?')})")

if __name__ == "__main__":
    main()

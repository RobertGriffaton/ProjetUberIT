import os, time, math, random
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
URI = os.getenv("MONGODB_URI")
DBNAME = os.getenv("DB_NAME", "ubeer")

VITESSE_KMH = 28.0
CENTER_LAT, CENTER_LON = 48.8660, 2.3350
JITTER_KM = 0.3
TICK_SEC = 1.0
PAUSE_S = 2

NAMES = [
    "Alex","Sam","Robin","Camille","Noa","Lina","Mael","Eli","Nora","Rayan",
    "Milan","Yanis","Léa","Jules","Zoé","Léo","Inès","Sacha","Aya","Nils","Pierre"
]

def choose_firstname():
    return random.choice(NAMES).capitalize()

def jitter(lat0, lon0, spread_km=JITTER_KM):
    dlat = random.gauss(0, spread_km) / 111.0
    dlon = random.gauss(0, spread_km) / (111.0 * max(0.1, math.cos(math.radians(lat0))))
    return lat0 + dlat, lon0 + dlon

def hav(a_lat,a_lon,b_lat,b_lon):
    R=6371.0
    dlat=math.radians(b_lat-a_lat); dlon=math.radians(b_lon-a_lon)
    lat1=math.radians(a_lat); lat2=math.radians(b_lat)
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(h))

def lerp(a,b,t): return a+(b-a)*t

def move_and_track(db, order_id, courier, start, target, status_label, planned_s, global_remaining_s):
    tracking = db.tracking
    steps = max(5, int(planned_s // TICK_SEC))
    t0 = time.time()
    last_shown = -25
    for step in range(steps+1):
        t = step/steps
        lat = lerp(start[0], target[0], t)
        lon = lerp(start[1], target[1], t)
        progress = int(round(t*100))
        if progress - last_shown < 25 and progress != 100:
            time.sleep(TICK_SEC)
            continue
        last_shown = progress
        elapsed = time.time() - t0
        local_eta  = max(0, int(planned_s - elapsed))
        global_eta = max(0, int(global_remaining_s - elapsed))
        tracking.insert_one({
            "type":"TRACK",
            "order_id":order_id,
            "courier_id":courier["id"],
            "name":courier["name"],
            "status":status_label,
            "lat":lat,"lon":lon,
            "progress":progress,
            "eta_s":local_eta,
            "global_eta_s":global_eta,
            "sent_at":int(time.time())
        })
        time.sleep(TICK_SEC)
    tracking.insert_one({
        "type":"TRACK",
        "order_id":order_id,
        "courier_id":courier["id"],
        "name":courier["name"],
        "status":f"{status_label}_arrived",
        "lat":target[0],"lon":target[1],
        "progress":100,"eta_s":0,
        "global_eta_s":max(0, int(global_remaining_s - planned_s)),
        "sent_at":int(time.time())
    })

def main():
    client = MongoClient(URI)
    db = client[DBNAME]
    orders, cands, assignments = db.orders, db.candidatures, db.assignments

    firstname = choose_firstname()
    courier = {"id": firstname, "name": firstname}

    lat, lon = jitter(CENTER_LAT, CENTER_LON, JITTER_KM)
    print(f"[COURSIER {courier['id']}] En ligne | position=({lat:.5f},{lon:.5f})")

    try:
        with orders.watch(
            [{"$match":{"operationType":"insert","fullDocument.type":"ORDER"}}],
            full_document='updateLookup'
        ) as stream:
            for ch in stream:
                order = ch["fullDocument"]
                order_id = order["_id"]

                ans = input(f"[{courier['name']}] Accepter la commande {order_id} (o/N) ? ").strip().lower()
                if ans != "o":
                    print(f"[{courier['id']}] ❌ refuse la commande {order_id}")
                    continue

                # Candidature
                cands.insert_one({
                    "type":"CANDIDATURE",
                    "order_id": order_id,
                    "courier_id": courier["id"],
                    "name": courier["name"],
                    "position": {"lat": lat, "lon": lon},
                    "sent_at": int(time.time())
                })
                print(f"[{courier['id']}] 📨 Candidature envoyée pour {order_id}")

                # Attente sélection
                with assignments.watch(
                    [{"$match": {
                        "operationType":"insert",
                        "fullDocument.order_id": order_id,
                        "fullDocument.courier_id": courier["id"]
                    }}],
                    full_document='updateLookup'
                ) as s2:
                    for ev in s2:
                        sel = ev["fullDocument"]
                        print(f"[{courier['id']}] ✅ Sélectionné pour {order_id}")

                        # ✅ Vérification sécurisée (évite KeyError)
                        pickup = sel.get("pickup")
                        dropoff = sel.get("dropoff")
                        if not pickup or not dropoff:
                            print(f"[{courier['id']}] ⚠️ Erreur : champs 'pickup'/'dropoff' absents dans l'assignation.")
                            print("→ Vérifie que manager_mongo.py insère bien ces champs.")
                            continue

                        target_total_s = max(5, int(sel.get("eta_min", 10)*60))

                        def dist(a_lat,a_lon,b_lat,b_lon):
                            return hav(a_lat,a_lon,b_lat,b_lon)

                        d_pick = dist(lat,lon,float(pickup["lat"]),float(pickup["lon"]))
                        d_drop = dist(float(pickup["lat"]),float(pickup["lon"]),
                                      float(dropoff["lat"]),float(dropoff["lon"]))
                        dur_pick = (d_pick / max(1e-6, VITESSE_KMH)) * 3600
                        dur_drop = (d_drop / max(1e-6, VITESSE_KMH)) * 3600
                        total_raw = max(1.0, dur_pick + PAUSE_S + dur_drop)
                        scale = target_total_s / total_raw
                        dur_pick *= scale
                        dur_drop *= scale
                        global_remaining = dur_pick + PAUSE_S + dur_drop

                        # 1️⃣ Vers le restaurant
                        move_and_track(db, order_id, courier, (lat,lon),
                                       (float(pickup["lat"]),float(pickup["lon"])),
                                       "vers_resto", dur_pick, global_remaining)
                        time.sleep(PAUSE_S)

                        # 2️⃣ Vers le client
                        lat, lon = float(pickup["lat"]), float(pickup["lon"])
                        global_remaining -= dur_pick + PAUSE_S
                        move_and_track(db, order_id, courier, (lat,lon),
                                       (float(dropoff["lat"]),float(dropoff["lon"])),
                                       "vers_client", dur_drop, global_remaining)
                        print(f"[{courier['id']}] 🎯 Livraison terminée pour {order_id}")
                        break

    except KeyboardInterrupt:
        print("\n[COURSIER] Arrêt manuel.")
    finally:
        client.close()

if __name__ == "__main__":
    main()

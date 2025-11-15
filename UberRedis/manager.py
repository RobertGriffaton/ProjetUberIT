import json, time, math, sys, csv, os
import redis

# ----- Réglages ETA -----
VITESSE_KMH = 20.0        # vitesse moyenne
DELAI_FIXE_MIN = 0.5      # délai fixe additionnel
TIMEOUT_S = 15            # fenêtre de candidatures
REWARD_EUR = 8.5
CSV_PATH = "menus.csv"

# ----- Canaux -----
CHAN_ORDERS = "orders"                 # client -> manager
CHAN_OFFERS = "offers"                 # manager -> coursiers (annonce)
CHAN_CANDIDATES = "candidates:{oid}"   # coursiers -> manager
CHAN_ASSIGN = "assignments:{oid}"      # manager -> client + coursier

def rconn():
    return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    lat1 = math.radians(a_lat); lat2 = math.radians(b_lat)
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def eta_minutes(c_pos, pickup, drop):
    d1 = haversine_km(c_pos[0], c_pos[1], pickup[0], pickup[1])
    d2 = haversine_km(pickup[0], pickup[1], drop[0], drop[1])
    minutes = ((d1 + d2) / max(1e-6, VITESSE_KMH)) * 60.0 + DELAI_FIXE_MIN
    return max(1, int(round(minutes)))

def get_rating_average(r, courier_name):
    data = r.hgetall(f"ratings:{courier_name}")  # fields: sum, count, avg
    if not data:
        return 3.0  # neutre par défaut si pas encore noté
    try:
        return float(data.get("avg", 3.0))
    except Exception:
        return 3.0

def normalize_name(name: str) -> str:
    return " ".join((name or "").strip().split()).casefold()

def load_restos_from_csv(path):
    """Retourne un dict clé=nom_normalisé -> (lat, lon)"""
    mapping = {}
    if not os.path.exists(path):
        print(f"[MANAGER] ⚠️ CSV introuvable: {path}.")
        return mapping
    with open(path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name_raw = (row.get("restaurant") or "").strip()
            if not name_raw:
                continue
            key = normalize_name(name_raw)
            try:
                lat = float(row["latitude"]); lon = float(row["longitude"])
            except Exception:
                continue
            if key not in mapping:
                mapping[key] = (lat, lon)
    print(f"[MANAGER] CSV chargé : {len(mapping)} restaurants uniques.")
    return mapping

def prompt_select_or_auto(cands_sorted):
    print("\n[MANAGER] 📊 Candidatures (tri ETA ↑ puis Note ↓):")
    for i, c in enumerate(cands_sorted, 1):
        print(f" {i}) {c['courier']} | ETA={c['eta_min']} min | Note={c['rating']:.2f}")
    try:
        raw = input("[MANAGER] Choisir un livreur (1..N) ou Entrée pour auto : ").strip()
    except EOFError:
        raw = ""
    if raw == "":
        return cands_sorted[0]
    try:
        idx = int(raw)
        if 1 <= idx <= len(cands_sorted):
            return cands_sorted[idx-1]
    except Exception:
        pass
    print("[MANAGER] Choix invalide → sélection auto.")
    return cands_sorted[0]

def main():
    r = rconn()
    restos = load_restos_from_csv(CSV_PATH)

    ps = r.pubsub()
    ps.subscribe(CHAN_ORDERS)
    print("[MANAGER] En attente de commandes sur", CHAN_ORDERS)

    for msg in ps.listen():
        if msg.get("type") != "message":
            continue
        try:
            order = json.loads(msg["data"])
        except Exception:
            continue
        if order.get("type") != "ORDER":
            continue

        order_id = order["order_id"]
        resto_name = order["restaurant"]["name"]
        drop = (float(order["customer"]["lat"]), float(order["customer"]["lon"]))

        key = normalize_name(resto_name)
        if key in restos:
            pickup = restos[key]
        else:
            # fallback coordonnées envoyées par le client
            pickup = (float(order["restaurant"]["lat"]), float(order["restaurant"]["lon"]))

        print(f"\n[MANAGER] 📣 Commande {order_id} ({resto_name}) → annonce envoyée aux coursiers…")

        # 1) Annonce globale
        offer = {
            "type": "OFFER",
            "order_id": order_id,
            "restaurant": {"name": resto_name, "lat": pickup[0], "lon": pickup[1]},
            "dropoff": {"lat": drop[0], "lon": drop[1]},
            "reward_eur": REWARD_EUR
        }
        r.publish(CHAN_OFFERS, json.dumps(offer))

        # 2) Collecte candidatures
        cand_chan = CHAN_CANDIDATES.format(oid=order_id)
        ps_cand = r.pubsub()
        ps_cand.subscribe(cand_chan)

        cands = []
        start = time.monotonic()
        while time.monotonic() - start < TIMEOUT_S:
            m = ps_cand.get_message(timeout=0.2)
            if not m or m.get("type") != "message":
                continue
            try:
                cand = json.loads(m["data"])
            except Exception:
                continue
            if cand.get("type") != "CANDIDATURE" or cand.get("order_id") != order_id:
                continue

            courier = cand["courier"]
            pos = (float(cand["position"]["lat"]), float(cand["position"]["lon"]))
            eta_min = eta_minutes(pos, pickup, drop)
            rating = get_rating_average(r, courier)

            cands.append({"courier": courier, "eta_min": eta_min, "rating": rating})
            print(f"[MANAGER] 📥 {courier} (ETA={eta_min} min, Note={rating:.2f})")

        if not cands:
            print("[MANAGER] 😕 Aucune candidature reçue.")
            continue

        cands.sort(key=lambda c: (c["eta_min"], -c["rating"]))
        chosen = prompt_select_or_auto(cands)

        # 3) Affectation
        assign = {
            "type": "SELECTION",
            "order_id": order_id,
            "courier_id": chosen["courier"],
            "courier_name": chosen["courier"],
            "eta_min": int(chosen["eta_min"]),
            "reward_eur": REWARD_EUR,
            "pickup": {"lat": pickup[0], "lon": pickup[1]},
            "dropoff": {"lat": drop[0], "lon": drop[1]},
            "assigned_at": int(time.time())
        }
        assign_chan = CHAN_ASSIGN.format(oid=order_id)
        r.publish(assign_chan, json.dumps(assign))
        print(f"[MANAGER] ✅ Affecté : {chosen['courier']} (ETA={chosen['eta_min']} min, Note={chosen['rating']:.2f})")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[MANAGER] Arrêt.")
        sys.exit(0)

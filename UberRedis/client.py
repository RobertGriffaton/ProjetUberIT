

import json, time, uuid, sys, csv, os
import redis

CLIENT_LAT = 48.8610
CLIENT_LON = 2.3450
CSV_PATH = "menus.csv"

CHAN_ORDERS = "orders"
CHAN_ASSIGN = "assignments:{oid}"
CHAN_TRACKING = "tracking:{oid}"

def rconn():
    return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def load_from_csv(path):
    """
    Retourne:
      - restos: liste ordonnée de (name, lat, lon)
      - menus: dict name -> liste d'items
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV introuvable: {path}")

    restos_order = []
    seen = set()
    menus = {}

    with open(path, newline='', encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("restaurant") or "").strip()
            item = (row.get("item") or "").strip()
            try:
                lat = float(row["latitude"]); lon = float(row["longitude"])
            except Exception:
                continue
            if not name or not item:
                continue

            if name not in seen:
                restos_order.append((name, lat, lon))
                seen.add(name)
            menus.setdefault(name, []).append(item)

    if not restos_order:
        raise RuntimeError("Aucun restaurant valide trouvé dans le CSV.")
    return restos_order, menus

def choose_restaurant_and_item(restos, menus):
    print("Restaurants disponibles :")
    for i,(name,_,_) in enumerate(restos,1):
        print(f"{i}) {name}")
    idx = -1
    while idx not in range(1, len(restos)+1):
        try:
            idx = int(input("Choisir un restaurant : "))
        except Exception:
            idx = -1
    resto, rlat, rlon = restos[idx-1]

    items = menus.get(resto, [])
    if not items:
        raise RuntimeError(f"Aucun plat trouvé pour {resto} dans le CSV.")
    print(f"Menu de {resto} :")
    for j,it in enumerate(items,1):
        print(f"{j}) {it}")
    k = -1
    while k not in range(1, len(items)+1):
        try:
            k = int(input("Choisir un plat : "))
        except Exception:
            k = -1
    item = items[k-1]
    return resto, rlat, rlon, item

def update_rating(r, courier, score):
    key = f"ratings:{courier}"
    r.hincrby(key, "sum", score)
    r.hincrby(key, "count", 1)
    data = r.hgetall(key)
    s = int(data.get("sum", 0))
    c = int(data.get("count", 1))
    avg = s / max(1, c)
    r.hset(key, mapping={"avg": avg})
    return avg, c

def phase_from_status(status: str) -> str:
    if status.startswith("vers_resto"):
        return "vers_resto"
    if status.startswith("vers_client"):
        return "vers_client"
    return "autre"

def main():
    r = rconn()
    restos, menus = load_from_csv(CSV_PATH)
    resto, rlat, rlon, item = choose_restaurant_and_item(restos, menus)

    order_id = str(uuid.uuid4())
    order = {
        "type":"ORDER",
        "order_id": order_id,
        "restaurant": {"name": resto, "lat": rlat, "lon": rlon},
        "items": [{"name": item, "qty": 1}],
        "customer": {"name":"Client POC", "lat": CLIENT_LAT, "lon": CLIENT_LON},
        "created_at": int(time.time())
    }
    r.publish(CHAN_ORDERS, json.dumps(order))
    print(f"[CLIENT] 🧾 Commande envoyée : {order_id} ({resto} / {item})")
    print("[CLIENT] ⏳ En attente d'attribution…")

    # Attente affectation
    ps = r.pubsub()
    ps.subscribe(CHAN_ASSIGN.format(oid=order_id))
    courier = None
    eta_min = None
    for _ in range(6000):
        m = ps.get_message(timeout=0.2)
        if not m or m.get("type") != "message":
            continue
        try:
            sel = json.loads(m["data"])
        except Exception:
            continue
        if sel.get("type") == "SELECTION" and sel.get("order_id") == order_id:
            courier = sel.get("courier_id")
            eta_min = sel.get("eta_min")
            print(f"[CLIENT] ✅ Livreur attribué : {courier} (ETA ≈ {eta_min} min)")
            break

    if not courier:
        print("[CLIENT] 😕 Pas d'attribution.")
        return

    # Suivi en temps réel — 2 phases 0→100 chacune (0/25/50/75/100)
    print("[CLIENT] 🚴 Suivi en temps réel… (0/25/50/75/100 par phase)")
    ps2 = r.pubsub()
    ps2.subscribe(CHAN_TRACKING.format(oid=order_id))

    last_phase = None
    last_local_pct = -1

    try:
        for _ in range(36000):
            m = ps2.get_message(timeout=0.5)
            if not m or m.get("type") != "message":
                continue
            try:
                t = json.loads(m["data"])
            except Exception:
                continue
            if t.get("type") != "TRACK":
                continue

            status = t.get("status","")
            phase = phase_from_status(status)

            # --- 1) FIN DE LIVRAISON : tester AVANT l'anti-doublon ---
            if status in ("vers_client_arrived", "livre", "vers_client_arrived_arrived"):
                lat = t.get("lat"); lon = t.get("lon")
                print(f"[SUIVI] {status:<18} | prog=100% | pos=({lat:.5f},{lon:.5f}) | eta~0 min")
                print("[CLIENT] 🎉 Livraison terminée.")
                break

            # --- 2) Changement de phase : reset du % local ---
            if phase != last_phase and phase in ("vers_resto", "vers_client"):
                if phase == "vers_resto":
                    print("\n--- Phase 1/2 : vers le restaurant ---")
                elif phase == "vers_client":
                    print("\n--- Phase 2/2 : vers le client ---")
                last_local_pct = -1
                last_phase = phase

            # --- 3) Pourcentage local + anti-doublon ---
            local_pct = int(t.get("progress", 0))
            if local_pct == last_local_pct:
                continue
            last_local_pct = local_pct

            lat = t.get("lat"); lon = t.get("lon")
            eta_min_remain = int(t.get("global_eta_s", 0) // 60)
            print(f"[SUIVI] {status:<18} | prog={local_pct:>3}% | pos=({lat:.5f},{lon:.5f}) | eta~{eta_min_remain} min")
    except KeyboardInterrupt:
        print("\n[CLIENT] Arrêt du suivi.")

    # Notation du coursier — agrégé + historique persistant
    while True:
        try:
            score = int(input(f"Notez {courier} (1 à 5) : "))
            if 1 <= score <= 5: break
        except Exception:
            pass
        print("Saisie invalide.")

    avg, cnt = update_rating(r, courier, score)
    # Historique détaillé
    r.lpush(
        f"ratings_history:{courier}",
        json.dumps({"order_id": order_id, "score": int(score), "ts": int(time.time())})
    )
    # (optionnel) limiter à 100 dernières : r.ltrim(f"ratings_history:{courier}", 0, 99)

    print(f"⭐ Merci ! Nouvelle moyenne de {courier} : {avg:.2f}/5 ({cnt} avis)")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[CLIENT] Arrêt.")
        sys.exit(0)

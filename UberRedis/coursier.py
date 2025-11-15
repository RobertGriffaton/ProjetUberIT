import json, time, math, random, sys
import redis

VITESSE_KMH = 20.0
CENTER_LAT, CENTER_LON = 48.8660, 2.3350
JITTER_KM = 0.3
TICK_SEC = 1.0
PAUSE_S = 2.0

NAMES = ["Alex","Sam","Robin","Camille","Noa","Lina","Mael","Eli","Nora","Rayan",
         "Milan","Yanis","Léa","Jules","Zoé","Léo","Inès","Sacha","Aya","Nils","Pierre"]

CHAN_OFFERS = "offers"
CHAN_CANDIDATES = "candidates:{oid}"
CHAN_ASSIGN = "assignments:{oid}"
CHAN_TRACKING = "tracking:{oid}"

def rconn():
    return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

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

def publish_tracking(r, order_id, courier, status, lat, lon, local_progress, eta_s, global_eta_s, global_progress):
    track = {
        "type":"TRACK","order_id":order_id,"courier_id":courier,"status":status,
        "lat":lat,"lon":lon,
        "progress":local_progress,            # % du tronçon (0/25/50/75/100)
        "global_progress": global_progress,   # % global si tu veux l'utiliser
        "eta_s":eta_s,"global_eta_s":global_eta_s,
        "sent_at": int(time.time())
    }
    r.publish(CHAN_TRACKING.format(oid=order_id), json.dumps(track))

def move_segment(r, order_id, courier, start, target, status_label,
                 planned_s, global_remain_s, base_elapsed_s, total_target_s):
    """
    - planned_s: durée visée pour CE tronçon
    - global_remain_s: temps global restant au début du tronçon
    - base_elapsed_s: temps global déjà passé AVANT le tronçon
    - total_target_s: durée globale visée (dur_pick + PAUSE + dur_drop)
    """
    steps = max(5, int(planned_s // TICK_SEC))
    t0 = time.time()
    last_local_quarter = -25  # anti-doublon 0/25/50/75/100

    for step in range(steps+1):
        t = step/steps
        lat = lerp(start[0], target[0], t)
        lon = lerp(start[1], target[1], t)

        # ---- Progression locale strictement aux quarts
        local_pct = int(round(t * 100))
        local_quarter = (local_pct // 25) * 25
        if local_quarter > 100:
            local_quarter = 100
        if local_quarter == last_local_quarter:
            time.sleep(TICK_SEC)
            continue
        last_local_quarter = local_quarter

        # ---- Progression globale (optionnelle)
        elapsed_local = time.time() - t0
        elapsed_global = base_elapsed_s + min(planned_s, elapsed_local)
        global_pct = int(round((elapsed_global / max(1e-6, total_target_s)) * 100))
        global_quarter = (global_pct // 25) * 25
        if global_quarter > 100:
            global_quarter = 100

        # ---- ETAs
        local_eta  = max(0, int(planned_s - elapsed_local))
        global_eta = max(0, int(global_remain_s - elapsed_local))

        publish_tracking(
            r, order_id, courier, status_label, lat, lon,
            local_quarter, local_eta, global_eta, global_quarter
        )
        time.sleep(TICK_SEC)

    # fin de tronçon = 100%
    publish_tracking(
        r, order_id, courier, f"{status_label}_arrived",
        target[0], target[1],
        100, 0,
        max(0, int(global_remain_s - planned_s)),
        min(100, int(round((base_elapsed_s + planned_s)/max(1e-6,total_target_s)*100)))
    )

def main():
    r = rconn()
    name = random.choice(NAMES)
    courier = name
    lat, lon = jitter(CENTER_LAT, CENTER_LON, JITTER_KM)
    print(f"[COURSIER {courier}] En ligne | pos=({lat:.5f},{lon:.5f})")

    ps = r.pubsub()
    ps.subscribe(CHAN_OFFERS)
    print("[COURSIER] En écoute des annonces…")

    for msg in ps.listen():
        if msg.get("type") != "message":
            continue
        try:
            offer = json.loads(msg["data"])
        except Exception:
            continue
        if offer.get("type") != "OFFER":
            continue

        order_id = offer["order_id"]
        resto = offer["restaurant"]["name"]
        print(f"[{courier}] Offre reçue: {order_id} → {resto}")
        try:
            ans = input(f"[{courier}] Accepter ? (o/N) ").strip().lower()
        except EOFError:
            ans = "n"
        if ans != "o":
            print(f"[{courier}] ❌ Refusé")
            continue

        # candidature
        cand = {
            "type":"CANDIDATURE",
            "order_id": order_id,
            "courier": courier,
            "position": {"lat": lat, "lon": lon},
            "sent_at": int(time.time())
        }
        r.publish(CHAN_CANDIDATES.format(oid=order_id), json.dumps(cand))
        print(f"[{courier}] 📨 Candidature envoyée")

        # attente sélection
        ps2 = r.pubsub()
        ps2.subscribe(CHAN_ASSIGN.format(oid=order_id))
        print(f"[{courier}] Attente sélection…")

        chosen = None
        t0 = time.time()
        while True:
            m = ps2.get_message(timeout=0.2)
            if m and m.get("type") == "message":
                try:
                    sel = json.loads(m["data"])
                except Exception:
                    sel = {}
                if sel.get("type") == "SELECTION" and sel.get("order_id") == order_id and sel.get("courier_id") == courier:
                    chosen = sel
                    break
            if time.time() - t0 > 120:
                print(f"[{courier}] ⏳ Pas sélectionné, on passe.")
                break

        if not chosen:
            continue

        print(f"[{courier}] ✅ Sélectionné (ETA={chosen['eta_min']} min)")
        pickup = (float(chosen["pickup"]["lat"]), float(chosen["pickup"]["lon"]))
        drop   = (float(chosen["dropoff"]["lat"]), float(chosen["dropoff"]["lon"]))
        target_total_s = max(5, int(chosen["eta_min"] * 60))

        # trajectoire (recalée sur ETA)
        def dist(a,b): return hav(a[0],a[1],b[0],b[1])
        d_pick = dist((lat,lon), pickup)
        d_drop = dist(pickup, drop)
        dur_pick = (d_pick / max(1e-6, VITESSE_KMH)) * 3600
        dur_drop = (d_drop / max(1e-6, VITESSE_KMH)) * 3600
        total_raw = max(1.0, dur_pick + PAUSE_S + dur_drop)
        scale = target_total_s / total_raw
        dur_pick *= scale; dur_drop *= scale

        total_target_s = dur_pick + PAUSE_S + dur_drop
        base_elapsed = 0.0

        # 1) Vers le resto
        move_segment(r, order_id, courier, (lat,lon), pickup,
                     "vers_resto", dur_pick, total_target_s, base_elapsed, total_target_s)
        time.sleep(PAUSE_S)
        base_elapsed += dur_pick + PAUSE_S

        # 2) Vers le client
        lat, lon = pickup
        remaining_global = max(0.0, total_target_s - base_elapsed)
        move_segment(r, order_id, courier, (lat,lon), drop,
                     "vers_client", dur_drop, remaining_global, base_elapsed, total_target_s)
        print(f"[{courier}] 🎯 Livraison terminée pour {order_id}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[COURSIER] Arrêt.")
        sys.exit(0)

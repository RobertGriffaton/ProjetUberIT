# README — Projet « Ubeer » (version **Redis**)

POC qui simule une mini-plateforme type UberEats avec **Redis Pub/Sub** :
**client** passe commande → **manager** publie une annonce → **coursiers** candidatent → le manager attribue au meilleur → **tracking en 2 phases (0/25/50/75/100)** → **client note** le coursier.
Les **notes sont persistées** dans Redis (AOF) et **influencent** l’attribution (ETA ↑ puis **note moyenne ↓**).

---

## 1) Prérequis

- **Python 3.9+**
- **Redis** pour Windows (portable) ou Linux/Mac
- `menus.csv` à la racine (colonnes minimales : `restaurant,latitude,longitude,item`)

### Installer les dépendances Python

```bash
pip install -r requirements.txt
```

---

## 2) Démarrer Redis (Windows)

Ouvre **PowerShell** :

```powershell
cd "C:\Users\Robert\Downloads\Redis"
mkdir "C:\Users\Robert\Downloads\Redis\data"  # 1ère fois seulement

# Lancer le serveur Redis avec persistance AOF activée
.\redis-server.exe --appendonly yes --appendfsync everysec --dir "C:\Users\Robert\Downloads\Redis\data"
```

> Laisse **cette fenêtre ouverte** (c’est le serveur).
> Le fichier de sauvegarde sera créé dans `...\Redis\data\appendonly.aof` (ou `appendonlydir\...`).

### (Linux/Mac)

```bash
redis-server --appendonly yes --appendfsync everysec
```

---

## 3) Lancer l’app (3 terminaux)

> Adapte le chemin jusqu’au dossier du projet si besoin.

### Terminal A — Manager

```powershell
cd "C:\Users\Robert\Downloads\projetUbeer\projetUbeer"
python manager.py
```

### Terminal B — Coursier (tu peux en ouvrir 1 à 3)

```powershell
cd "C:\Users\Robert\Downloads\projetUbeer\projetUbeer"
python coursier.py
```

### Terminal C — Client

```powershell
cd "C:\Users\Robert\Downloads\projetUbeer\projetUbeer"
python client.py
```

---

## 4) Scénario de démo (pour le prof)

1. **Client** choisit un restaurant / un plat (depuis `menus.csv`).
2. **Manager** diffuse l’annonce, **attend 15 s** les candidatures, puis :

   - **appuie Entrée** ➜ attribution **automatique** (meilleur ETA puis meilleure **note**), ou
   - **tape un numéro** (1..N) ➜ attribution **manuelle**.

3. **Coursier** sélectionné simule 2 tronçons :

   - **Phase 1/2** : _vers le restaurant_ → 0/25/50/75/100
   - **Phase 2/2** : _vers le client_ → 0/25/50/75/100

4. **Client** voit le suivi en temps réel **par quarts** (pas d’intermédiaires 6%/13%).
5. À la fin, **client** attribue une **note (1–5)** :

   - `ratings:<prenom>` (Hash) mis à jour : `sum`, `count`, `avg`
   - `ratings_history:<prenom>` (List) reçois l’entrée `{order_id, score, ts}`
   - grâce à l’**AOF**, tout **persiste** au redémarrage.

---

## 5) Commandes Redis utiles (cheat-sheet)

Ouvre un **client Redis** dans un autre PowerShell :

```powershell
cd "C:\Users\Robert\Downloads\Redis"
.\redis-cli.exe
```

### Vérifier la persistance

```text
INFO persistence     # aof_enabled:1 et aof_last_write_status:ok = OK
```

### Lister les livreurs notés

```text
SCAN 0 MATCH ratings:* COUNT 100
```

### Voir la moyenne / nombre d’avis d’un livreur

```text
HGETALL ratings:Noa
# ou
HGET ratings:Noa avg
HGET ratings:Noa count
```

### Voir l’historique des notes d’un livreur

```text
LRANGE ratings_history:Noa 0 -1
```

### Remise à zéro (sans toucher au fichier AOF)

```text
FLUSHALL
```

> **Attention** : `FLUSHALL` efface toutes les clés en mémoire (et sera reflété dans l’AOF).

---

## 6) Structure des fichiers (version Redis)

```
projetUbeer/
├─ manager.py        # écoute orders, publie offers, collecte candidatures, trie (ETA -> rating), attribue
├─ coursier.py       # écoute offers, candidate, suit l’attribution, publie tracking (0/25/50/75/100)
├─ client.py         # choix menu, envoi order, suivi en 2 phases, saisie et enregistrement des notes
├─ menus.csv         # restaurants + coords + items (source des menus)
├─ requirements.txt
```

---

## 7) Points clés pour la présentation

- **Pub/Sub Redis** :
  `orders` (client→manager), `offers` (manager→coursiers),
  `candidates:<order_id>` (coursiers→manager),
  `assignments:<order_id>` (manager→client+coursier),
  `tracking:<order_id>` (coursier→client).
- **ETA réaliste & court** : vitesse 20 km/h + 0.5 min fixe.
- **Attribution “intelligente”** : tri par **ETA** puis **note moyenne**.
- **Notes persistées** (AOF) et **réellement utilisées** par le manager.
- **Suivi par quarts** (0/25/50/75/100) : lisible, pas de spam de lignes.
- **CSV → JSON** à la volée (pas de fichier .json externe) : le CSV est lu, puis les messages sont échangés en JSON via Redis.

---

## 8) Dépannage rapide

- Rien ne s’affiche côté client ➜ vérifier que **`manager.py`** tourne et que **Redis** est lancé.
- Coursier ne reçoit pas d’annonce ➜ ouvrir **au moins 1 coursier** et vérifier l’acceptation `(o/N)`.
- “AOF unable to turn on” ➜ lancer `redis-server` avec
  `--dir "C:\Users\Robert\Downloads\Redis\data"` (dossier écrivable).
- Redémarrage machine ➜ relancer **Redis**, puis **manager**, **coursier(s)**, **client** (ordre recommandé).

---

## 9) Annexes (optionnelles)

### Lancer Redis en 1 clic (Windows)

Crée `start-redis.bat` dans `C:\Users\Robert\Downloads\Redis` :

```bat
@echo off
cd /d C:\Users\Robert\Downloads\Redis
start "" cmd /k ".\redis-server.exe --appendonly yes --appendfsync everysec --dir C:\Users\Robert\Downloads\Redis\data"
```

Crée `redis-cli.bat` :

```bat
@echo off
cd /d C:\Users\Robert\Downloads\Redis
start "" cmd /k ".\redis-cli.exe"
```

---

Si tu veux, je peux aussi te générer un **mini aide-mémoire A4** (PDF) avec les 10 commandes Redis à montrer pendant la soutenance.

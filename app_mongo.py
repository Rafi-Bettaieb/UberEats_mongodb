from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
import hashlib
import uuid
import time
import threading
import json
from datetime import datetime, timedelta
from pymongo import MongoClient, GEOSPHERE, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import json_util # Important pour sérialiser les données BSON (comme les dates)
import os # Ajout pour le chemin du JSON

app = Flask(__name__)
app.secret_key = 'votre_cle_secrete'

# --- Connexion MongoDB ---
try:
    # Utilisation d'une variable d'environnement pour l'URI, sinon fallback
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb+srv://rafiibettaieb004:3gFC65o82k4DppKb@cluster0.1drqg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
    client = MongoClient(MONGO_URI)
    db = client['delivery_db'] # Nom de la base de données

    # Définition des collections
    users_col = db['users']
    orders_col = db['orders']
    stats_col = db['livreur_stats']
    positions_col = db['livreurs_positions']
    restaurants_col = db['restaurants'] # NOUVELLE COLLECTION
    
    # Collection pour le "Pub/Sub" via Change Streams
    if 'events' not in db.list_collection_names():
        db.create_collection("events", capped=True, size=10 * 1024 * 1024) # 10MB
    events_col = db['events']
    
    print("✅ Connexion à MongoDB réussie.")

except Exception as e:
    print(f"❌ Erreur de connexion à MongoDB: {e}")
    exit()
# -------------------------


# === FONCTION MODIFIÉE: Initialisation depuis le JSON ===
def init_test_users():
    try:
        # Ouvrir et lire le fichier JSON
        with open('donnees_fusionnees_avec_menus.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("ERREUR: Le fichier 'donnees_denormalisees.json' est introuvable.")
        return
    except json.JSONDecodeError:
        print("ERREUR: Le fichier 'donnees_denormalisees.json' contient un JSON invalide.")
        return

    print("Initialisation des utilisateurs...")
    
    # === Initialiser les utilisateurs (clients, managers) ===
    for user in data.get('utilisateurs', []):
        username = user.get('username')
        if not username:
            continue
        
        try:
            users_col.update_one(
                {"_id": username},
                {"$setOnInsert": {
                    "_id": username,
                    "password": user['password_hash'],
                    "role": user['role']
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Erreur init user {username}: {e}")

    # === Initialiser les livreurs ===
    for livreur_data in data.get('livreurs', []):
        username = livreur_data.get('username')
        if not username:
            continue
        
        # 1. Créer l'utilisateur
        try:
            users_col.update_one(
                {"_id": username},
                {"$setOnInsert": {
                    "_id": username,
                    "password": livreur_data['password_hash'],
                    "role": livreur_data['role']
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Erreur init livreur user {username}: {e}")

        # 2. Initialiser les scores et statistiques
        stats = livreur_data.get('livreur', {})
        avg_rating = stats.get('avg_rating', 4.5)
        
        stats_col.update_one(
            {"_id": username},
            {"$setOnInsert": {
                "_id": username,
                "avg_rating": avg_rating,
                "delivery_count": 1, # Simuler 1
                "total_rating": avg_rating
            }},
            upsert=True
        )

    # === Initialiser les restaurants et leurs menus ===
    for restaurant_data in data.get('restaurants', []):
        username = restaurant_data.get('username') # username est l'ID (ex: "restaurant1")
        if not username:
            continue
            
        # 1. Créer l'utilisateur
        try:
            users_col.update_one(
                {"_id": username},
                {"$setOnInsert": {
                    "_id": username,
                    "password": restaurant_data['password_hash'],
                    "role": restaurant_data['role']
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Erreur init restaurant user {username}: {e}")

        info = restaurant_data.get('restaurant', {})
        if not info:
            print(f"AVERTISSEMENT: Pas d'infos 'restaurant' pour {username}")
            continue
            
        # 2. Stocker les infos (nom, localisation, menu)
        lon = float(info.get("longitude", 0.0))
        lat = float(info.get("latitude", 0.0))
        
        # Le menu est déjà une liste d'objets, parfait pour Mongo
        menu_list = info.get('menu', []) 
        
        restaurants_col.update_one(
            {"_id": username},
            {"$setOnInsert": {
                "_id": username,
                "name": info.get("nom", username),
                "location": {
                    "type": "Point",
                    "coordinates": [lon, lat] # [Longitude, Latitude]
                },
                "menu": menu_list # Stocker la liste de menus directement
            }},
            upsert=True
        )
    
    print("Initialisation des données de test depuis le JSON terminée.")
    
   # --- Création des index MongoDB ---
    print("Création des index MongoDB...")
    users_col.create_index("role")
    orders_col.create_index("client")
    orders_col.create_index("status")
    orders_col.create_index("assigned_driver")
    orders_col.create_index("restaurant")
    orders_col.create_index([("candidates", ASCENDING)])
    orders_col.create_index([("created_at", DESCENDING)])
    stats_col.create_index([("avg_rating", DESCENDING)])
    positions_col.create_index([("location", GEOSPHERE)])
    restaurants_col.create_index([("location", GEOSPHERE)])
    restaurants_col.create_index([("name", "text")])  # NOUVEL INDEX pour la recherche
    print("Index créés.")
# =========================================================


def publish_event(event_type, data):
    """Publie un événement en l'insérant dans la collection 'events'."""
    try:
        event_data = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now()
        }
        events_col.insert_one(event_data)
    except Exception as e:
        print(f"Erreur lors de la publication de l'événement: {e}")

def get_livreur_score(livreur_id):
    stats = stats_col.find_one({"_id": livreur_id})
    return float(stats['avg_rating']) if stats and 'avg_rating' in stats else 0.0

def get_all_orders_with_details():
    # Convertit le curseur en liste et trie
    return list(orders_col.find().sort("created_at", DESCENDING))

def get_assigned_orders_for_livreur(livreur_id):
    return list(orders_col.find({
        "assigned_driver": livreur_id,
        "status": "assigned"
    }).sort("created_at", DESCENDING))

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# === ROUTE MODIFIÉE: Ajout du nom du restaurant en session ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        user_data = users_col.find_one({"_id": username})
        
        if user_data:
            stored_hash = user_data['password']
            stored_role = user_data['role']
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if password_hash == stored_hash and role == stored_role:
                session['username'] = username
                session['role'] = role
                
                # Si c'est un restaurant, stocker son nom
                if role == 'restaurant':
                    info = restaurants_col.find_one({"_id": username}, {"name": 1})
                    session['restaurant_name'] = info.get('name', username) if info else username
                
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
        
        flash('Identifiants incorrects', 'error')
    
    return render_template('login.html')
# =============================================================

# === ROUTE MODIFIÉE: Logique restaurant mise à jour ===
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    role = session['role']
    username = session['username']
    
    if role == 'client':
        orders = get_client_orders(username)
        return render_template('client_simple.html', username=username, orders=orders)
    elif role == 'manager':
        all_orders = get_all_orders_with_details()
        return render_template('manager_simple.html', 
                             username=username,
                             all_orders=all_orders,
                             get_livreur_score=get_livreur_score)
    elif role == 'restaurant':
        # MODIFIÉ: Obtenir les commandes pour ce restaurant spécifique
        orders = get_restaurant_orders(username)
        restaurant_name = session.get('restaurant_name', username)
        return render_template('restaurant_simple.html', 
                             username=restaurant_name, # Afficher le nom complet
                             orders=orders)
    elif role == 'livreur':
        available_orders = get_available_orders()
        my_interests = get_my_interests(username)
        assigned_orders = get_assigned_orders_for_livreur(username)
        return render_template('livreur_simple.html', 
                             username=username, 
                             available_orders=available_orders, 
                             my_interests=my_interests,
                             assigned_orders=assigned_orders)
    
    return redirect(url_for('login'))
# =======================================================

# === NOUVELLE ROUTE: Obtenir la liste des restaurants ===
@app.route('/get_restaurants')
def get_restaurants():
    if 'username' not in session:
        return jsonify({'status': 'error', 'message': 'Non autorisé'}), 401
    
    restaurants_data = list(restaurants_col.find({}, {"_id": 1, "name": 1}))
    
    # Reformater pour le frontend
    restaurants = [
        {"id": resto["_id"], "name": resto.get("name", resto["_id"])} 
        for resto in restaurants_data
    ]
    
    return jsonify({'status': 'success', 'restaurants': restaurants})
# ========================================================

# === NOUVELLE ROUTE: Obtenir les restaurants paginés avec recherche ===
@app.route('/get_restaurants_paginated')
def get_restaurants_paginated():
    if 'username' not in session:
        return jsonify({'status': 'error', 'message': 'Non autorisé'}), 401
    
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search_term = request.args.get('search', '').strip()
        
        # Construire la requête de recherche
        query = {}
        if search_term:
            # Recherche insensible à la casse dans le nom du restaurant
            query["name"] = {"$regex": search_term, "$options": "i"}
        
        # Compter le nombre total de restaurants (avec filtre si recherche)
        total_restaurants = restaurants_col.count_documents(query)
        
        # Calculer le skip pour la pagination
        skip = (page - 1) * per_page
        
        # Récupérer les restaurants paginés
        restaurants_cursor = restaurants_col.find(
            query, 
            {"_id": 1, "name": 1}
        ).skip(skip).limit(per_page)
        
        # Reformater pour le frontend
        restaurants = [
            {"id": resto["_id"], "name": resto.get("name", resto["_id"])} 
            for resto in restaurants_cursor
        ]
        
        # Calculer la pagination
        total_pages = (total_restaurants + per_page - 1) // per_page if total_restaurants > 0 else 1
        
        return jsonify({
            'status': 'success', 
            'restaurants': restaurants,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_restaurants': total_restaurants,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            },
            'search_term': search_term
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
# ========================================================


# === NOUVELLE ROUTE: Obtenir le menu d'un restaurant ===
@app.route('/get_menu/<restaurant_id>')
def get_menu(restaurant_id):
    if 'username' not in session:
        return jsonify({'status': 'error', 'message': 'Non autorisé'}), 401
    
    resto_data = restaurants_col.find_one({"_id": restaurant_id}, {"menu": 1})
    
    if not resto_data or "menu" not in resto_data:
        return jsonify({'status': 'error', 'message': 'Menu non trouvé'}), 404
    
    # Convertir la liste d'objets en dictionnaire {nom: prix}
    menu_list = resto_data.get('menu', [])
    menu_dict = {
        item['nom_article']: float(item['prix']) 
        for item in menu_list 
        if 'nom_article' in item and 'prix' in item
    }
    
    return jsonify({'status': 'success', 'menu': menu_dict})
# ======================================================

# === ROUTE MODIFIÉE: Passer une commande ===
@app.route('/passer_commande', methods=['POST'])
def passer_commande():
    try:
        data = request.get_json()
        restaurant_id = data.get('restaurant_id')
        items = data.get('items') # Attendu: [{"item": "Pizza", "quantity": 1, "price": 12}, ...]
        
        if not restaurant_id or not items:
            return jsonify({'status': 'error', 'message': 'Données manquantes'}), 400

        id_commande = str(uuid.uuid4())[:8]
        
        # Formater la chaîne des articles
        articles_str = ", ".join([f"{item['quantity']}x {item['item']}" for item in items])
        total_price = sum(item['quantity'] * item['price'] for item in items)
        
        # Récupérer les infos du restaurant (nom, localisation)
        resto_info = restaurants_col.find_one({"_id": restaurant_id})
        if not resto_info:
            return jsonify({'status': 'error', 'message': 'Restaurant non trouvé'}), 404
        
        resto_loc = resto_info.get("location", {}).get("coordinates", [0.0, 0.0])
        
        details_commande = {
            "_id": id_commande,
            "id": id_commande,
            "client": session.get('username'),
            "restaurant": restaurant_id,
            "restaurant_name": resto_info.get("name", restaurant_id),
            "restaurant_lon": str(resto_loc[0]), # lon
            "restaurant_lat": str(resto_loc[1]), # lat
            "articles": articles_str,
            "total_price": total_price,
            "status": "pending",
            "created_at": datetime.now() # Utiliser datetime objet
        }
        
        orders_col.insert_one(details_commande)
        
        # Rendre les détails sérialisables pour l'événement
        details_commande_serializable = json.loads(json_util.dumps(details_commande))
        publish_event('order_created', {'order_id': id_commande, 'details': details_commande_serializable})
        
        return jsonify({'status': 'success', 'order_id': id_commande})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
# =================================================

# === ROUTE MODIFIÉE: Vérification du restaurant ===
@app.route('/marquer_prete/<order_id>', methods=['POST'])
def marquer_prete(order_id):
    try:
        # Vérifier que le restaurant est autorisé
        restaurant_id = session.get('username')
        order_data = orders_col.find_one({"_id": order_id}, {"restaurant": 1})
        
        if not order_data or order_data.get('restaurant') != restaurant_id:
             return jsonify({'status': 'error', 'message': 'Non autorisé'}), 403
             
        # Marquer la commande comme prête
        orders_col.update_one({"_id": order_id}, {"$set": {"status": "ready"}})
        
        # Démarrer la fenêtre de 60s pour les livreurs
        start_acceptance_window(order_id)
        
        print(f"✅ Fenêtre d'acceptation ouverte pour {order_id}")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
# ================================================

# === FONCTION MODIFIÉE: Ajout de order_data à l'événement ===
def start_acceptance_window(order_id):
    """Démarre la fenêtre d'acceptation de 60s pour les livreurs"""
    expiration_time = datetime.now() + timedelta(seconds=60)
    
    # On stocke le timer directement dans le document de la commande
    timer_data = {
        "type": "acceptance_window",
        "expires_at": expiration_time.isoformat(),
        "status": "active",
        "created_at": datetime.now().isoformat()
    }
    orders_col.update_one({"_id": order_id}, {"$set": {"timer": timer_data}})
    
    # Programmer l'expiration pour déclencher la décision manager
    schedule_manager_decision(order_id, 60)
    
    # MODIFIÉ: Envoyer les détails de la commande dans l'événement
    order_data = orders_col.find_one({"_id": order_id})
    # Rendre sérialisable
    order_data_serializable = json.loads(json_util.dumps(order_data))

    publish_event('order_ready', {
        'order_id': order_id,
        'expires_at': expiration_time.isoformat(),
        'order_data': order_data_serializable # Envoyer les détails
    })
# =========================================================

def schedule_manager_decision(order_id, delay_seconds):
    """Programme la décision du manager après un délai"""
    def start_manager_decision():
        time.sleep(delay_seconds)
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data or order_data.get('status') != 'ready':
            return
            
        candidates = order_data.get('candidates', [])
        
        if candidates:
            expiration_time = datetime.now() + timedelta(seconds=60)
            timer_data = {
                "type": "manager_decision",
                "expires_at": expiration_time.isoformat(),
                "status": "active"
            }
            orders_col.update_one({"_id": order_id}, {"$set": {"timer": timer_data}})
            
            publish_event('manager_decision_started', {
                'order_id': order_id,
                'candidates_count': len(candidates),
                'expires_at': expiration_time.isoformat()
            })
            
            print(f"🔄 Fenêtre manager démarrée pour {order_id} avec {len(candidates)} candidats")
            
            schedule_auto_assignment(order_id, 60)
        else:
            orders_col.update_one({"_id": order_id}, {"$unset": {"timer": ""}})
            publish_event('no_candidates', {'order_id': order_id})
            print(f"❌ Aucun candidat pour {order_id}")
    
    thread = threading.Thread(target=start_manager_decision, daemon=True)
    thread.start()

def schedule_auto_assignment(order_id, delay_seconds):
    """Programme l'attribution automatique après un délai"""
    def auto_assign():
        time.sleep(delay_seconds)
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data or order_data.get('status') != 'ready':
            return
            
        candidates = order_data.get('candidates', [])
        
        if candidates:
            resto_lon = order_data.get('restaurant_lon', '2.333')
            resto_lat = order_data.get('restaurant_lat', '48.865')
            
            best_livreur = None
            best_score = -1
            
            for candidate in candidates:
                driver_score = get_livreur_score(candidate)
                
                driver_pos_doc = positions_col.find_one({"_id": candidate})
                
                if driver_pos_doc and 'location' in driver_pos_doc:
                    driver_lon = driver_pos_doc['location']['coordinates'][0]
                    driver_lat = driver_pos_doc['location']['coordinates'][1]
                    
                    distance = calculate_distance(resto_lon, resto_lat, driver_lon, driver_lat)
                    
                    combined_score = (driver_score ** 2) / (distance + 1)
                    
                    if combined_score > best_score:
                        best_score = combined_score
                        best_livreur = candidate
                else:
                    if driver_score > best_score:
                        best_score = driver_score
                        best_livreur = candidate
            
            if best_livreur:
                orders_col.update_one(
                    {"_id": order_id},
                    {
                        "$set": {"status": "assigned", "assigned_driver": best_livreur},
                        "$unset": {"candidates": "", "timer": ""}
                    }
                )
                
                distance_info = ""
                driver_pos_doc = positions_col.find_one({"_id": best_livreur})
                if driver_pos_doc:
                    driver_lon = driver_pos_doc['location']['coordinates'][0]
                    driver_lat = driver_pos_doc['location']['coordinates'][1]
                    distance = calculate_distance(resto_lon, resto_lat, driver_lon, driver_lat)
                    distance_info = f" (distance: {distance}km)"
                
                publish_event('auto_assignment', {
                    'order_id': order_id,
                    'driver_id': best_livreur,
                    'score': get_livreur_score(best_livreur),
                    'distance': distance_info
                })
                
                print(f"🤖 Attribution automatique: {order_id} -> {best_livreur}{distance_info}")
    
    thread = threading.Thread(target=auto_assign, daemon=True)
    thread.start()

@app.route('/montrer_interet/<order_id>', methods=['POST'])
def montrer_interet(order_id):
    try:
        livreur = session.get('username')
        
        order_data = orders_col.find_one({"_id": order_id}, {"timer": 1})
        timer_data = order_data.get('timer')
        
        if not timer_data or timer_data.get('type') != 'acceptance_window':
            return jsonify({'status': 'error', 'message': 'Fenêtre d\'acceptation fermée'}), 400
        
        orders_col.update_one(
            {"_id": order_id},
            {"$addToSet": {"candidates": livreur}}
        )
        
        publish_event('driver_interest', {
            'order_id': order_id,
            'driver_id': livreur,
            'driver_score': get_livreur_score(livreur)
        })
        
        print(f"✅ {livreur} a montré son intérêt pour {order_id}")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/choisir_livreur/<order_id>/<livreur>', methods=['POST'])
def choisir_livreur(order_id, livreur):
    try:
        orders_col.update_one(
            {"_id": order_id},
            {
                "$set": {"status": "assigned", "assigned_driver": livreur},
                "$unset": {"candidates": "", "timer": ""}
            }
        )
        
        publish_event('driver_assigned', {
            'order_id': order_id,
            'driver_id': livreur,
            'assigned_by': session.get('username')
        })
        
        print(f"✅ Manager a choisi {livreur} pour {order_id}")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/marquer_livree/<order_id>', methods=['POST'])
def marquer_livree(order_id):
    try:
        order_data = orders_col.find_one_and_update(
            {"_id": order_id},
            {"$set": {"status": "delivered"}},
            projection={"assigned_driver": 1}
        )
        
        publish_event('order_delivered', {
            'order_id': order_id,
            'driver_id': order_data.get("assigned_driver")
        })
        
        print(f"✅ Commande {order_id} livrée")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_order_candidates/<order_id>')
def get_order_candidates(order_id):
    try:
        order_data = orders_col.find_one({"_id": order_id}, {"candidates": 1, "status": 1})
        if not order_data:
            return jsonify({'status': 'error', 'message': 'Commande non trouvée'}), 404

        candidates = order_data.get('candidates', [])
        candidates_with_scores = []
        
        for candidate in candidates:
            score = get_livreur_score(candidate)
            candidates_with_scores.append({
                'id': candidate,
                'score': score
            })
        
        candidates_with_scores.sort(key=lambda x: x['score'], reverse=True)
        
        return jsonify({
            'status': 'success', 
            'candidates': candidates_with_scores,
            'order_status': order_data.get('status')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_timer_status/<order_id>')
def get_timer_status(order_id):
    try:
        order_data = orders_col.find_one({"_id": order_id}, {"timer": 1})
        timer_data = order_data.get('timer')

        if not timer_data:
            return jsonify({'status': 'expired'})
        
        expires_at = datetime.fromisoformat(timer_data['expires_at'])
        time_left = max(0, (expires_at - datetime.now()).total_seconds())
        
        if time_left == 0:
            return jsonify({'status': 'expired'})

        return jsonify({
            'status': 'active',
            'time_left': int(time_left),
            'type': timer_data.get('type', 'unknown')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/events')
def events():
    """Endpoint Server-Sent Events (SSE) utilisant les Change Streams MongoDB"""
    def generate():
        pipeline = [{'$match': {'operationType': 'insert'}}]
        
        try:
            with events_col.watch(pipeline, full_document='updateLookup') as stream:
                yield "data: {}\n\n".format(json.dumps({'type': 'connected'}))
                
                for change in stream:
                    event_doc = change['fullDocument']
                    event_doc.pop('_id', None) 
                    
                    # Utiliser json_util.dumps pour gérer les types BSON
                    yield "data: {}\n\n".format(json_util.dumps(event_doc))
        except Exception as e:
            print(f"Erreur SSE/Change Stream: {e}")
            yield "data: {}\n\n".format(json.dumps({'type': 'error', 'message': str(e)}))

    return Response(generate(), mimetype='text/event-stream')

@app.route('/debug_timers')
def debug_timers():
    """Page de debug pour voir l'état des timers"""
    timers_info = []
    for order_data in orders_col.find(
        {"timer": {"$exists": True}},
        {"_id": 1, "timer": 1, "candidates": 1, "status": 1}
    ):
        timers_info.append({
            'order_id': order_data['_id'],
            'timer': order_data.get('timer', {}),
            'candidates': order_data.get('candidates', []),
            'order_status': order_data.get('status', 'unknown')
        })
    
    # Utiliser json_util pour sérialiser (car contient des datetime)
    return Response(json_util.dumps(timers_info), mimetype='application/json')

@app.route('/force_auto_assign/<order_id>', methods=['POST'])
def force_auto_assign(order_id):
    try:
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return jsonify({'status': 'error', 'message': 'Commande non trouvée'}), 404

        candidates = order_data.get('candidates', [])
        if not candidates:
            return jsonify({'status': 'error', 'message': 'Aucun candidat'}), 400

        resto_lon = order_data.get('restaurant_lon', '2.333')
        resto_lat = order_data.get('restaurant_lat', '48.865')
        
        best_livreur = None
        best_combined_score = -1
        
        for candidate in candidates:
            driver_score = get_livreur_score(candidate)
            driver_pos_doc = positions_col.find_one({"_id": candidate})
            
            if driver_pos_doc:
                driver_lon = driver_pos_doc['location']['coordinates'][0]
                driver_lat = driver_pos_doc['location']['coordinates'][1]
                distance = calculate_distance(resto_lon, resto_lat, driver_lon, driver_lat)
                combined_score = (driver_score ** 2) / (distance + 1)
                
                if combined_score > best_combined_score:
                    best_combined_score = combined_score
                    best_livreur = candidate
            else:
                if driver_score > best_combined_score:
                    best_combined_score = driver_score
                    best_livreur = candidate
        
        if best_livreur:
            orders_col.update_one(
                {"_id": order_id},
                {
                    "$set": {"status": "assigned", "assigned_driver": best_livreur},
                    "$unset": {"candidates": "", "timer": ""}
                }
            )
            
            distance_info = ""
            final_driver_score = get_livreur_score(best_livreur)
            driver_pos_doc = positions_col.find_one({"_id": best_livreur})
            if driver_pos_doc:
                driver_lon = driver_pos_doc['location']['coordinates'][0]
                driver_lat = driver_pos_doc['location']['coordinates'][1]
                distance = calculate_distance(resto_lon, resto_lat, driver_lon, driver_lat)
                distance_info = f" (distance: {distance}km)"

            publish_event('auto_assignment', {
                'order_id': order_id,
                'driver_id': best_livreur,
                'score': final_driver_score,
                'distance': distance_info
            })
            
            print(f"🤖 [FORCE] Attribution: {order_id} -> {best_livreur}{distance_info}")

            return jsonify({'status': 'success', 
                    'assigned_to': best_livreur,
                    'score': final_driver_score,
                    'combined_score': best_combined_score
                   })
        else:
            return jsonify({'status': 'error', 'message': 'Aucun livreur valide'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    
@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('login'))

# === FONCTION MODIFIÉE: Ajout du tri ===

def get_client_orders(username):
    orders_cursor = orders_col.find({"client": username}).sort("created_at", DESCENDING)
    orders_list = []
    
    # Itérer et convertir les dates en string pour le template
    for order in orders_cursor:
        if order.get('created_at') and isinstance(order['created_at'], datetime):
            order['created_at'] = order['created_at'].isoformat()
            
        if order.get('rated_at') and isinstance(order['rated_at'], datetime):
            order['rated_at'] = order['rated_at'].isoformat()
            
        orders_list.append(order)
        
    return orders_list
# =============================================================
# ======================================

# === FONCTION MODIFIÉE: Obtenir les commandes du restaurant ===
def get_restaurant_orders(restaurant_id):
    # Filtre par restaurant ET par statut
    return list(orders_col.find({
        "restaurant": restaurant_id,
        "status": {"$in": ["pending", "ready", "assigned"]}
    }).sort("created_at", DESCENDING))
# ==========================================================

def get_available_orders():
    # Commandes prêtes et avec fenêtre d'acceptation active
    return list(orders_col.find({
        "status": "ready",
        "timer.type": "acceptance_window"
    }).sort("created_at", DESCENDING))

def get_my_interests(username):
    # Trouve les commandes où l'utilisateur est dans l'array 'candidates'
    return list(orders_col.find({"candidates": username}).sort("created_at", DESCENDING))

@app.route('/annuler_commande/<order_id>', methods=['POST'])
def annuler_commande(order_id):
    try:
        username = session.get('username')
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return jsonify({'status': 'error', 'message': 'Commande non trouvée'}), 404
        
        if order_data.get('client') != username:
            return jsonify({'status': 'error', 'message': 'Vous ne pouvez pas annuler cette commande'}), 403
        
        if order_data.get('status') == 'assigned':
            return jsonify({'status': 'error', 'message': 'Impossible d\'annuler: un livreur a déjà été assigné'}), 400
        
        orders_col.update_one(
            {"_id": order_id},
            {
                "$set": {"status": "cancelled"},
                "$unset": {"candidates": "", "timer": ""}
            }
        )
        
        publish_event('order_cancelled', {
            'order_id': order_id,
            'client': username,
            'reason': 'Annulé par le client'
        })
        
        print(f"❌ Commande {order_id} annulée par {username}")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/noter_livreur/<order_id>', methods=['POST'])
def noter_livreur(order_id):
    try:
        data = request.get_json()
        note = data.get('note')
        username = session.get('username')
        
        if note is None or not (1 <= note <= 5):
            return jsonify({'status': 'error', 'message': 'Note invalide. Doit être entre 1 et 5'}), 400
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return jsonify({'status': 'error', 'message': 'Commande non trouvée'}), 404
        
        if order_data.get('client') != username:
            return jsonify({'status': 'error', 'message': 'Vous ne pouvez noter que vos propres commandes'}), 403
        
        if order_data.get('status') != 'delivered':
            return jsonify({'status': 'error', 'message': 'Vous ne pouvez noter que les commandes livrées'}), 400
        
        if order_data.get("client_rating") is not None:
            return jsonify({'status': 'error', 'message': 'Cette commande a déjà été notée'}), 400
        
        livreur_id = order_data.get('assigned_driver')
        if not livreur_id:
            return jsonify({'status': 'error', 'message': 'Aucun livreur assigné à cette commande'}), 400
        
        orders_col.update_one(
            {"_id": order_id},
            {"$set": {
                "client_rating": note,
                "rated_at": datetime.now()
            }}
        )
        
        update_livreur_score(livreur_id, float(note))
        
        publish_event('driver_rated', {
            'order_id': order_id,
            'driver_id': livreur_id,
            'rating': note,
            'client': username
        })
        
        print(f"⭐ Livreur {livreur_id} noté {note}/5 pour la commande {order_id}")
        return jsonify({'status': 'success', 'message': f'Merci! Vous avez noté {livreur_id} avec {note} étoiles'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def update_livreur_score(livreur_id, new_rating):
    """Met à jour la note moyenne d'un livreur dans la collection 'stats'"""
    try:
        stats_col.update_one(
            {"_id": livreur_id},
            {
                "$inc": {
                    "total_rating": new_rating,
                    "delivery_count": 1
                }
            },
            upsert=True
        )
        
        stats = stats_col.find_one({"_id": livreur_id})
        total_rating = stats.get("total_rating", 0)
        delivery_count = stats.get("delivery_count", 1)
        
        avg_rating = round(total_rating / delivery_count, 2)
        
        stats_col.update_one(
            {"_id": livreur_id},
            {"$set": {"avg_rating": avg_rating}}
        )
        
        print(f"📊 Statistiques mises à jour pour {livreur_id}: {avg_rating}/5 ({delivery_count} livraisons)")
        
    except Exception as e:
        print(f"Erreur mise à jour score livreur: {e}")

@app.route('/get_livreur_stats/<livreur_id>')
def get_livreur_stats(livreur_id):
    """Récupère les statistiques d'un livreur"""
    try:
        stats = stats_col.find_one({"_id": livreur_id})
        if not stats:
            return jsonify({
                'status': 'success',
                'stats': {
                    'avg_rating': 5.0,
                    'delivery_count': 0,
                    'total_rating': 0
                }
            })
        
        return jsonify({
            'status': 'success',
            'stats': {
                'avg_rating': float(stats.get('avg_rating', 5.0)),
                'delivery_count': int(stats.get('delivery_count', 0)),
                'total_rating': float(stats.get('total_rating', 0))
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


def calculate_distance(lon1, lat1, lon2, lat2):
    """Calcule la distance en km entre deux points GPS"""
    try:
        from math import radians, sin, cos, sqrt, atan2
        
        lon1, lat1, lon2, lat2 = map(radians, [float(lon1), float(lat1), float(lon2), float(lat2)])
        
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        radius_earth = 6371
        
        return round(radius_earth * c, 2)
    except Exception as e:
        print(f"Erreur calcul distance: {e}")
        return float('inf')

@app.route('/update_position', methods=['POST'])
def update_position():
    try:
        data = request.get_json()
        livreur_id = session.get('username')
        longitude = data.get('longitude')
        latitude = data.get('latitude')
        
        if not longitude or not latitude:
            return jsonify({'status': 'error', 'message': 'Coordonnées manquantes'}), 400
        
        position_doc = {
            "location": {
                "type": "Point",
                "coordinates": [float(longitude), float(latitude)]
            },
            "updated_at": datetime.now()
        }
        
        positions_col.update_one(
            {"_id": livreur_id},
            {"$set": position_doc},
            upsert=True
        )
        
        publish_event('position_updated', {
            'driver_id': livreur_id,
            'longitude': longitude,
            'latitude': latitude
        })
        
        return jsonify({'status': 'success', 'message': 'Position mise à jour'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/get_my_position')
def get_my_position():
    try:
        livreur_id = session.get('username')
        position_doc = positions_col.find_one({"_id": livreur_id})
        
        if position_doc and 'location' in position_doc:
            pos_data = {
                "longitude": position_doc['location']['coordinates'][0],
                "latitude": position_doc['location']['coordinates'][1],
                "updated_at": position_doc.get('updated_at').isoformat() if position_doc.get('updated_at') else None
            }
            return jsonify({
                'status': 'success',
                'position': pos_data
            })
        else:
            return jsonify({
                'status': 'success',
                'position': None
            })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.context_processor
def utility_processor():
    def has_candidates(order_id):
        order = orders_col.find_one({"_id": order_id}, {"candidates": 1})
        return (order and order.get("candidates"))
    
    def get_candidates_count(order_id):
        order = orders_col.find_one({"_id": order_id}, {"candidates": 1})
        return len(order.get("candidates", [])) if order else 0
    
    def get_timer_data(order_id):
        order = orders_col.find_one({"_id": order_id}, {"timer": 1})
        # Rendre sérialisable pour Jinja
        return json.loads(json_util.dumps(order.get("timer"))) if order and order.get("timer") else {}
    
    return {
        'has_candidates': has_candidates,
        'get_candidates_count': get_candidates_count,
        'get_timer_data': get_timer_data
    }

if __name__ == '__main__':
    init_test_users()
    print("🚀 Démarrage du serveur Flask sur http://127.0.0.1:5000")
    app.run(debug=True, port=5000, threaded=True)

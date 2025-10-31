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

app = Flask(__name__)
app.secret_key = 'votre_cle_secrete'

# --- Connexion MongoDB ---
try:
    client = MongoClient('mongodb+srv://rafiibettaieb004:3gFC65o82k4DppKb@cluster0.1drqg.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
    db = client['delivery_db'] # Nom de la base de données

    # Définition des collections
    users_col = db['users']
    orders_col = db['orders']
    stats_col = db['livreur_stats']
    positions_col = db['livreurs_positions']
    
    # Collection pour le "Pub/Sub" via Change Streams
    # On la crée en "capped" (taille fixe), idéal pour les logs/événements
    if 'events' not in db.list_collection_names():
        db.create_collection("events", capped=True, size=10 * 1024 * 1024) # 10MB
    events_col = db['events']
    
    print("✅ Connexion à MongoDB réussie.")

except Exception as e:
    print(f"❌ Erreur de connexion à MongoDB: {e}")
    print("Veuillez vous assurer que MongoDB est en cours d'exécution sur localhost:27017")
    exit()
# -------------------------


def init_test_users():
    password_hash = hashlib.sha256("123456".encode()).hexdigest()
    
    test_users = {
        "client1": {"password": password_hash, "role": "client"},
        "client2": {"password": password_hash, "role": "client"},
        "manager1": {"password": password_hash, "role": "manager"},
        "restaurant1": {"password": password_hash, "role": "restaurant"},
        "livreur1": {"password": password_hash, "role": "livreur"},
        "livreur2": {"password": password_hash, "role": "livreur"},
        "livreur3": {"password": password_hash, "role": "livreur"},
    }
    
    print("Initialisation des utilisateurs...")
    for username, user_data in test_users.items():
        try:
            # On utilise _id comme nom d'utilisateur pour garantir l'unicité
            users_col.insert_one({
                "_id": username,
                "password": user_data['password'],
                "role": user_data['role']
            })
        except DuplicateKeyError:
            pass # L'utilisateur existe déjà
            
    # Initialiser les scores des livreurs (dans la collection stats)
    livreur_scores = {
        "livreur1": 4.8,
        "livreur2": 4.3,
        "livreur3": 4.6
    }
    for livreur, score in livreur_scores.items():
        stats_col.update_one(
            {"_id": livreur},
            {"$setOnInsert": {
                "_id": livreur,
                "avg_rating": score,
                "delivery_count": 0, # On suppose 0 pour l'init
                "total_rating": 0
            }},
            upsert=True
        )
        
    # --- Création des index MongoDB ---
    print("Création des index MongoDB...")
    users_col.create_index("role")
    orders_col.create_index("client")
    orders_col.create_index("status")
    orders_col.create_index("assigned_driver")
    orders_col.create_index([("candidates", ASCENDING)]) # Pour trouver les intérêts
    stats_col.create_index([("avg_rating", DESCENDING)]) # Pour trier
    # Index géospatial pour les positions des livreurs
    positions_col.create_index([("location", GEOSPHERE)])
    print("Index créés.")


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
    # Convertit le curseur en liste
    return list(orders_col.find())

def get_assigned_orders_for_livreur(livreur_id):
    return list(orders_col.find({
        "assigned_driver": livreur_id,
        "status": "assigned"
    }))

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        # On cherche l'utilisateur par son _id
        user_data = users_col.find_one({"_id": username})
        
        if user_data:
            stored_hash = user_data['password']
            stored_role = user_data['role']
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            
            if password_hash == stored_hash and role == stored_role:
                session['username'] = username
                session['role'] = role
                flash('Connexion réussie!', 'success')
                return redirect(url_for('dashboard'))
        
        flash('Identifiants incorrects', 'error')
    
    return render_template('login.html')

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
        orders = get_restaurant_orders()
        return render_template('restaurant_simple.html', username=username, orders=orders)
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

@app.route('/passer_commande', methods=['POST'])
def passer_commande():
    try:
        id_commande = str(uuid.uuid4())[:8]
        details_commande = {
            "_id": id_commande, # On utilise _id pour la clé primaire
            "id": id_commande, # Gardé pour la compatibilité d'affichage
            "client": session.get('username'),
            "restaurant": "La Bonne Fourchette",
            "articles": "1x Pizza, 1x Boisson",
            "status": "pending",
            "restaurant_lon": "2.333", # Ajout des coordonnées pour le POC
            "restaurant_lat": "48.865"
        }
        
        orders_col.insert_one(details_commande)
        publish_event('order_created', {'order_id': id_commande, 'details': details_commande})
        return {'status': 'success', 'order_id': id_commande}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/marquer_prete/<order_id>', methods=['POST'])
def marquer_prete(order_id):
    try:
        # Marquer la commande comme prête
        orders_col.update_one({"_id": order_id}, {"$set": {"status": "ready"}})
        
        # Démarrer la fenêtre de 60s pour les livreurs
        start_acceptance_window(order_id)
        
        print(f"✅ Fenêtre d'acceptation ouverte pour {order_id}")
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

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
    # Cette logique de "scheduler" reste en Python (hors DB) comme dans l'original
    schedule_manager_decision(order_id, 60)
    
    publish_event('order_ready', {
        'order_id': order_id,
        'expires_at': expiration_time.isoformat()
    })

def schedule_manager_decision(order_id, delay_seconds):
    """Programme la décision du manager après un délai"""
    def start_manager_decision():
        time.sleep(delay_seconds)
        
        # Vérifier si la commande existe toujours et n'est pas déjà assignée
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data or order_data.get('status') != 'ready':
            return
            
        # Les candidats sont maintenant un array dans la commande
        candidates = order_data.get('candidates', [])
        
        if candidates:
            # Démarrer la fenêtre de décision du manager (60s)
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
            
            # Programmer l'attribution automatique
            schedule_auto_assignment(order_id, 60)
        else:
            # S'il n'y a pas de candidats, on efface le timer
            orders_col.update_one({"_id": order_id}, {"$unset": {"timer": ""}})
            publish_event('no_candidates', {'order_id': order_id})
            print(f"❌ Aucun candidat pour {order_id}")
    
    thread = threading.Thread(target=start_manager_decision, daemon=True)
    thread.start()

def schedule_auto_assignment(order_id, delay_seconds):
    """Programme l'attribution automatique après un délai"""
    def auto_assign():
        time.sleep(delay_seconds)
        
        # Vérifier si la commande existe toujours et n'est pas déjà assignée
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data or order_data.get('status') != 'ready':
            return
            
        candidates = order_data.get('candidates', [])
        
        if candidates:
            # Récupérer les coordonnées du restaurant
            resto_lon = order_data.get('restaurant_lon', '2.333')
            resto_lat = order_data.get('restaurant_lat', '48.865')
            
            # Calculer le meilleur livreur basé sur score et distance
            best_livreur = None
            best_score = -1
            
            for candidate in candidates:
                driver_score = get_livreur_score(candidate)
                
                # Récupérer la position depuis la collection 'positions'
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
                # Assigner la commande et effacer timer/candidats
                orders_col.update_one(
                    {"_id": order_id},
                    {
                        "$set": {"status": "assigned", "assigned_driver": best_livreur},
                        "$unset": {"candidates": "", "timer": ""}
                    }
                )
                
                # Récupérer les infos pour le log
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
        
        # Vérifier si la fenêtre d'acceptation est encore ouverte
        order_data = orders_col.find_one({"_id": order_id}, {"timer": 1})
        timer_data = order_data.get('timer')
        
        if not timer_data or timer_data.get('type') != 'acceptance_window':
            return {'status': 'error', 'message': 'Fenêtre d\'acceptation fermée'}
        
        # Ajouter le livreur à l'array des candidats (uniquement s'il n'y est pas)
        orders_col.update_one(
            {"_id": order_id},
            {"$addToSet": {"candidates": livreur}} # $addToSet évite les doublons
        )
        
        publish_event('driver_interest', {
            'order_id': order_id,
            'driver_id': livreur,
            'driver_score': get_livreur_score(livreur)
        })
        
        print(f"✅ {livreur} a montré son intérêt pour {order_id}")
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/choisir_livreur/<order_id>/<livreur>', methods=['POST'])
def choisir_livreur(order_id, livreur):
    try:
        # Assigner la commande et effacer timer/candidats
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
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

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
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/get_order_candidates/<order_id>')
def get_order_candidates(order_id):
    """Récupère les candidats pour une commande spécifique"""
    try:
        order_data = orders_col.find_one({"_id": order_id}, {"candidates": 1, "status": 1})
        if not order_data:
            return {'status': 'error', 'message': 'Commande non trouvée'}

        candidates = order_data.get('candidates', [])
        candidates_with_scores = []
        
        for candidate in candidates:
            score = get_livreur_score(candidate)
            candidates_with_scores.append({
                'id': candidate,
                'score': score
            })
        
        # Trier par score décroissant
        candidates_with_scores.sort(key=lambda x: x['score'], reverse=True)
        
        return {
            'status': 'success', 
            'candidates': candidates_with_scores,
            'order_status': order_data.get('status')
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/get_timer_status/<order_id>')
def get_timer_status(order_id):
    """Récupère le statut et le temps restant d'un timer"""
    try:
        order_data = orders_col.find_one({"_id": order_id}, {"timer": 1})
        timer_data = order_data.get('timer')

        if not timer_data:
            return {'status': 'expired'}
        
        # Calculer le temps restant
        expires_at = datetime.fromisoformat(timer_data['expires_at'])
        time_left = max(0, (expires_at - datetime.now()).total_seconds())
        
        if time_left == 0:
            return {'status': 'expired'}

        return {
            'status': 'active',
            'time_left': int(time_left),
            'type': timer_data.get('type', 'unknown')
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/events')
def events():
    """Endpoint Server-Sent Events (SSE) utilisant les Change Streams MongoDB"""
    def generate():
        # Pipeline pour n'écouter que les NOUVEAUX événements (opérations 'insert')
        pipeline = [{'$match': {'operationType': 'insert'}}]
        
        # Utiliser 'with' pour gérer correctement la fermeture du stream
        try:
            with events_col.watch(pipeline, full_document='updateLookup') as stream:
                yield "data: {}\n\n".format(json.dumps({'type': 'connected'}))
                
                for change in stream:
                    # 'fullDocument' contient le document qui vient d'être inséré
                    event_doc = change['fullDocument']
                    
                    # On retire le _id de MongoDB avant d'envoyer
                    event_doc.pop('_id', None) 
                    
                    # Utiliser json_util.dumps pour gérer les types BSON comme datetime
                    yield "data: {}\n\n".format(json_util.dumps(event_doc))
        except Exception as e:
            print(f"Erreur SSE/Change Stream: {e}")
            yield "data: {}\n\n".format(json.dumps({'type': 'error', 'message': str(e)}))

    return Response(generate(), mimetype='text/event-stream')

@app.route('/debug_timers')
def debug_timers():
    """Page de debug pour voir l'état des timers"""
    timers_info = []
    # On cherche toutes les commandes qui ont un champ 'timer'
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
    
    return jsonify(timers_info)

@app.route('/force_auto_assign/<order_id>', methods=['POST'])
def force_auto_assign(order_id):
    """Forcer l'attribution automatique (pour tests) en utilisant le score et la distance"""
    try:
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return {'status': 'error', 'message': 'Commande non trouvée'}

        candidates = order_data.get('candidates', [])
        if not candidates:
            return {'status': 'error', 'message': 'Aucun candidat'}

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

            return {'status': 'success', 
                    'assigned_to': best_livreur,
                    'score': final_driver_score,
                    'combined_score': best_combined_score
                   }
        else:
            return {'status': 'error', 'message': 'Aucun livreur valide'}
            
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    
@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnexion réussie', 'info')
    return redirect(url_for('login'))

def get_client_orders(username):
    return list(orders_col.find({"client": username}))

def get_restaurant_orders():
    return list(orders_col.find({"status": {"$in": ["pending", "ready"]}}))

def get_available_orders():
    # Commandes prêtes et avec fenêtre d'acceptation active
    return list(orders_col.find({
        "status": "ready",
        "timer.type": "acceptance_window"
    }))

def get_my_interests(username):
    # Trouve les commandes où l'utilisateur est dans l'array 'candidates'
    return list(orders_col.find({"candidates": username}))

@app.route('/annuler_commande/<order_id>', methods=['POST'])
def annuler_commande(order_id):
    try:
        username = session.get('username')
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return {'status': 'error', 'message': 'Commande non trouvée'}
        
        if order_data.get('client') != username:
            return {'status': 'error', 'message': 'Vous ne pouvez pas annuler cette commande'}
        
        if order_data.get('status') == 'assigned':
            return {'status': 'error', 'message': 'Impossible d\'annuler: un livreur a déjà été assigné'}
        
        # Annuler la commande et effacer timer/candidats
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
        return {'status': 'success'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@app.route('/noter_livreur/<order_id>', methods=['POST'])
def noter_livreur(order_id):
    try:
        data = request.get_json()
        note = data.get('note')
        username = session.get('username')
        
        if note is None or not (1 <= note <= 5):
            return {'status': 'error', 'message': 'Note invalide. Doit être entre 1 et 5'}
        
        order_data = orders_col.find_one({"_id": order_id})
        if not order_data:
            return {'status': 'error', 'message': 'Commande non trouvée'}
        
        if order_data.get('client') != username:
            return {'status': 'error', 'message': 'Vous ne pouvez noter que vos propres commandes'}
        
        if order_data.get('status') != 'delivered':
            return {'status': 'error', 'message': 'Vous ne pouvez noter que les commandes livrées'}
        
        # Vérifier que la commande n'a pas déjà été notée
        if order_data.get("client_rating") is not None:
            return {'status': 'error', 'message': 'Cette commande a déjà été notée'}
        
        livreur_id = order_data.get('assigned_driver')
        if not livreur_id:
            return {'status': 'error', 'message': 'Aucun livreur assigné à cette commande'}
        
        # Enregistrer la note dans la commande
        orders_col.update_one(
            {"_id": order_id},
            {"$set": {
                "client_rating": note,
                "rated_at": datetime.now()
            }}
        )
        
        # Mettre à jour la note moyenne du livreur
        update_livreur_score(livreur_id, float(note))
        
        publish_event('driver_rated', {
            'order_id': order_id,
            'driver_id': livreur_id,
            'rating': note,
            'client': username
        })
        
        print(f"⭐ Livreur {livreur_id} noté {note}/5 pour la commande {order_id}")
        return {'status': 'success', 'message': f'Merci! Vous avez noté {livreur_id} avec {note} étoiles'}
        
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

def update_livreur_score(livreur_id, new_rating):
    """Met à jour la note moyenne d'un livreur dans la collection 'stats'"""
    try:
        # On utilise $inc pour des mises à jour atomiques
        stats_col.update_one(
            {"_id": livreur_id},
            {
                "$inc": {
                    "total_rating": new_rating,
                    "delivery_count": 1
                }
            },
            upsert=True # Crée le document si c'est le premier rating
        )
        
        # Recalculer la moyenne
        stats = stats_col.find_one({"_id": livreur_id})
        total_rating = stats.get("total_rating", 0)
        delivery_count = stats.get("delivery_count", 1) # Évite division par zéro
        
        avg_rating = round(total_rating / delivery_count, 2)
        
        # Mettre à jour la moyenne
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
            return {
                'status': 'success',
                'stats': {
                    'avg_rating': 5.0,
                    'delivery_count': 0,
                    'total_rating': 0
                }
            }
        
        return {
            'status': 'success',
            'stats': {
                'avg_rating': float(stats.get('avg_rating', 5.0)),
                'delivery_count': int(stats.get('delivery_count', 0)),
                'total_rating': float(stats.get('total_rating', 0))
            }
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# Ajouter cette fonction pour calculer la distance
def calculate_distance(lon1, lat1, lon2, lat2):
    """Calcule la distance en km entre deux points GPS"""
    try:
        from math import radians, sin, cos, sqrt, atan2
        
        # Convertir les degrés en radians
        lon1, lat1, lon2, lat2 = map(radians, [float(lon1), float(lat1), float(lon2), float(lat2)])
        
        # Formule de Haversine
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        radius_earth = 6371  # Rayon de la Terre en km
        
        return round(radius_earth * c, 2)
    except Exception as e:
        print(f"Erreur calcul distance: {e}")
        return float('inf')

# Ajouter cette route pour mettre à jour la position du livreur
@app.route('/update_position', methods=['POST'])
def update_position():
    try:
        data = request.get_json()
        livreur_id = session.get('username')
        longitude = data.get('longitude')
        latitude = data.get('latitude')
        
        if not longitude or not latitude:
            return {'status': 'error', 'message': 'Coordonnées manquantes'}
        
        # Stocker la position du livreur au format GeoJSON
        position_doc = {
            "location": {
                "type": "Point",
                "coordinates": [float(longitude), float(latitude)]
            },
            "updated_at": datetime.now().isoformat()
        }
        
        # Mettre à jour ou insérer (upsert) la position
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
        
        return {'status': 'success', 'message': 'Position mise à jour'}
        
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# Modifier la fonction d'attribution automatique pour utiliser la distance
# NOTE: Cette fonction est déjà mise à jour plus haut (schedule_auto_assignment)


@app.route('/get_my_position')
def get_my_position():
    try:
        livreur_id = session.get('username')
        position_doc = positions_col.find_one({"_id": livreur_id})
        
        if position_doc and 'location' in position_doc:
            # Re-formater pour correspondre à l'ancienne structure HASH
            pos_data = {
                "longitude": position_doc['location']['coordinates'][0],
                "latitude": position_doc['location']['coordinates'][1],
                "updated_at": position_doc.get('updated_at')
            }
            return {
                'status': 'success',
                'position': pos_data
            }
        else:
            return {
                'status': 'success',
                'position': None
            }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


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
        return order.get("timer") if order else {}
    
    return {
        'has_candidates': has_candidates,
        'get_candidates_count': get_candidates_count,
        'get_timer_data': get_timer_data
    }

if __name__ == '__main__':
    # 'with app.app_context()' n'est pas nécessaire pour PyMongo
    init_test_users()
    print("🚀 Démarrage du serveur Flask sur http://127.0.0.1:5000")
    app.run(debug=True, port=5000, threaded=True)
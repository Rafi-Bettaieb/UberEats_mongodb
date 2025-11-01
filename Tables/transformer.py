import json
import csv

def lire_fichier_csv(nom_fichier):
    """Lit un fichier CSV et retourne une liste de dictionnaires"""
    try:
        with open(nom_fichier, 'r', encoding='utf-8') as fichier:
            lecteur = csv.DictReader(fichier)
            return list(lecteur)
    except FileNotFoundError:
        print(f"Erreur: Le fichier {nom_fichier} n'a pas été trouvé.")
        return []
    except Exception as e:
        print(f"Erreur lors de la lecture du fichier {nom_fichier}: {e}")
        return []

def denormaliser_donnees():
    # Lire tous les fichiers
    utilisateurs = lire_fichier_csv("utilisateurs.txt")
    restaurants = lire_fichier_csv("restaurants.txt")
    menu_articles = lire_fichier_csv("menu_articles.txt")
    livreurs = lire_fichier_csv("livreurs.txt")
    
    # Vérifier que tous les fichiers ont été lus correctement
    if not all([utilisateurs, restaurants, menu_articles, livreurs]):
        print("Erreur: Impossible de lire tous les fichiers nécessaires.")
        return None
    
    # Créer un dictionnaire pour stocker les données dénormalisées
    donnees_denormalisees = {
        "utilisateurs": [],
        "restaurants": [],
        "livreurs": []
    }
    
    # Traiter les utilisateurs
    for utilisateur in utilisateurs:
        donnees_utilisateur = {
            "username": utilisateur["username"],
            "password_hash": utilisateur["password_hash"],
            "role": utilisateur["role"]
        }
        
        # Ajouter les données spécifiques selon le rôle
        if utilisateur["role"] == "restaurant":
            # Trouver le restaurant correspondant
            info_restaurant = next((r for r in restaurants if r["utilisateur_username"] == utilisateur["username"]), None)
            if info_restaurant:
                donnees_utilisateur["restaurant"] = {
                    "nom": info_restaurant["nom"],
                    "longitude": float(info_restaurant["longitude"]),
                    "latitude": float(info_restaurant["latitude"]),
                    "menu": []
                }
                
                # Ajouter les articles du menu
                articles_menu = [article for article in menu_articles if article["restaurant_nom"] == info_restaurant["nom"]]
                for article in articles_menu:
                    donnees_utilisateur["restaurant"]["menu"].append({
                        "nom_article": article["nom_article"],
                        "prix": float(article["prix"])
                    })
        
        elif utilisateur["role"] == "livreur":
            # Trouver les informations du livreur
            info_livreur = next((l for l in livreurs if l["utilisateur_username"] == utilisateur["username"]), None)
            if info_livreur:
                donnees_utilisateur["livreur"] = {
                    "avg_rating": float(info_livreur["avg_rating"])
                }
        
        # Classer par rôle dans la structure finale
        if utilisateur["role"] == "restaurant":
            donnees_denormalisees["restaurants"].append(donnees_utilisateur)
        elif utilisateur["role"] == "livreur":
            donnees_denormalisees["livreurs"].append(donnees_utilisateur)
        else:
            donnees_denormalisees["utilisateurs"].append(donnees_utilisateur)
    
    return donnees_denormalisees

def main():
    print("Début de la dénormalisation des données...")
    
    # Dénormaliser les données
    donnees_denormalisees = denormaliser_donnees()
    
    if donnees_denormalisees is None:
        print("Échec de la dénormalisation.")
        return
    
    # Convertir en JSON
    json_output = json.dumps(donnees_denormalisees, indent=2, ensure_ascii=False)
    
    # Afficher le résultat
    print("Données dénormalisées :")
    print(json_output)
    
    # Sauvegarder dans un fichier JSON
    with open("donnees_denormalisees.json", "w", encoding="utf-8") as f:
        f.write(json_output)
    
    print("\nDonnées sauvegardées dans 'donnees_denormalisees.json'")
    
    # Afficher quelques statistiques
    print(f"\nStatistiques :")
    print(f"- Utilisateurs: {len(donnees_denormalisees['utilisateurs'])}")
    print(f"- Restaurants: {len(donnees_denormalisees['restaurants'])}")
    print(f"- Livreurs: {len(donnees_denormalisees['livreurs'])}")

if __name__ == "__main__":
    main()

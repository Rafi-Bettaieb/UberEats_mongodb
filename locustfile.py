from locust import HttpUser, task, between

class MongoAppUser(HttpUser):
    wait_time = between(1, 2)

    def on_start(self):
        """Simulate login once per user session"""
        response = self.client.post("/login", data={
            "username": "client1",
            "password": "123456",   # <- Ce mot de passe correspond au hash dans le JSON
            "role": "client"
        }, allow_redirects=False)
        
        if response.status_code != 302:  # Flask redirige après une connexion réussie
            print("❌ Login failed:", response.status_code, response.text)
        else:
            print("✅ Logged in as client1")

    @task(2)
    def get_restaurants(self):
        self.client.get("/get_restaurants")

    @task(1)
    def passer_commande(self):
        payload = {
            "restaurant_id": "restaurant1",
            "items": [
                {"item": "Pizza", "quantity": 1, "price": 12.0},
                {"item": "Boisson", "quantity": 1, "price": 3.0}
            ]
        }
        self.client.post("/passer_commande", json=payload)

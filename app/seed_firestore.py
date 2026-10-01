import sys
import google.auth
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-42dbf6e50d0a"

SEED_RECIPES = [
    {
        "id": "recipe_1",
        "title": "Avocado Toast with Poached Egg",
        "category": "Breakfast",
        "ingredients": [
            "2 slices sourdough bread",
            "1 ripe avocado",
            "2 eggs",
            "1 tsp chili flakes",
            "Salt & pepper to taste",
        ],
        "prep_time_mins": 10,
        "calories": 350,
        "dietary_tags": ["vegetarian"],
    },
    {
        "id": "recipe_2",
        "title": "Quinoa & Roasted Veggie Buddha Bowl",
        "category": "Lunch",
        "ingredients": [
            "1 cup cooked quinoa",
            "1/2 cup roasted sweet potatoes",
            "1/2 cup chickpeas",
            "1/4 cup tahini dressing",
            "1 cup kale",
        ],
        "prep_time_mins": 25,
        "calories": 480,
        "dietary_tags": ["vegan", "gluten-free"],
    },
    {
        "id": "recipe_3",
        "title": "Grilled Salmon with Asparagus",
        "category": "Dinner",
        "ingredients": [
            "2 salmon fillets",
            "1 bunch asparagus",
            "2 tbsp olive oil",
            "1 lemon",
            "2 cloves garlic",
        ],
        "prep_time_mins": 20,
        "calories": 520,
        "dietary_tags": ["keto", "gluten-free", "high-protein"],
    },
]


def seed_database():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    creds, _ = google.auth.default()
    db = firestore.Client(project=PROJECT_ID, credentials=creds)
    collection_ref = db.collection("recipes")

    for recipe in SEED_RECIPES:
        doc_id = recipe["id"]
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(recipe)
        print(f"Seeded recipe: '{recipe['title']}' (ID: {doc_id})")

    print("Firestore database seeding completed successfully!")


if __name__ == "__main__":
    seed_database()

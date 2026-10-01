# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from typing import List, Optional
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors.agent_engine_sandbox_code_executor import (
    AgentEngineSandboxCodeExecutor,
)
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

PROJECT_ID = "qwiklabs-gcp-02-42dbf6e50d0a"
BUCKET_NAME = "smart-recipe-images-qwiklabs-gcp-02-42dbf6e50d0a"
MEMORY_BANK_ID = "4414158754497429504"


def _get_db():
    return firestore.Client(project=PROJECT_ID)


def _get_code_executor():
    metadata_path = os.path.join(
        os.path.dirname(__file__), "..", "deployment_metadata.json"
    )
    agent_engine_id = None
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
                agent_engine_id = data.get("remote_agent_runtime_id")
        except Exception:
            pass

    if not agent_engine_id:
        agent_engine_id = (
            "projects/399749367936/locations/us-east1/reasoningEngines/4414158754497429504"
        )

    return AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=agent_engine_id
    )


def memory_bank_service_builder():
    """Builds a VertexAiMemoryBankService instance targeting the deployed Agent Engine."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback triggered after each turn to extract and persist durable session facts and user allergies to Memory Bank."""
    await callback_context.add_session_to_memory()
    return None


def search_recipes(
    query: str = "", category: str = "", max_calories: int = 0
) -> str:
    """Searches recipes in the Firestore database by query term, category, or calorie limits.

    Args:
        query: Free text term to search in recipe title, ingredients, or dietary tags (e.g. 'salmon', 'vegan', 'avocado').
        category: Optional category filter (e.g. 'Breakfast', 'Lunch', 'Dinner').
        max_calories: Optional maximum calories threshold (e.g. 500).

    Returns:
        A list of matching recipes formatted as a string.
    """
    try:
        db = _get_db()
        collection_ref = db.collection("recipes")
        docs = collection_ref.stream()

        results = []
        q_lower = query.lower().strip() if query else ""
        cat_lower = category.lower().strip() if category else ""

        for doc in docs:
            data = doc.to_dict()
            if not data or "title" not in data:
                continue

            title = data.get("title", "")
            cat = data.get("category", "")
            calories = data.get("calories", 0)
            ingredients = data.get("ingredients", [])
            dietary_tags = data.get("dietary_tags", [])

            # Category filter
            if cat_lower and cat_lower not in cat.lower():
                continue

            # Calorie filter
            if max_calories > 0 and calories > max_calories:
                continue

            # Query filter (matches title, any ingredient, or dietary tags)
            if q_lower:
                match_title = q_lower in title.lower()
                match_ing = any(q_lower in ing.lower() for ing in ingredients)
                match_tag = any(q_lower in tag.lower() for tag in dietary_tags)
                if not (match_title or match_ing or match_tag):
                    continue

            results.append(data)

        if not results:
            return "No recipes found matching your search criteria."

        output = [f"Found {len(results)} recipe(s):"]
        for r in results:
            tags = ", ".join(r.get("dietary_tags", []))
            output.append(
                f"- [{r.get('id')}] {r.get('title')} ({r.get('category')}) - "
                f"{r.get('calories')} kcal, Prep: {r.get('prep_time_mins')} mins. Tags: [{tags}]"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error searching recipes: {str(e)}"


def get_recipe_details(recipe_id: str) -> str:
    """Retrieves full details for a specific recipe from the Firestore database.

    Args:
        recipe_id: The document ID of the recipe (e.g. 'recipe_1').

    Returns:
        Formatted string containing complete recipe information.
    """
    try:
        db = _get_db()
        doc_ref = db.collection("recipes").document(recipe_id)
        doc = doc_ref.get()

        if not doc.exists:
            return f"Recipe with ID '{recipe_id}' not found."

        data = doc.to_dict()
        ingredients_list = "\n  - ".join(data.get("ingredients", []))
        tags_list = ", ".join(data.get("dietary_tags", []))

        return (
            f"Title: {data.get('title')}\n"
            f"ID: {data.get('id')}\n"
            f"Category: {data.get('category')}\n"
            f"Prep Time: {data.get('prep_time_mins')} mins\n"
            f"Calories: {data.get('calories')} kcal\n"
            f"Dietary Tags: {tags_list}\n"
            f"Ingredients:\n  - {ingredients_list}"
        )
    except Exception as e:
        return f"Error getting recipe details: {str(e)}"


def save_recipe(
    title: str,
    category: str,
    ingredients: List[str],
    prep_time_mins: int,
    calories: int,
    dietary_tags: Optional[List[str]] = None,
) -> str:
    """Saves a new recipe to the Firestore database.

    Args:
        title: Title of the recipe (e.g. 'Berry Protein Smoothie').
        category: Category of meal (e.g. 'Breakfast', 'Snack', 'Dinner').
        ingredients: List of ingredient items with quantities.
        prep_time_mins: Preparation time in minutes.
        calories: Total calorie count per serving.
        dietary_tags: Optional list of dietary tags (e.g. ['high-protein', 'vegan']).

    Returns:
        A confirmation string containing the newly created recipe ID.
    """
    try:
        db = _get_db()
        recipe_id = f"recipe_{uuid.uuid4().hex[:8]}"
        recipe_data = {
            "id": recipe_id,
            "title": title,
            "category": category,
            "ingredients": ingredients,
            "prep_time_mins": prep_time_mins,
            "calories": calories,
            "dietary_tags": dietary_tags or [],
        }

        db.collection("recipes").document(recipe_id).set(recipe_data)
        return (
            f"Recipe '{title}' saved successfully with ID: {recipe_id}."
        )
    except Exception as e:
        return f"Error saving recipe: {str(e)}"


def scale_recipe_and_macros(
    recipe_id: str, target_servings: int, base_servings: int = 1
) -> str:
    """Scales a recipe's ingredient quantities and total calories for a target number of servings.

    Args:
        recipe_id: The document ID of the recipe (e.g. 'recipe_1').
        target_servings: The desired target number of servings (e.g. 4).
        base_servings: The original number of servings (default: 1).

    Returns:
        Formatted string with scaled ingredient amounts and total calories for target servings.
    """
    try:
        db = _get_db()
        doc = db.collection("recipes").document(recipe_id).get()

        if not doc.exists:
            return f"Recipe with ID '{recipe_id}' not found."

        data = doc.to_dict()
        factor = target_servings / max(1, base_servings)
        base_calories = data.get("calories", 0)
        scaled_calories = int(base_calories * factor)

        scaled_ingredients = []
        for ing in data.get("ingredients", []):
            parts = ing.split(" ", 1)
            try:
                if "/" in parts[0]:
                    num, denom = parts[0].split("/")
                    val = float(num) / float(denom)
                    scaled_val = round(val * factor, 2)
                    scaled_ingredients.append(f"{scaled_val} {parts[1]}")
                else:
                    val = float(parts[0])
                    scaled_val = round(val * factor, 2)
                    if scaled_val.is_integer():
                        scaled_val = int(scaled_val)
                    scaled_ingredients.append(f"{scaled_val} {parts[1]}")
            except (ValueError, IndexError):
                scaled_ingredients.append(f"{ing} (x{factor:.1f})")

        ing_list = "\n  - ".join(scaled_ingredients)
        return (
            f"Scaled Recipe: '{data.get('title')}'\n"
            f"Original Servings: {base_servings} -> Target Servings: {target_servings} (Scale Factor: {factor:.2f}x)\n"
            f"Scaled Calories: {scaled_calories} kcal (originally {base_calories} kcal)\n"
            f"Scaled Ingredients:\n  - {ing_list}"
        )
    except Exception as e:
        return f"Error scaling recipe: {str(e)}"


def fetch_online_recipe(dish_name: str) -> str:
    """Searches and fetches real recipe details from TheMealDB public REST API.

    Args:
        dish_name: Name of the dish or meal to search online (e.g. 'pasta', 'tacos', 'curry').

    Returns:
        Formatted string containing online recipe title, cuisine area, category, ingredients, and instructions.
    """
    try:
        api_key = os.getenv("MEALDB_API_KEY", "1")
        url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={urllib.parse.quote(dish_name)}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "SmartRecipeAssistant/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        meals = data.get("meals")
        if not meals:
            return f"No online recipes found for '{dish_name}'."

        meal = meals[0]
        title = meal.get("strMeal", "Unknown")
        category = meal.get("strCategory", "General")
        area = meal.get("strArea", "International")
        instructions = meal.get("strInstructions", "").strip()

        ingredients = []
        for i in range(1, 21):
            ing = meal.get(f"strIngredient{i}")
            measure = meal.get(f"strMeasure{i}")
            if ing and ing.strip():
                m_str = (
                    f" ({measure.strip()})"
                    if measure and measure.strip()
                    else ""
                )
                ingredients.append(f"{ing.strip()}{m_str}")

        ing_list = "\n  - ".join(ingredients)
        snippet = (
            (instructions[:250] + "...")
            if len(instructions) > 250
            else instructions
        )

        return (
            f"Online Recipe: '{title}' ({area} {category})\n"
            f"Ingredients:\n  - {ing_list}\n"
            f"Instructions Snippet:\n  {snippet}"
        )
    except Exception as e:
        return f"Error fetching online recipe for '{dish_name}': {str(e)}"


def geocode_address(address: str) -> str:
    """Uses Google Maps Geocoding API to convert an address string into geographic coordinates (latitude/longitude).

    Args:
        address: Street address, city, or location name (e.g. 'San Francisco, CA').

    Returns:
        Formatted string containing latitude, longitude, and full formatted address.
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            return "Error: GOOGLE_MAPS_API_KEY is not set in the environment."

        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "SmartRecipeAssistant/1.0"}
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        if data.get("status") != "OK" or not data.get("results"):
            return f"Geocoding failed for address '{address}': {data.get('status')}"

        result = data["results"][0]
        formatted_address = result.get("formatted_address", address)
        loc = result["geometry"]["location"]
        lat, lng = loc["lat"], loc["lng"]

        return (
            f"Geocoding Result for '{address}':\n"
            f"Formatted Address: {formatted_address}\n"
            f"Latitude: {lat}\n"
            f"Longitude: {lng}"
        )
    except Exception as e:
        return f"Error geocoding address '{address}': {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "grocery_store",
    radius_meters: int = 5000,
) -> str:
    """Uses Google Places API (New) REST endpoint to find nearby places of a given type around coordinates.

    Args:
        latitude: Target latitude coordinate (e.g. 37.7749).
        longitude: Target longitude coordinate (e.g. -122.4194).
        place_type: Type of place to search for (e.g. 'grocery_store', 'supermarket', 'restaurant').
        radius_meters: Search radius in meters (default: 5000).

    Returns:
        Formatted list of nearby places with key fields (name, address, location coordinates).
    """
    try:
        api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            return "Error: GOOGLE_MAPS_API_KEY is not set in the environment."

        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
        }
        body = json.dumps(
            {
                "includedTypes": [place_type],
                "maxResultCount": 5,
                "locationRestriction": {
                    "circle": {
                        "center": {
                            "latitude": float(latitude),
                            "longitude": float(longitude),
                        },
                        "radius": float(radius_meters),
                    }
                },
            }
        ).encode()

        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        places = data.get("places", [])
        if not places:
            return f"No nearby '{place_type}' places found within {radius_meters}m of ({latitude}, {longitude})."

        output = [f"Found {len(places)} nearby '{place_type}' place(s):"]
        for p in places:
            display_name = p.get("displayName", {}).get("text", "Unknown")
            addr = p.get("formattedAddress", "N/A")
            loc = p.get("location", {})
            lat_val = loc.get("latitude")
            lng_val = loc.get("longitude")

            output.append(
                f"- Name: {display_name}\n"
                f"  Address: {addr}\n"
                f"  Location: ({lat_val}, {lng_val})"
            )
        return "\n".join(output)
    except Exception as e:
        return f"Error finding nearby places: {str(e)}"


def generate_recipe_image(
    recipe_name: str, tool_context: ToolContext
) -> str:
    """Generates a presentation photo for a dish/recipe using gemini-3.1-flash-lite-image model, saves it as an artifact, and uploads to GCS.

    Args:
        recipe_name: Name or visual description of the recipe/dish to generate an image for (e.g. 'Avocado Toast with Poached Egg').
        tool_context: ADK ToolContext instance provided automatically by the agent framework.

    Returns:
        The public HTTPS URL of the generated image uploaded to Cloud Storage (https://storage.googleapis.com/<bucket>/<object>).
    """
    try:
        client = genai.Client(
            vertexai=True, project=PROJECT_ID, location="global"
        )
        prompt = (
            f"A mouth-watering, professional food photography photo of {recipe_name}, "
            f"beautiful plating, soft natural lighting, high resolution"
        )

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break

        if not image_bytes:
            return f"Failed to generate image for '{recipe_name}'."

        ext = "png" if "png" in mime_type else "jpg"
        filename = f"recipe_{uuid.uuid4().hex[:8]}.{ext}"

        # 1. Save artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(
            data=image_bytes, mime_type=mime_type
        )
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = (
            f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        )
        return public_url
    except Exception as e:
        return f"Error generating recipe image: {str(e)}"


def generate_recipe_video(
    recipe_name: str, tool_context: ToolContext
) -> str:
    """Generates a short video demonstration for a dish/recipe using Google's Omni model (gemini-omni-flash-preview) in the global region, saves it as an artifact, and uploads to GCS.

    Args:
        recipe_name: Name or visual description of the recipe/dish to generate a short video demonstration for (e.g. 'Avocado Toast' or 'Sizzling Steak').
        tool_context: ADK ToolContext instance provided automatically by the agent framework.

    Returns:
        The public HTTPS URL of the generated video uploaded to Cloud Storage (https://storage.googleapis.com/<bucket>/<object>).
    """
    try:
        client = genai.Client(
            vertexai=True, project=PROJECT_ID, location="global"
        )
        prompt = (
            f"A short, high-quality video showing {recipe_name}, "
            f"delicious food presentation, professional food videography"
        )

        res = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=[{"type": "text", "text": prompt}],
            response_format=[{
                "type": "video",
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "duration": "5s",
            }],
            generation_config={
                "video_config": {
                    "task": "text_to_video"
                }
            }
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(res, "steps") and res.steps:
            for step in res.steps:
                step_type = getattr(step, "type", None) or (step.get("type") if isinstance(step, dict) else None)
                if step_type == "model_output":
                    content = getattr(step, "content", None) or (step.get("content") if isinstance(step, dict) else [])
                    for item in content:
                        d_val = getattr(item, "data", None) or (item.get("data") if isinstance(item, dict) else None)
                        if d_val:
                            video_bytes = base64.b64decode(d_val) if isinstance(d_val, str) else d_val
                            m_val = getattr(item, "mime_type", None) or (item.get("mime_type") if isinstance(item, dict) else None)
                            if m_val:
                                mime_type = m_val
                            break
                        uri_val = getattr(item, "uri", None) or (item.get("uri") if isinstance(item, dict) else None)
                        if uri_val and uri_val.startswith("gs://"):
                            parts = uri_val[5:].split("/", 1)
                            b_name, o_name = parts[0], parts[1]
                            storage_client = storage.Client(project=PROJECT_ID)
                            video_bytes = storage_client.bucket(b_name).blob(o_name).download_as_bytes()
                            break

        if not video_bytes:
            return f"Failed to generate video for '{recipe_name}'."

        filename = f"recipe_video_{uuid.uuid4().hex[:8]}.mp4"

        # 1. Save artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(
            data=video_bytes, mime_type=mime_type
        )
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = (
            f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        )
        return public_url
    except Exception as e:
        return f"Error generating recipe video: {str(e)}"


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


# Build A2UI System Instruction via A2uiSchemaManager (version 0.8) and BasicCatalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are the Smart Recipe & Nutrition Assistant. You help users discover healthy recipes, "
        "search the local recipe collection by ingredient, category, or calorie limits, "
        "fetch real online recipes, geocode locations into coordinates, find nearby grocery stores or restaurants, "
        "generate presentation photos for recipes using AI, "
        "scale recipe ingredient quantities and nutritional macros for custom serving sizes, "
        "run Python code in a safe sandbox to perform precise mathematical, statistical, or nutritional calculations, "
        "and save new recipes to their personalized collection.\n\n"
        "IMPORTANT DIETARY & ALLERGY INSTRUCTIONS:\n"
        "- Actively remember all user food allergies, intolerances, and dietary restrictions across sessions (e.g. peanuts, tree nuts, gluten, dairy, shellfish, eggs, soy).\n"
        "- Whenever the user mentions a food allergy or dietary preference, ensure it is recorded in long-term Memory Bank.\n"
        "- Always check preloaded user memories before suggesting recipes, generating meals, or searching recipes. Automatically exclude or clearly flag any ingredients that conflict with remembered user allergies."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=_get_code_executor(),
    tools=[
        PreloadMemoryTool(),
        search_recipes,
        get_recipe_details,
        save_recipe,
        scale_recipe_and_macros,
        fetch_online_recipe,
        geocode_address,
        find_nearby_places,
        generate_recipe_image,
        generate_recipe_video,
        get_weather,
        get_current_time,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)

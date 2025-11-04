from flask import Blueprint, jsonify, request
from services.repository_service import RepositoryService
from services.image_processing_service import ImageProcessingService
#from services.reminder_service import ReminderService
#from services.disease_recognition_service import DiseaseRecognitionService

from utils.jwt_helper import validate_token

# Create a Flask Blueprint – a modular collection of routes
# This helps to keep your API organized
api_blueprint = Blueprint("api", __name__)
# Initialize all service classes
# Each service handles a specific domain logic (C4 style)
repo = RepositoryService()
image_service = ImageProcessingService()
#reminder_service = ReminderService()
#disease_service = DiseaseRecognitionService()


@api_blueprint.route("/check-auth", methods=["GET"])
def check_auth():
    token = request.headers.get("Authorization")
    if not token or not validate_token(token):
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True}), 200


@api_blueprint.route("/plants", methods=["GET"])
def get_plants():
    """
    Endpoint to fetch the list of plants stored in the database.
    - Calls RepositoryService.get_all_plants() to query the database
    - Returns the results as JSON so that the Flutter frontend can render them
    """
    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify({"error": "Missing user identifier"}), 400

    plants = repo.get_plants_by_user(user_id)
    return jsonify(plants)

@api_blueprint.route("/ping", methods=["GET"])
def ping():
    return jsonify(ping="pong")


@api_blueprint.route("/families", methods=["GET"])
def get_families():
    """
    Ritorna tutte le famiglie botaniche: [{id, name, plants_count}, ...]
    """
    families = repo.get_all_families()
    return jsonify(families), 200



@api_blueprint.route("/plants/all", methods=["GET"])
def get_all_plants():
    """
    GET /api/plants/all
    Ritorna l'intero catalogo piante (senza filtro utente).
    """
    try:
        plants = repo.get_all_plants_catalog()
        return jsonify(plants), 200
    except Exception:
        return jsonify({"error": "Database error"}), 500
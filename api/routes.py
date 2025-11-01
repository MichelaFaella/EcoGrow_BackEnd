from flask import Blueprint, jsonify, request
from services.repository_service import RepositoryService
from services.image_processing_service import ImageProcessingService
from services.reminder_service import ReminderService
from services.disease_recognition_service import DiseaseRecognitionService

# Create a Flask Blueprint – a modular collection of routes
# This helps to keep your API organized
api_blueprint = Blueprint("api", __name__)

# Initialize all service classes
# Each service handles a specific domain logic (C4 style)
repo = RepositoryService()
image_service = ImageProcessingService()
reminder_service = ReminderService()
disease_service = DiseaseRecognitionService()



# ROUTE: /check-auth
@api_blueprint.route("/check-auth", methods=["GET"])
def check_auth():
    """
        Endpoint to verify user authentication.
        Currently, this is just a placeholder returning `authenticated: true`.
        In a real-world scenario, this route should:
          - Read an Authorization header (e.g., JWT token)
          - Validate it to confirm if the user session is still active
        """
    return jsonify({"authenticated": False})


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
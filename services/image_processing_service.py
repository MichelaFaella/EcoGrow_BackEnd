from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image
import io

PLANT_NET_KEY = "2b10OOOA7FlnK64qRSChrFVO7"
FALLBACK_PLANT_NET_KEY = "2b10sxb5k5CkMBTK4clgmxySDe"
PLANT_NET_PATH = "https://my-api.plantnet.org/v2/identify/all"

DISEASE_MODEL_URL = os.getenv("DISEASE_MODEL_URL", "http://model:8000/predict")
DISEASE_MODEL_TIMEOUT = float(os.getenv("DISEASE_MODEL_TIMEOUT", "300"))


class ImageProcessingService:

    @staticmethod
    def _identify_plant(image_bytes: bytes, base_url: str, api_key: str) -> dict | None:
        print("[ImageProcessingService] _identify_plant → start")
        print(f"[ImageProcessingService] _identify_plant → URL: {base_url}")
        print(f"[ImageProcessingService] _identify_plant → Image bytes size: {len(image_bytes)}")

        url = f"{base_url}?api-key={api_key}"

        files = [
            ("images", ("image.jpg", image_bytes, "image/jpeg")),
        ]

        data = [("organs", "auto")]

        try:
            print("[ImageProcessingService] _identify_plant → sending POST to PlantNet…")
            resp = requests.post(url, files=files, data=data, timeout=30)
            print(f"[ImageProcessingService] _identify_plant → Response HTTP {resp.status_code}")
            if resp.status_code == 429:
                url = f"{base_url}?api-key={FALLBACK_PLANT_NET_KEY}"
                resp = requests.post(url, files=files, data=data, timeout=30)
                print(f"[ImageProcessingService] _identify_plant → Response HTTP {resp.status_code}")
            resp.raise_for_status()
        except Exception as e:
            print(f"[ImageProcessingService] _identify_plant → ERROR in POST: {e}")

            raise

        try:
            payload = resp.json()
            print("[ImageProcessingService] _identify_plant → JSON received")
        except Exception as e:
            print(f"[ImageProcessingService] _identify_plant → ERROR parsing JSON: {e}")
            raise

        # Log: visualizza best match se presente
        if "bestMatch" in payload:
            print(f"[ImageProcessingService] _identify_plant → bestMatch: {payload['bestMatch']}")

        results = payload.get("results") or []
        print(f"[ImageProcessingService] _identify_plant → results found: {len(results)}")

        if not results:
            print("[ImageProcessingService] _identify_plant → NO results → returning None")
            return None

        # ✓ best match by score
        best = max(results, key=lambda r: r.get("score") or 0)

        species = best.get("species") or {}
        family = species.get("family") or {}

        common_names = species.get("commonNames") or []

        result = {
            "scientific_name": species.get("scientificNameWithoutAuthor"),
            "scientific_name_full": species.get("scientificName"),
            "family_name": family.get("scientificNameWithoutAuthor"),
            "score": best.get("score"),
            "common_names": common_names,
        }

        print(f"[ImageProcessingService] _identify_plant → BEST MATCH object: {best}")
        print(f"[ImageProcessingService] _identify_plant → Parsed result: {result}")

        return result

    @staticmethod
    def process_image(file):
        print("[ImageProcessingService] process_image → start")

        try:
            img = Image.open(file.stream)
            print("[ImageProcessingService] process_image → image loaded successfully")
        except Exception as e:
            print(f"[ImageProcessingService] process_image → ERROR opening image: {e}")
            raise

        try:
            img.thumbnail((512, 512))
            print("[ImageProcessingService] process_image → image resized to 512px")
        except Exception as e:
            print(f"[ImageProcessingService] process_image → ERROR resizing image: {e}")
            raise

        try:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            print("[ImageProcessingService] process_image → image converted to JPEG")
        except Exception as e:
            print(f"[ImageProcessingService] process_image → ERROR converting to JPEG: {e}")
            raise

        try:
            print("[ImageProcessingService] process_image → calling _identify_plant …")
            info = ImageProcessingService._identify_plant(
                buffer.getvalue(),
                base_url=PLANT_NET_PATH,
                api_key=PLANT_NET_KEY,
            )
            print(f"[ImageProcessingService] process_image → result: {info}")
        except Exception as e:
            print(f"[ImageProcessingService] process_image → ERROR from _identify_plant: {e}")
            raise

        print("[ImageProcessingService] process_image → done")
        return info

    @staticmethod
    def _call_disease_model(
            image_bytes: bytes,
            unknown_threshold: float | None = None,
            family: str | None = None,
            disease_suggestions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Parla con il servizio esterno di disease recognition.
        """
        files = {
            "image": ("image.jpg", image_bytes, "image/jpeg"),
        }
        data: Dict[str, Any] = {}
        if unknown_threshold is not None:
            data["unknown_threshold"] = float(unknown_threshold)
        if family:
            data["family"] = family
        if disease_suggestions:
            data["disease_suggestions"] = disease_suggestions

        resp = requests.post(
            DISEASE_MODEL_URL,
            files=files,
            data=data,
            timeout=DISEASE_MODEL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _extract_top_disease(result: Dict[str, Any]) -> Tuple[str, float]:
        """
        Prende il tuo JSON tipo:

        {
          "data": {
            "predictions": [ { "classes": [ { "label": "...", "probability": ...}, ... ] } ],
            "top_prediction": { "classes": [...], ... }
          },
          ...
        }

        e ritorna (label, probability) della classe con probabilità più alta.
        """
        data = result.get("data") or {}
        top = data.get("top_prediction")
        if top and "classes" in top:
            classes = top["classes"]
        else:
            predictions = data.get("predictions") or []
            if not predictions:
                raise ValueError("No predictions in AI result")
            classes = predictions[0].get("classes") or []

        if not classes:
            raise ValueError("Empty classes in AI result")

        best = max(classes, key=lambda c: c.get("probability", 0.0) or 0.0)
        return best["label"], float(best["probability"])

    @staticmethod
    def disease_detection_raw(
            image_file,
            unknown_threshold: float | None = None,
            family: str | None = None,
            disease_suggestions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Converte l'immagine in JPEG (come per PlantNet), chiama il modello
        di disease recognition e restituisce il JSON completo del modello.
        """
        # 1) leggo i bytes dall'upload Flask
        image_bytes = image_file.read()

        # 2) normalizzo in JPEG
        img = Image.open(io.BytesIO(image_bytes))
        buffer = io.BytesIO()
        img = img.convert("RGB")
        img.save(buffer, format="JPEG", quality=90, optimize=True)
        buffer.seek(0)

        # 3) chiamata al modello
        return ImageProcessingService._call_disease_model(
            buffer.getvalue(),
            unknown_threshold=unknown_threshold,
            family=family,
            disease_suggestions=disease_suggestions,
        )

    @staticmethod
    def disease_detection_top_class(
            image_file,
            unknown_threshold: float | None = None,
            family: str | None = None,
            disease_suggestions: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], str, float]:
        """
        Come disease_detection_raw, ma in più estrae la top prediction.
        Ritorna: (json_modello, label_top, prob_top)
        """
        result = ImageProcessingService.disease_detection_raw(
            image_file=image_file,
            unknown_threshold=unknown_threshold,
            family=family,
            disease_suggestions=disease_suggestions,
        )
        label, prob = ImageProcessingService._extract_top_disease(result)
        return result, label, prob

from __future__ import annotations

import requests
from PIL import Image
import io

PLANT_NET_KEY = "2b10OOOA7FlnK64qRSChrFVO7"
PLANT_NET_PATH = "https://my-api.plantnet.org/v2/identify/all"


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

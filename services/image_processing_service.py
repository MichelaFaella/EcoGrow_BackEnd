from __future__ import annotations

import requests
from PIL import Image
import io

PLANT_NET_KEY = "2b10OOOA7FlnK64qRSChrFVO7"
PLANT_NET_PATH = "https://my-api.plantnet.org/v2/identify/all"


class ImageProcessingService:
    @staticmethod
    def _identify_plant(image_bytes: bytes, base_url: str, api_key: str) -> str | None:
        """
        Manda l'immagine a PlantNet usando:
          base_url + "?api-key=" + api_key

        Ritorna:
          - scientificNameWithoutAuthor del best match
          - oppure None se non ci sono risultati
        """
        url = f"{base_url}?api-key={api_key}"

        files = [
            (
                "images",
                ("image.jpg", image_bytes, "image/jpeg"),
            )
        ]

        # come nel tuo esempio: organs = ["auto"]
        data = [
            ("organs", "auto"),
        ]

        resp = requests.post(url, files=files, data=data, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        results = payload.get("results") or []
        if not results:
            return None

        # Best match = risultato con score più alto
        best = max(results, key=lambda r: r.get("score") or 0)
        species = best.get("species") or {}

        return species.get("scientificNameWithoutAuthor")

    @staticmethod
    def process_image(file):
        """
        Riceve un file (es. request.files['file']),
        lo ridimensiona, lo converte in JPEG e lo manda a PlantNet.

        Ritorna:
          scientificNameWithoutAuthor del best match
        """
        img = Image.open(file.stream)
        img.thumbnail((512, 512))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        buffer.seek(0)

        scientific_name = ImageProcessingService._identify_plant(
            buffer.getvalue(),
            base_url=PLANT_NET_PATH,
            api_key=PLANT_NET_KEY,
        )

        # qui ritorniamo direttamente lo scientific name senza autore
        return scientific_name

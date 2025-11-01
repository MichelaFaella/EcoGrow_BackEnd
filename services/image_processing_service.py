from utils.plantnet_client import identify_plant
from PIL import Image
import io

class ImageProcessingService:
    def process_image(self, file):
        img = Image.open(file.stream)
        img.thumbnail((512, 512))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")

        plant_info = identify_plant(buffer.getvalue())
        return {"plant": plant_info}

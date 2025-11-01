import requests

def identify_plant(image_bytes):
    url = "https://my-api.plantnet.org/v2/identify/all"
    files = {"images": ("image.jpg", image_bytes, "image/jpeg")}
    data = {"api-key": "2b10OOOA7FlnK64qRSChrFVO7"}
    response = requests.post(url, files=files, data=data)
    return response.json()

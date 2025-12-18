from pathlib import Path
import cv2
import requests
from pyzbar.pyzbar import decode

def decode_qr_code(folder_path): # Probablemente útil, quizás optimizable
    data = []
    for image in Path(folder_path).glob("*"):
        name = image.name
        print(f"Procesando imagen: {name}...")
        matrix = cv2.imread(str(image)) # Imagen en BGR, NO RGB!
        decodedImage = None if matrix is None else decode(matrix)
        data.append((name, decodedImage))

    # Idea: Si no hay una solución accesible para QRs con blur, logos en medio, etc, 
    # se podría crear un autoencoder para reconstruir la imagen del QR antes de decodificarla.
    # Esto es caro, y quizás hasta innecesario, por ende de momento se deja como comentario.

    return data
    
def url_classifier(url): # Probablemente útil, sin más
    try:
        response = requests.get(url, timeout=10)
        content_type = response.headers.get('Content-Type', '')

        if 'text/html' in content_type:
            return "html"
        elif 'application/pdf' in content_type:
            return "pdf"
        elif 'image/' in content_type:
            return "img"
        else:
            return "unknown"
    except requests.RequestException as e:
        print("Error al acceder al enlace:", e)
        return "error"

if __name__ == "__main__":
    # En la práctica, debería requerir antes extracción del backend, puede requerir limitación de archivos, geenrando batches
    image_path = "/home/matty/CCU/P-Imágenes/Imágenes" # carpeta local
    qr_data = decode_qr_code(image_path) # Procesamiento del batch
    for name, data in qr_data:
        if data == []:
            print(f"{name}: NO LINK")
        else:
            url = data[0].data.decode("utf-8")
            urlType = url_classifier(url)
            # Toda esta data requiere un preprocesamiento para después poder ser utilizado
            print(f"{name}: {url}, Tipo: {urlType}")

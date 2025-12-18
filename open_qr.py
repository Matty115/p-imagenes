from pathlib import Path
import cv2
import requests
from pyzbar.pyzbar import decode
from bs4 import BeautifulSoup
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

def decode_qr_code(folder_path):
    data = []
    for image in Path(folder_path).glob("*"):
        name = image.name
        matrix = cv2.imread(str(image)) # Imagen en BGR, NO RGB!
        decodedImage = None if matrix is None else decode(matrix)
        
        # Si no se detectó, aplicar preprocesamiento
        if matrix is not None and decodedImage == []:
            # Técnica 1: Conversión a escala de grises
            gray = cv2.cvtColor(matrix, cv2.COLOR_BGR2GRAY)
            decodedImage = decode(gray)
            
            # Técnica 2: Umbralización adaptativa
            if decodedImage == []:
                thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                               cv2.THRESH_BINARY, 11, 2)
                decodedImage = decode(thresh)
            
            # Técnica 3: Aumentar contraste
            if decodedImage == []:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                enhanced = clahe.apply(gray)
                decodedImage = decode(enhanced)
            
            # Técnica 4: Umbralización simple (Otsu)
            if decodedImage == []:
                _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                decodedImage = decode(otsu)
            
            # Técnica 5: Aumentar tamaño de la imagen
            if decodedImage == []:
                resized = cv2.resize(matrix, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                decodedImage = decode(resized)
        
        data.append((name, decodedImage))

    return data

def htmlHandler(soup):
    # Ejemplo simple: extraer todos los enlaces en el HTML
    links = []
    for a in soup.find_all('a', href=True):
        links.append(a['href'])
    return links

def url_scraping(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extraer información útil del HTML
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            if 'berenguer' in url:
                print(response.text)
            #if 'text/html' in content_type:
            #    out = htmlHandler(soup)

            ## Potencialmente necesario para scraping
            #title = soup.find('title')
            #title_text = title.get_text().strip() if title else "Sin título"
            
            # agregar más extracción de datos con scraping?

            return content_type
        else:
            return f"status_{response.status_code}"
    except requests.RequestException as e:
        print("Error al acceder al enlace:", e)
        return "error"

if __name__ == "__main__":
    # En la práctica, debería requerir antes extracción del backend, 
    # puede requerir limitación de archivos, generando batches (es la gracia)
    image_path = "C:\\Users\\msandovalk\\Documents\\p-imagenes\\Imagenes" # carpeta local
    qr_data = decode_qr_code(image_path) # Procesamiento del batch
    for name, data in qr_data:
        if data == []:
            print(f"{name}: NO LINK")
        else:
            url = data[0].data.decode("utf-8")
            urlType = url_scraping(url) # La salida no será única si se añade exitosamente el scraping
            # Toda esta data requiere un preprocesamiento para después poder ser utilizado
            print(f"{name}: {url}, Tipo: {urlType}")

### NOTA: Para poder extraer contentido deseado, probablemente hay que hacer un esfuerzo mayor en los html.
### Esto porque a veces requieren simplemente revisar el html, otras veces clickear para desplegar contenido,
### inclusive redirecciones a chatbots.
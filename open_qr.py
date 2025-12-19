from pathlib import Path
import re
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

def classic_extraction(soup):
    PRICES_THRESHOLD = 10
    KEYWORD_THRESHOLD = 3

    for tag in soup(['script', 'style']):
        tag.decompose()

    text = soup.get_text(separator=' ', strip=True)

    price_pattern = r"([$€₲]|(CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?\s*(\d{1,3}([.,]\d{3})*[.,]\d{2,3}|\d{3,})\s*([$€₲]|(CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?"
    prices = list(re.finditer(price_pattern, text, flags=re.IGNORECASE))
    price_count = len(prices)

    keywords = ['corona', 'sol', 'heineken', 'stella artois'] # necesidad de listado oficial
    keyword_hits = sum(1 for kw in keywords if kw.lower() in text.lower())

    recognized = price_count >= PRICES_THRESHOLD or keyword_hits >= KEYWORD_THRESHOLD
    if not recognized:
        return {
        'recognized': False,
        'items': [],
        'stats': {
            'price_count': price_count,
            'keyword_hits': keyword_hits,
            'items_found': 0
        }
    }

    def item_info(element):
        item_class = element.get('class')
        text_el = element.get_text(separator=' ', strip=True)
        matches = re.findall(price_pattern, text_el)
        return item_class, text_el, matches

    items = []

    # Búsqueda en listas y tablas
    for el in soup.find_all(['li', 'tr', 'div']):
        text_block = el.get_text(separator=' ', strip=True)
        if 20 < len(text_block) < 500:
            continue
        match_count = sum(1 for _ in re.finditer(price_pattern, text_block, flags=re.IGNORECASE))
        if match_count >= 1:
            item_class, item_text, item_matches = item_info(el)
            if item_matches != []:
                items.append({'class': item_class, 'text': item_text, 'matches': item_matches})

    # Fallback: contexto de precios si no se encontraron items
    if not items:
        for match in prices:
            ctx_start = max(0, match.start() - 50)
            ctx_end = match.end() + 50
            context = text[ctx_start:ctx_end].strip()
            items.append({'class': f'Contexto entre {ctx_start}-{ctx_end}', 'text': context, 'matches': [match.group(0)]})

    return {
        'recognized': True,
        'items': items,
        'stats': {
            'price_count': price_count,
            'keyword_hits': keyword_hits,
            'items_found': len(items)
        }
    }

def html_handler(soup):
    # Ejemplo simple: extraer todos los enlaces en el HTML
    out = classic_extraction(soup)
    return out

def url_scraping(url):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extraer información útil del HTML
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            if 'text/html' in content_type:
                scrap = html_handler(soup)
                return {'content_type': content_type, 'scrap': scrap}

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
        if data == [] or name != "sample1.jpg": # luego volver
            #print(f"{name}: NO LINK")
            continue
        else:
            url = data[0].data.decode("utf-8")
            scrap = url_scraping(url) # La salida no será única si se añade exitosamente el scraping
            print(f"{name}: {url} -> {scrap}")

### NOTA: Para poder extraer contentido deseado, probablemente hay que hacer un esfuerzo mayor en los html.
### Esto porque a veces requieren simplemente revisar el html, otras veces clickear para desplegar contenido,
### inclusive redirecciones a chatbots.
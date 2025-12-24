from pathlib import Path
import re
import cv2
import requests
import time
import unicodedata

from pyzbar.pyzbar import decode
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, ElementNotInteractableException
from selenium.webdriver.common.by import By

from dotenv import load_dotenv
import os

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

def decode_qr_code(folder_path):
    '''
    Decodifica códigos QR en imágenes dentro de una carpeta, aplicando técnicas de preprocesamiento si la detección inicial falla.

    Parámetros:
    - folder_path (str): Ruta a la carpeta que contiene las imágenes.
    
    Retorna:
    - data (list): Lista de tuplas (nombre_imagen, datos_decodificados).
        - nombre_imagen (str): Nombre del archivo de imagen.
        - datos_decodificados (list): Lista de objetos decodificados por pyzbar, o lista vacía si no se detecta ningún código QR.
    '''

    data = []

    # Obtención y procesamiento de cada imagen en la carpeta
    for image in Path(folder_path).glob("*"):
        name = image.name
        matrix = cv2.imread(str(image)) # Obtención de imagen en BGR, NO RGB
        decodedImage = None if matrix is None else decode(matrix) # Intento inicial de decodificación
        
        # Si no se detectó, se aplican técnicas de preprocesamiento
        if matrix is not None and decodedImage == []:

            # Conversión a escala de grises
            gray = cv2.cvtColor(matrix, cv2.COLOR_BGR2GRAY)
            decodedImage = decode(gray)
            
            # Umbralización adaptativa
            if decodedImage == []:
                thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                               cv2.THRESH_BINARY, 11, 2)
                decodedImage = decode(thresh)
            
            # Aumento de contraste
            if decodedImage == []:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
                enhanced = clahe.apply(gray)
                decodedImage = decode(enhanced)
            
            # Umbralización simple (Otsu)
            if decodedImage == []:
                _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                decodedImage = decode(otsu)
            
            # Aumento de tamaño de la imagen
            if decodedImage == []:
                resized = cv2.resize(matrix, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                decodedImage = decode(resized)
        
        data.append((name, decodedImage)) # Almacenamiento de nombre y datos decodificados

    return data


def normalize_text(text):
    '''
    Normaliza el texto para facilitar la comparación y extracción.

    Parámetros:
    - text (str): Texto a normalizar.

    Retorna:
    - t (str): Texto normalizado.
    '''

    if not text:
        return ''
    
    t = text.strip() # Elimina espacios al inicio y final

    t = unicodedata.normalize('NFKD', t)
    t =''.join([c for c in t if not unicodedata.combining(c)]) # Quita tildes

    t = t.lower()
    t = t.replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"') # Comillas especiales
    t = re.sub(r'[\r\n\t]+', ' ', t) # Espacios en blanco especiales
    t = re.sub(r'[–—−]', '-', t) # Guiones especiales
    t = re.sub(r'\s+', ' ', t) # Múltiples espacios
    t = re.sub(r'[^\w\s\$\€\.,:-]', '', t) # Caracteres no alfanuméricos (excepto algunos signos)
    return t


def split_multi_item_block(text, matches):
    '''
    Divide un bloque de texto que contiene múltiples productos y precios en elementos individuales.

    Parámetros:
    - text (str): Bloque de texto a dividir.
    - matches (list): Lista de objetos match de regex que indican las posiciones de los precios en el texto.

    Retorna:
    - items (list): Lista de diccionarios con 'name', 'price' y 'text' extraídos para cada producto.
        - name (str): Nombre del producto.
        - price (str): Precio del producto.
        - text (str): Texto completo del segmento del producto.
    '''

    if not matches:
        return []

    items = []
    last_end = 0 # Variable para rastrear el final del último match
    
    for match in matches:
        chunk = text[last_end:match.end()].strip() # El producto es lo que está antes del precio (desde el fin del anterior)
        chunk = re.sub(r'^[:\s\.-]+', '', chunk) # Limpieza del inicio del chunk
        
        price_str = match.group(0) # Precio

        # Extracción y limpieza del nombre
        name_str = text[last_end:match.start()].strip()
        name_str = re.sub(r'^[:\s\.-]+', '', name_str)
        
        if len(name_str) > 2: # Evitamos anomalías
            items.append({
                'name': normalize_text(name_str),
                'price': price_str.strip(),
                'text': chunk
            })
        
        last_end = match.end() # Actualización del corte

    return items


def filter_redundant_items(items):
    '''
    Filtra elementos redundantes de una lista de productos.

    Parámetros:
    - items (list): Lista de diccionarios con 'name', 'price' y 'text' para cada producto.

    Retorna:
    - filtered (list): Lista de diccionarios con 'name', 'price' y 'text' sin elementos redundantes.
    '''

    if not items:
        return items
    
    # Eliminación de items con textos duplicados
    seen = {}
    for item in items:
        text = item['text']
        if text not in seen:
            seen[text] = item
    unique_items = list(seen.values())

    # Eliminación de items con subcadenas
    filtered = []
    for i, item1 in enumerate(unique_items):
        text1 = item1['text']
        is_redundant = False
        
        for j, item2 in enumerate(unique_items):
            if i != j:
                text2 = item2['text']
                if text1 in text2:
                    is_redundant = True
                    break
        
        if not is_redundant:
            filtered.append(item1)
    
    return filtered


def classic_extraction(soup): # En proceso de mejora
    '''
    Extracción directa de precios y nombres de productos desde HTML.

    Parámetros:
    - soup: BeautifulSoup object del HTML a procesar.
    Retorna:
    - diccionario con 'recognized' (bool) y 'items' (lista de diccionarios con 'name', 'price' y 'text').
        - name (str): Nombre del producto.
        - price (str): Precio del producto.
        - text (str): Texto completo del segmento del producto.
    '''

    # Parámetros de umbralización
    PRICES_THRESHOLD = 10
    KEYWORD_THRESHOLD = 1 
    MIN_LENGTH = 10
    MAX_LENGTH = 1000

    text = normalize_text(soup.get_text(strip=True))

    # Regex con non-capturing groups (?:...) para evitar tuplas de grupos
    price_pattern = r"(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?\s?(\d{1,3}([.,]\d{3}\s?)*[.,]\d{2,3}|(\d\s?){3,})\s*(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?"

    matches = list(re.finditer(price_pattern, text, flags=re.IGNORECASE))
    price_count = len(matches)
    keywords = ['sol', 'heineken', 'stella artois'] # necesidad de listado oficial
    keyword_hits = sum(1 for kw in keywords if kw.lower() in text.lower())

    recognized = price_count >= PRICES_THRESHOLD and keyword_hits >= KEYWORD_THRESHOLD
    if not recognized:
        return {
        'recognized': False,
        'items': []
    }

    processed_texts = set()
    items = []

    # Búsqueda en listas, tablas y divs
    for el in soup.find_all(['div', 'li', 'tr', 'p', 'td']):
        # Verificamos si el elemento tiene el patrón de precio dentro de su texto propio
        clean_block = normalize_text(el.get_text(strip=True, separator=' '))
        
        if not clean_block or len(clean_block) < 10:
            continue

        # Evitar procesar el mismo texto si ya lo capturamos en un hijo o padre
        if clean_block in processed_texts:
            continue

        block_matches = list(re.finditer(price_pattern, clean_block, flags=re.IGNORECASE))
        
        if block_matches:
            sub_items = split_multi_item_block(clean_block, block_matches)

            if sub_items:
                items.extend(sub_items)
                processed_texts.add(clean_block)

    items = filter_redundant_items(items)

    return {
        'recognized': True,
        'items': items
    }


def interactive_extraction(driver, max_time=60, history=[], depth=0): # En proceso de mejora
    '''
    Extracción interactiva de precios y nombres de productos desde una página web utilizando Selenium a partir de la interacción con elementos, como hacer clic en botones o enlaces para expandir contenido dinámico. De esta manera, para cada nuevo contenido cargado, se aplica extracción clásica recursivamente.

    Parámetros:
    - driver (WebDriver): Instancia de Selenium WebDriver.
    - max_time (int): Tiempo máximo en segundos para la extracción interactiva.
    - history (list): Lista de URLs ya visitadas para evitar ciclos.
    - depth (int): Nivel de profundidad de la recursión.

    Retorna:
    - diccionario con 'recognized' (bool) y 'items' (lista de diccionarios con 'name', 'price' y 'text').
        - name (str): Nombre del producto.
        - price (str): Precio del producto.
        - text (str): Texto completo del segmento del producto.
    '''

    BANNED_DOMAINS = [d.strip() for d in os.getenv("BANNED_DOMAINS", "").split(",") if d.strip()]
    url = driver.current_url
    out = {'recognized': False, 'items': []}

    if url in history or depth > 5 or url in BANNED_DOMAINS:
        return out
    
    history.append(url)
    actual = classic_extraction(BeautifulSoup(driver.page_source, 'html.parser'))
    start = time.time()

    step_size = 500
    current_position = 0
    total_height = driver.execute_script("return document.body.scrollHeight")
    while time.time() - start < max_time:
        current_position += step_size
        if current_position >= total_height:
            break
        # Scroll gradual hacia abajo
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height > total_height:
            total_height = new_height

        # Expandir acordeones/tabs
        for tag in ['button', 'a', 'span', 'li', 'td', 'div']:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:    
                            tag = el.tag_name.lower()
                            href = el.get_attribute('href')
                            onclick = el.get_attribute('onclick')
                            role = el.get_attribute('role')
                            class_attr = el.get_attribute('class') or ''
                            reference = href or onclick

                            is_interactive = (
                                (tag == 'a' and href) or
                                (tag == 'button') or
                                onclick or
                                (role and 'button' in role.lower()) or
                                ('button' in class_attr.lower() or 'accordion' in class_attr.lower())
                            )

                            if not is_interactive:
                                continue  # No hacer click

                            text = el.text.lower()

                            if any(keyword in text for keyword in ['whatsapp', 'facebook', 'instagram', 'twitter', 'tiktok', 'youtube', 'wix', 'acceder', 'iniciar sesión', 'registrarse', 'suscribirse', 'comprar', 'pagar', 'donar', 'descargar', 'contacto', 'contactanos', 'contacta', 'llamanos', 'llámanos', 'mensajería', 'messenger', 'linkedin', 'snapchat', 'google drive', 'play store']):
                                continue
                            cond = any([domain in reference for domain in BANNED_DOMAINS])
                            if reference is not None and (cond or reference in history):
                                continue
                            
                            old_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                            el.click()
                            WebDriverWait(driver, 10).until(
                                lambda d: d.find_element(By.TAG_NAME, "body").get_attribute("innerHTML") != old_html
                            )
                            new_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                            new_url = driver.current_url
                            if new_html != old_html :
                                soup = BeautifulSoup(new_html, 'html.parser')
                                new = html_handler(soup, driver, max_time - (time.time() - start), history, depth + 1)
                                actual['recognized'] = actual['recognized'] or new['recognized']
                                actual['items'].extend(new['items'])
                                actual['items'] = filter_redundant_items(actual['items'])
                            if reference:
                                history.append(reference)
                            if new_url != url:
                                history.append(new_url)
                                driver.back()
                                
                    except (ElementClickInterceptedException, ElementNotInteractableException):
                        continue
            except Exception:
                continue
    return actual


def html_handler(soup, driver, max_time=60, history=[], depth=0): # Incompleta
    '''
    Maneja el procesamiento de HTML para extraer información útil, combinando extracción clásica y extracción interactiva si es necesario.

    Parámetros:
    - soup: BeautifulSoup object del HTML a procesar.
    - driver (WebDriver): Instancia de Selenium WebDriver.
    - max_time (int): Tiempo máximo en segundos para la extracción interactiva.
    - history (list): Lista de URLs ya visitadas para evitar ciclos.
    - depth (int): Profundidad actual de la extracción interactiva.

    Retorna:
    - diccionario con 'recognized' (bool) y 'items' (lista de diccionarios con 'name', 'price' y 'text').
        - name (str): Nombre del producto.
        - price (str): Precio del producto.
        - text (str): Texto completo del segmento del producto.
    '''

    # Ejemplo simple: extraer todos los enlaces en el HTML
    scrap = classic_extraction(soup)
    if not scrap['recognized'] or history != []:
        scrap = interactive_extraction(driver, max_time, history, depth)
    return scrap


def url_scraping(url): # Incompleta
    '''
    Realiza scraping de un URL para extraer información útil según su tipo de contenido.

    Parámetros:
    - url (str): URL a procesar.

    Retorna:
    - diccionario con 'status' (int), 'content_type' (str) y 'data' (diccionario con 'recognized' (bool) y 'items' (lista de diccionarios con 'name', 'price' y 'text')).
        - name (str): Nombre del producto.
        - price (str): Precio del producto.
        - text (str): Texto completo del segmento del producto.
    '''

    # Headers para simular un navegador real y evitar errores 406
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    
    try:
        response = requests.get(url, timeout=10, headers=headers)
        if response.status_code == 200:
            driver = webdriver.Chrome()
            driver.get(url)
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: len(d.find_element("tag name", "body").get_attribute("innerHTML")) > 1000
                )
            except TimeoutException:
                pass  # Si no se cumple, sigue igual
            time.sleep(2)  # Espera adicional para cargar contenido dinámicos
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Extraer información útil del HTML
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            if 'text/html' in content_type:
                scrap = html_handler(soup, driver)
                driver.quit()
                return {'status': response.status_code, 'content_type': content_type, 'data': scrap}

            return {'status': response.status_code, 'content_type': content_type, 'data': 'Sin contenido para procesar'}
        else:
            return {'status': response.status_code, 'content_type': None, 'data': {'recognized': False, 'items': [], 'stats': {}}}
    except requests.RequestException as e:
        print("Error al acceder al enlace:", e)
        return "error"


if __name__ == "__main__":

    load_dotenv() # Carga de variables de entorno desde .env

    # Rutas de entrada y salida !
    # En la práctica, debería requerir extracción del backend de los códigos QR y comunicación vía API para la salida estructurada
    image_path = os.getenv("IMAGE_PATH")
    save_data_path = Path(os.getenv("SAVE_DATA_PATH"))
    save_data_path.mkdir(parents=True, exist_ok=True)

    # Limpieza previa
    for file in save_data_path.glob("*"):
        if file.is_file():
            file.unlink()

    qr_data = decode_qr_code(image_path) # Procesamiento de los códigos QR (no controla cantidad de batches, obtiene todos !)
    for name, data in qr_data:
        if data == []:
            print(f"{name}: No se detecta código QR o URL válido.")
            continue

        else:
            url = data[0].data.decode("utf-8") # Obtención del URL asociado al QR
            scrap = url_scraping(url) # Scraping del URL, información estructurada en texto plano

            print(f"{name}: {url} -> scrap: status {scrap['status']}, cantidad de elementos: {len(scrap['data']['items'])}")

            if scrap['data']['items'] != []: # Almacenamiento del texto plano en archivo !
                output_file = Path(save_data_path) / f"{name}_scrap.txt"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(f"URL: {url}\n")
                    for item in scrap['data']['items']:
                        f.write(f"Name: {item['name']}\n")
                        f.write(f"Price: {item['price']}\n")
                        f.write(f"Text: {item['text']}\n")
                        f.write("\n")
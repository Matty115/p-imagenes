from pathlib import Path
import re
import cv2
import requests
import time
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

def filter_redundant_items(items):
        if not items:
            return items
        
        # Normalizar y filtrar duplicados exactos
        seen = {}
        for item in items:
            normalized = ' '.join(item['text'].split()).lower()
            if normalized not in seen:
                seen[normalized] = item
        
        unique_items = list(seen.values())
        
        # Filtrar redundancia: si un texto está contenido en otro, descartar el más corto
        filtered = []
        for i, item1 in enumerate(unique_items):
            text1 = item1['text'].lower()
            is_redundant = False
            
            for j, item2 in enumerate(unique_items):
                if i != j:
                    text2 = item2['text'].lower()
                    # Si item1 está contenido en item2, item1 es redundante
                    # (los iguales exactos ya fueron filtrados en la primera fase)
                    if text1 in text2:
                        is_redundant = True
                        break
            
            if not is_redundant:
                filtered.append(item1)
        
        return filtered

def classic_extraction(soup):
    # Parámetros de umbralización
    PRICES_THRESHOLD = 10
    KEYWORD_THRESHOLD = 1 
    MIN_LENGTH = 10
    MAX_LENGTH = 1000
    CONTEXT_SPAN = 50

    text = soup.get_text(strip=True)

    # Regex con non-capturing groups (?:...) para evitar tuplas de grupos
    price_pattern = r"(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?\s*(\d{1,3}([.,]\d{3})*[.,]\d{2,3}|\d{3,})\s*(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?"
    prices = list(re.finditer(price_pattern, text, flags=re.IGNORECASE))
    price_count = len(prices)

    keywords = ['sol', 'heineken', 'stella artois'] # necesidad de listado oficial
    keyword_hits = sum(1 for kw in keywords if kw.lower() in text.lower())

    recognized = price_count >= PRICES_THRESHOLD and keyword_hits >= KEYWORD_THRESHOLD
    if not recognized:
        return {
        'recognized': False,
        'items': []
    }

    def item_info(element):
        item_class = element.get('class')
        matches = [m.group(0) for m in re.finditer(price_pattern, text_block, flags=re.IGNORECASE)]
        return item_class, matches

    items = []

    # Búsqueda en listas, tablas y divs
    for el in soup.find_all(['li', 'tr', 'div']):
        text_block = el.get_text(strip=True)
        if len(text_block) < MIN_LENGTH or len(text_block) > MAX_LENGTH:
            continue
        item_class, item_matches = item_info(el)
        if item_matches != []:
            items.append({'class': item_class, 'text': text_block, 'matches': item_matches})

    # Fallback: contexto de precios si no se encontraron items
    if not items:
        for match in prices:
            ctx_start = max(0, match.start() - CONTEXT_SPAN)
            ctx_end = match.end() + CONTEXT_SPAN
            context = text[ctx_start:ctx_end].strip()
            items.append({'class': f'Contexto entre {ctx_start}-{ctx_end}', 'text': context, 'matches': [match.group(0)]})
    
    items = filter_redundant_items(items)

    return {
        'recognized': True,
        'items': items
    }


def interactive_extraction(driver, max_time=60, history=[]):
    url = driver.current_url
    out = {'recognized': False, 'items': []}
    if url in history:
        return out
    start = time.time()
    last_height = 0
    while time.time() - start < max_time:
        # Scroll hacia abajo
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        # Expandir acordeones/tabs
        for tag in ['button', 'a', 'span', 'li', 'td', 'div']:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                            text = el.text.lower()
                            if any(keyword in text for keyword in ['whatsapp', 'facebook', 'instagram', 'twitter', 'tiktok', 'youtube', 'wix', 'acceder', 'iniciar sesión', 'registrarse', 'suscribirse', 'comprar', 'pagar', 'donar']):
                                continue
                            reference = el.get_attribute('href')  # Para enlaces
                            if reference is None:
                                reference = el.get_attribute('onClick')  # Para otros elementos
                            if reference and any(domain in reference for domain in ['whatsapp.com', 'facebook.com', 'instagram.com', 'twitter.com', 'tiktok.com', 'youtube.com', 'wix.com', 'x.com', 'wa.me', 'wa.link', 'linkedin.com', 'messenger.com', 'snapchat.com', ]):
                                continue

                            el.click() # Clickea en cualquier cosa, ojo
                            time.sleep(1)
                            soup = BeautifulSoup(driver.page_source, 'html.parser')
                            classic_redirected = classic_extraction(soup)

                            if classic_redirected['recognized']:
                                out['recognized'] = True
                                out['items'].extend(classic_redirected['items']) # Revisar si conviene deduplicar

                            redirected = interactive_extraction(driver, max_time - (time.time() - start), history + [url])
                            out['recognized'] = out['recognized'] or redirected['recognized']
                            out['items'].extend(redirected['items'])
                            out['items'] = filter_redundant_items(out['items'])
                            driver.back()
                                
                    except (ElementClickInterceptedException, ElementNotInteractableException):
                        continue
            except Exception:
                continue
    return out


def html_handler(soup, driver):
    # Ejemplo simple: extraer todos los enlaces en el HTML
    scrap = classic_extraction(soup)
    if not scrap['recognized']:
        scrap = interactive_extraction(driver)
    return scrap

def url_scraping(url):
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
    # Rutas de entrada y salida
    # En la práctica, debería requerir extracción del backend y comunicación vía API para la salida
    image_path = os.getenv("IMAGE_PATH")
    save_data_path = Path(os.getenv("SAVE_DATA_PATH"))
    save_data_path.mkdir(parents=True, exist_ok=True)

    for file in save_data_path.glob("*"): # Limpieza previa
        if file.is_file():
            file.unlink()

    qr_data = decode_qr_code(image_path) # Procesamiento del batch
    for name, data in qr_data:
        if data == []:
            #print(f"{name}: NO LINK")
            continue

        else:
            url = data[0].data.decode("utf-8") # Obtención del URL asociado al QR
            scrap = url_scraping(url) # Scraping del URL, información estructurada en texto plano

            print(f"{name}: {url} -> scrap: status {scrap['status']}, elementos: {[len(item['text']) for item in scrap['data']['items']]}")

            if scrap['data']['items'] != []: # Almacenamiento del texto plano
                output_file = Path(save_data_path) / f"{name}_scrap.txt"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(f"URL: {url}\n")
                    for item in scrap['data']['items']:
                        f.write(f"Class: {item['class']}\n")
                        f.write(f"Text: {item['text']}\n")
                        f.write("\n")
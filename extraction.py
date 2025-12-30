import re
import time
import unicodedata

from bs4 import BeautifulSoup

import requests
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import ElementClickInterceptedException, ElementNotInteractableException
from selenium.webdriver.common.by import By

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

BANNED_DOMAINS = ["whatsapp.com","facebook.com","instagram.com","twitter.com","tiktok.com","youtube.com","wix.com","x.com","wa.me","wa.link","linkedin.com","messenger.com","snapchat.com","drive.google.com/?tab=oo","play.google.com"]
BANNED_TERMS = ['whatsapp', 'facebook', 'instagram', 'twitter', 'tiktok', 'youtube', 'wix', 'acceder', 'iniciar sesion', 'registrarse', 'suscribirse', 'comprar', 'pagar', 'donar', 'descargar', 'contacto', 'contactanos', 'contacta', 'llamanos', 'mensajeria', 'messenger', 'linkedin', 'snapchat', 'google drive', 'play store']

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
    #MAX_LENGTH = 1000

    compact_text = normalize_text(soup.get_text(strip=True)) # Texto completo normalizado

    price_pattern = r"(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?\s?(\d{1,3}([.,]\d{3}\s?)*[.,]\d{2,3}|(\d\s?){3,})\s*(?:[$€₲]|(?:CLP|USD|EUR|COP|ARS|UYU|BOL|PYG))?" # Exp. regular relajada para detección de precios

    # Conteo de precios y palabras clave en el texto
    matches = list(re.finditer(price_pattern, compact_text, flags=re.IGNORECASE))
    price_count = len(matches)

    # Conteo de presencia de productos clave en el texto
    keywords = ['sol', 'heineken', 'stella artois'] # Necesidad de listado de productos CCU, competencia y productos, para mejorar calidad de detección !
    keyword_hits = sum(1 for kw in keywords if kw.lower() in compact_text.lower())

    # Si no supera los umbrales mínimos, probablemente no tiene información útil en el HTML
    recognized = price_count >= PRICES_THRESHOLD and keyword_hits >= KEYWORD_THRESHOLD
    if not recognized:
        return {
            'recognized': False,
            'full_text': normalize_text(soup.get_text(strip=True, separator=' ')),
            'items': []
        }

    items = []

    # Búsqueda en listas, tablas y divs
    for el in soup.find_all(['li', 'tr', 'p', 'td', 'div']):
        clean_block = normalize_text(el.get_text(strip=True, separator=' ')) # Texto limpio del bloque asociado a la etiqueta

        # Evitar bloques muy cortos o subtextos ya procesados
        if not clean_block or len(clean_block) < MIN_LENGTH:
            continue

        block_matches = list(re.finditer(price_pattern, clean_block, flags=re.IGNORECASE)) # Búsqueda de precios en el bloque

        if block_matches:
            sub_items = split_multi_item_block(clean_block, block_matches) # División en sub-items si hay múltiples precios en el bloque

            if sub_items:
                # Almacenamiento de los items extraídos
                items.extend(sub_items)

    items = filter_redundant_items(items) # Se elimina la redundancia

    return {
        'recognized': True,
        'full_text': normalize_text(soup.get_text(strip=True, separator=' ')),
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

    # Inicialización
    url = driver.current_url
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    text = normalize_text(soup.get_text(strip=True, separator=' '))
    out = {
        'recognized': False,
        'full_text': text,
        'items': []
    }

    # Deja de buscar si ya se visitó la URL, o si no se debe visitar la URL, o si hay demasiada profundidad de búsqueda sobre URLs 
    if url in history or depth > 5 or url in BANNED_DOMAINS:
        if url not in history:
            history.append(url)
        return out
    
    # Se marca como revisada la URL y se le aplica extracción clásica
    history.append(url)
    actual = classic_extraction(soup)

    # Se inicializan parámetros de scroll e interacción
    step_size = 500
    current_position = 0
    total_height = driver.execute_script("return document.body.scrollHeight")
    start = time.time()

    while time.time() - start < max_time:
        current_position += step_size # El scroll desplaza la página en step_size píxeles
        if current_position >= total_height:
            break
        
        # Scroll hacia abajo
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(1)

        # Actualización de la altura total si es mayor
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height > total_height:
            total_height = new_height

        # Interacción con elementos
        for tag in ['button', 'a', 'span', 'li', 'td', 'div']:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                #print(elements)
                for el in elements:
                    try:    
                            # Características del elemento
                            tag = el.tag_name.lower()
                            href = el.get_attribute('href')
                            onclick = el.get_attribute('onclick')
                            role = el.get_attribute('role')
                            class_attr = el.get_attribute('class') or ''
                            reference = href or onclick

                            # Determinación si el elemento es interactivo
                            is_interactive = (
                                (tag == 'a' and href) or
                                (tag == 'button') or
                                onclick or
                                (role and 'button' in role.lower()) or
                                ('button' in class_attr.lower() or 'accordion' in class_attr.lower())
                            )
                            
                            # Discriminación de elementos no interactivos
                            if not is_interactive:
                                continue

                            text = normalize_text(el.text.lower())

                            # Filtro de elementos con términos no deseados
                            is_banned_term = False
                            for keyword in BANNED_TERMS:
                                if keyword in text:
                                    is_banned_term = True
                                    break
                        
                            if is_banned_term:
                                continue
                            
                            # Filtro de dominios no deseados o URLs ya visitadas
                            # Esta forma ahorra algo de memoria y es más estable, y por ende confiable
                            is_banned_domain = False
                            for domain in BANNED_DOMAINS:
                                if domain in reference:
                                    is_banned_domain = True
                                    break

                            if reference is not None and (is_banned_domain or reference in history):
                                continue
                            old_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                            el.click() # Click en el elemento
                            WebDriverWait(driver, 10).until(
                                lambda d: d.find_element(By.TAG_NAME, "body").get_attribute("innerHTML") != old_html
                            )
                            
                            # Nueva página tras la interacción
                            new_html = driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                            new_url = driver.current_url

                            # Si el HTML cambió, se llama a html_handler
                            if new_html != old_html:
                                new = html_handler(driver, max_time - (time.time() - start), history, depth + 1)

                                # Se incorporan resultados de la extracción
                                actual['recognized'] = actual['recognized'] or new['recognized']
                                actual['items'].extend(new['items'])
                                actual['items'] = filter_redundant_items(actual['items'])
                                if actual['full_text'] in new['full_text']:
                                    actual['full_text'] = new['full_text']

                            # Actualización del historial y volvemos a la página anterior si cambió la URL 
                            if reference:
                                history.append(reference)
                            if new_url != url:
                                history.append(new_url)
                                driver.back()
                                
                    except (ElementClickInterceptedException, ElementNotInteractableException):
                        continue

            except Exception:
                pass
            
    return actual


def html_handler(driver, max_time=60, history=[], depth=0): # Incompleta, potencial cambio de orden de procedimientos
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
    time.sleep(2)
    scrap = classic_extraction(BeautifulSoup(driver.page_source, 'html.parser'))
    if not scrap['recognized'] or history:
        scrap = interactive_extraction(driver, max_time, history, depth)

    ## PENDIENTE: Imágenes/PDFs embedidos en el HTML

    return scrap
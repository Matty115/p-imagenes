from pathlib import Path
import requests
import time

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from dotenv import load_dotenv
import os

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from extraction import html_handler


def url_scraping_controller(url): # Incompleta
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

    # Headers para simular un navegador real y evitar errores
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

            # Inicialización de Selenium WebDriver (esto debería desplazarlo a interactive_extraction)
            driver = webdriver.Chrome()
            driver.get(url)
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: len(d.find_element("tag name", "body").get_attribute("innerHTML")) > 1000
                )
            except TimeoutException:
                pass  # Si no se cumple, sigue igual
            
            # Extraer información útil del HTML
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            scrap = {}
            if 'text/html' in content_type:
                scrap = html_handler(driver)
            driver.quit()
            return {'status': response.status_code, 'content_type': content_type, 'data': scrap}


            ## PENDIENTE: Manejo de otros tipos de contenido (PDF, imágenes, etc.)

        else:
            return {'status': response.status_code, 'content_type': None, 'data': {'recognized': False, 'items': []}}
    except requests.RequestException as e:
        print("Error al acceder al enlace:", e)
        return {'status': None, 'content_type': None, 'data': {'recognized': False, 'items': []}}


load_dotenv() # Carga de variables de entorno desde .env

# Rutas de entrada y salida !
# En la práctica, debería requerir extracción del backend de los códigos QR y comunicación vía API para la salida estructurada
main_path = Path(__file__).parent
qr_file_name = "qr_url.txt"
input_file = main_path / qr_file_name
save_data_path = Path(os.getenv("SAVE_DATA_PATH"))
save_data_path.mkdir(parents=True, exist_ok=True)

# Limpieza previa
for file in save_data_path.glob("*"):
    if file.is_file():
        file.unlink()

with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        name, url = [el.strip() for el in line.split(",")]
        if not url:
            print(f"{name}: No se detectó dirección URL.")
            continue

        else:
            scrap = url_scraping_controller(url) # Scraping del URL, información estructurada en texto plano
            print(f"{name}: {url} -> scrap: status {scrap['status']}, cantidad de elementos: {len(scrap['data']['items'])}")
            
            # Almacenamiento del texto plano en archivo !
            if scrap['data']['items']:
                output_file = Path(save_data_path) / f"{name}_scrap.txt"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(f"URL: {url}\n")
                    for item in scrap['data']['items']:
                        f.write(f"Name: {item['name']}\n")
                        f.write(f"Price: {item['price']}\n")
                        f.write(f"Text: {item['text']}\n")
                        f.write("\n")
import tempfile
from uuid import uuid4
from urllib.parse import urlparse, unquote
from pathlib import Path
from contextlib import redirect_stderr, contextmanager
import requests
import pandas as pd
import cv2
from pyzbar.pyzbar import decode
from dotenv import load_dotenv
import os
from google.cloud import storage
import time

client = storage.Client.from_service_account_json("credentials.json")
bucket = client.bucket("read-image-storage-qr")


@contextmanager
def _silence_stderr_fd():
    # Silencia stderr a nivel de descriptor (zbar escribe directo al fd 2)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stderr = os.dup(2)
    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stderr, 2)
        os.close(devnull_fd)
        os.close(saved_stderr)


def safe_decode(img):
    try:
        with open(os.devnull, "w") as devnull, redirect_stderr(devnull), _silence_stderr_fd():
            return decode(img)
    except Exception:
        return []

def fetch_image(url_or_blob):

    if not url_or_blob or not isinstance(url_or_blob, str):
        return None

    tmp = Path(tempfile.gettempdir()) / f"qr_{uuid4().hex}.img"
    parsed = urlparse(url_or_blob)

    # Caso GCS: storage.cloud.google.com/<bucket>/<objeto>
    if parsed.netloc == "storage.cloud.google.com":
        
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) < 2:
            return None
        bucket_name, blob_path = parts
        if bucket_name == "undefined" or blob_path.startswith("undefined"):
            return None
        try:
            bucket = client.bucket(bucket_name)
            bucket.blob(unquote(blob_path)).download_to_filename(tmp)
            time.sleep(2)
            return tmp
        except Exception as exc:
            print(f"No se pudo bajar desde GCS {bucket_name}/{blob_path}: {exc}")
            return None

    try:
        resp = requests.get(url_or_blob, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(1024):
                f.write(chunk)
        return tmp
    except Exception as exc:
        print(f"No se pudo bajar por HTTP {url_or_blob}: {exc}")
        return None

def decode_qr_code(image_with_url):
    '''
    Decodifica códigos QR en imágenes dentro de una carpeta, aplicando técnicas de preprocesamiento si la detección inicial falla.

    Parámetros:
    - folder_path (str): Ruta a la carpeta que contiene las imágenes.
    
    Retorna:
    - data (list): Lista de tuplas (nombre_imagen, datos_decodificados).
        - nombre_imagen (str): Nombre del archivo de imagen.
        - datos_decodificados (list): Lista de objetos decodificados por pyzbar, o lista vacía si no se detecta ningún código QR.
    '''

    # Obtención y procesamiento de cada imagen en la carpeta
    
    file_path = fetch_image(image_with_url)
    if not file_path or not Path(file_path).exists():
        return None

    matrix = cv2.imread(str(file_path)) # Obtención de imagen en BGR, NO RGB
    if matrix is None:
        file_path.unlink(missing_ok=True)
        return None

    decodedImage = safe_decode(matrix) # Intento inicial de decodificación
    
    # Si no se detectó, se aplican técnicas de preprocesamiento
    if matrix is not None and decodedImage == []:

        # Conversión a escala de grises
        gray = cv2.cvtColor(matrix, cv2.COLOR_BGR2GRAY)
        decodedImage = safe_decode(gray)
        
        # Umbralización adaptativa
        if decodedImage == []:
            thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                        cv2.THRESH_BINARY, 11, 2)
            decodedImage = safe_decode(thresh)
        
        # Aumento de contraste
        if decodedImage == []:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)
            decodedImage = safe_decode(enhanced)
        
        # Umbralización simple (Otsu)
        if decodedImage == []:
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            decodedImage = safe_decode(otsu)
        
        # Aumento de tamaño de la imagen
        if decodedImage == []:
            resized = cv2.resize(matrix, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            decodedImage = safe_decode(resized)

    file_path.unlink(missing_ok=True) # Eliminación del archivo temporal
    return decodedImage if decodedImage != [] else None


def insert_into_qr_url(fk, url_image, url_link):
        '''
        Simula un insert/update en el archivo qr_url.csv:
        - Si la fk existe y la url es distinta, actualiza la url.
        - Si la fk no existe, inserta una nueva fila con nuevo id.
        '''

        main_path = Path(__file__).parent
        qr_file_name = "qr_url.csv"
        output_file = main_path / qr_file_name

        # Leer el archivo existente o crear DataFrame vacío
        if output_file.exists() and output_file.stat().st_size > 0:
            df = pd.read_csv(output_file)
        else:
            df = pd.DataFrame(columns=["id", "id_cliente", "url_carta", "url_obtenida"])

        # Buscar si la fk ya existe
        idx = df.index[df['id_cliente'] == fk].tolist()
        if idx:
            # Si existe, chequear si la url es distinta
            i = idx[0]
            if df.at[i, 'url_carta'] != url_image:
                df.at[i, 'url_carta'] = url_image  # Actualizar url
            if df.at[i, 'url_obtenida'] != url_link:
                df.at[i, 'url_obtenida'] = url_link  # Actualizar url obtenida
        else:
            # Si no existe, agregar nueva fila con nuevo id
            new_id = df['id'].max() + 1 if not df.empty else 1
            print(  f"Insertando nueva fila: id {new_id}, fk {fk}, url de imagen {url_image}, url obtenida {url_link}" )
            df = pd.concat([df, pd.DataFrame([[new_id, fk, url_image, url_link]], columns=["id", "id_cliente", "url_carta", "url_obtenida"])], ignore_index=True)

        # Sobrescribir el archivo CSV
        df.to_csv(output_file, index=False)
    

def start_qr_lecture():
    '''
    Inicia la lectura de códigos QR, para luego almacenar los URLs decodificados en un archivo de texto.
    '''

    load_dotenv() # Carga de variables de entorno desde .env

    # Ubicación de la carpeta con imágenes y del archivo de salida
    # EN UNA VERSIÓN MADURA, ESTO NO DEBERÍA SER ASÍ
    main_path = Path(__file__).parent
    qr_file_name = "qr_url.csv"
    images_name = "images.csv"
    output_file = main_path / qr_file_name
    image_file = main_path / images_name
    image_df = pd.read_csv(image_file)[:700]
    id = 0

    if output_file.exists() and output_file.stat().st_size > 0:
        out_df = pd.read_csv(output_file)
        id = len(out_df)
    else:
        out_df = pd.DataFrame(columns=["id", "fk", "url_carta"])

    for _, row in image_df.iterrows():
        id += 1
        fk = row['response_id']
        url_with_image = row['f0_']
        qr_data = decode_qr_code(url_with_image) # Procesamiento de los códigos QR (no controla cantidad de batches, obtiene todos !)
        url_carta = qr_data[0].data.decode("utf-8") if qr_data is not None else None
        insert_into_qr_url(fk, url_with_image, url_carta)


start_qr_lecture()
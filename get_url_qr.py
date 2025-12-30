import csv
from pathlib import Path
import requests
import pandas as pd
import cv2
from pyzbar.pyzbar import decode
from dotenv import load_dotenv
import os
from google.cloud import storage


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
    response = requests.get(image_with_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    if response.status_code != 200:
        print(f"Error al descargar la imagen desde {image_with_url}: Código {response.status_code}")
        return None
    print(response.url)
    filename = response.title if 'title' in response.headers else image_with_url.split("/")[-1]
    file_path = Path(__file__).parent / filename
    with open(file_path, "wb") as img_file:
        for chunk in response.iter_content(1024):
            img_file.write(chunk)

    matrix = cv2.imread(str(file_path)) # Obtención de imagen en BGR, NO RGB
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

    file_path.unlink(missing_ok=True) # Eliminación del archivo temporal
    return decodedImage if decodedImage != [] else None

def insert_into_qr_url(fk, url):
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
            df = pd.DataFrame(columns=["id", "fk", "url_carta"])

        # Buscar si la fk ya existe
        idx = df.index[df['fk'] == fk].tolist()
        if idx:
            # Si existe, chequear si la url es distinta
            i = idx[0]
            if df.at[i, 'url_carta'] != url:
                df.at[i, 'url_carta'] = url  # Actualizar url
        else:
            # Si no existe, agregar nueva fila con nuevo id
            new_id = df['id'].max() + 1 if not df.empty else 1
            print("hoal")
            df = pd.concat([df, pd.DataFrame([[new_id, fk, url]], columns=["id", "fk", "url_carta"])], ignore_index=True)

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
        image_with_url = row['f0_']
        qr_data = decode_qr_code(image_with_url) # Procesamiento de los códigos QR (no controla cantidad de batches, obtiene todos !)
        url_carta = qr_data[0].data.decode("utf-8") if qr_data is not None else None
        insert_into_qr_url(fk, url_carta)


start_qr_lecture()
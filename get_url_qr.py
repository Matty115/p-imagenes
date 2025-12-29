from pathlib import Path
import cv2
from pyzbar.pyzbar import decode
from dotenv import load_dotenv
import os


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


def start_qr_lecture():
    '''
    Inicia la lectura de códigos QR, para luego almacenar los URLs decodificados en un archivo de texto.
    '''

    load_dotenv() # Carga de variables de entorno desde .env

    # Ubicación de la carpeta con imágenes y del archivo de salida
    # EN UNA VERSIÓN MADURA, ESTO NO DEBERÍA SER ASÍ
    main_path = Path(__file__).parent
    qr_file_name = "qr_url.txt"
    output_file = main_path / qr_file_name
    image_path = os.getenv("IMAGE_PATH")

    # Limpieza previa (mientras se trabaje con archivos)
    if qr_file_name in os.listdir(main_path):
        os.remove(main_path / qr_file_name)

    with open(output_file, "a", encoding="utf-8") as f:
        qr_data = decode_qr_code(image_path) # Procesamiento de los códigos QR (no controla cantidad de batches, obtiene todos !)
        for name, data in qr_data:
            if not data:
                print(f"{name}: No se detecta código QR o URL válido.")
                continue

            else:
                url = data[0].data.decode("utf-8") # Obtención del URL asociado al QR
                f.write(f"{name},{url}\n")
        f.close()


start_qr_lecture()
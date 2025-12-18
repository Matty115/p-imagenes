# Descarable apenas hayan casos reales

import qrcode
from pathlib import Path
import random

output_folder = Path("C:\\Users\\msandovalk\\Documents\\p-imagenes\\Imagenes")
output_folder.mkdir(parents=True, exist_ok=True)

for f in output_folder.glob("*"):
    if f.is_file():
        f.unlink()

N = 0
img, pdf, html = 1, 1, 1

for i in range(N):
    url = ""
    n = random.randint(1, 3)
    if n == 1:
        url = f"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf?id={pdf}"
        pdf += 1
    elif n == 2:
        url = f"https://example.com/page_{html}.html"
        html += 1
    else:
        url = f"https://placehold.co/256x256/png?text=IMG_{img}"
        img += 1

    qr = qrcode.make(url)
    img_name = f"qr_{i}.png"
    img_path = output_folder / img_name
    qr.save(img_path)
    print(f"Generated QR code for {url} at {img_path}")
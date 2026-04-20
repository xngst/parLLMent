import re
import requests
import time
import random

from bs4 import BeautifulSoup
from pathlib import Path

url = "https://www.parlament.hu/web/guest/orszaggyulesi-naplo-2014-2018"
#url = "https://www.parlament.hu/web/guest/orszaggyulesi-naplo-2018-2022"
base = "https://www.parlament.hu"
file_path = Path(r"Parlament/raw_pdf/2018-2022")
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

collector_page = requests.get(url)
soup = BeautifulSoup(collector_page.text, "html.parser")
issues = soup.find_all('a', href=re.compile(r'/documents/10181'))
links = sorted([base + i['href'] if base not in i['href'] else i['href'] for i in issues])

down_list = []
failed_list = []

for file_url in links:
    print(file_url)
    try:
        response = requests.get(file_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        file_name = file_path.joinpath(file_url.split("/")[6])
        with open(file_name, "wb") as f:
            f.write(response.content)
        
        down_list.append(file_url)
    except requests.RequestException as e:
        print(f"Letöltési hiba: {e}")
        failed_list.append(file_url)
        
    time.sleep(random.uniform(7.5, 10.2))

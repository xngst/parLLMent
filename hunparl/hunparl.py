import re
import functools
import requests
from bs4 import BeautifulSoup
from io import StringIO
from pathlib import Path
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from urllib import parse

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

__all__ = ['OgyNaplo']

@functools.lru_cache(maxsize=None)
def _get_issue_map() -> dict:
    url = "https://www.parlament.hu/orszaggyulesi-naplo"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, verify=False, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Hálózati hiba: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    issue_dict = {}

    # Find all links starting with /documents/
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if "/documents/" in href:
            text = a.get_text(strip=True)
            try:
                # Extract number from "12. szám" or similar
                match = re.search(r"(\d+)", text)
                if match:
                    num = int(match.group(1))
                    issue_dict[num] = parse.urljoin("https://www.parlament.hu/", href)
            except ValueError:
                continue
    return issue_dict


# --- SCRAPER LOGIC ---


def scraper(homedir: str, szam: int = -1) -> str:
    """
    Letölti a megadott számú naplót. Ha szam=-1, a legfrissebbet tölti le.
    """
    home_path = Path(homedir)
    home_path.mkdir(parents=True, exist_ok=True)

    issue_map = _get_issue_map()
    if not issue_map:
        return "Nem sikerült letölteni a listát."

    target_szam = szam if szam != -1 else max(issue_map.keys())

    if target_szam not in issue_map:
        return f"A(z) {target_szam}. szám nem található."

    file_url = issue_map[target_szam]
    file_path = home_path / f"Országgyűlési Napló {target_szam}.szám.pdf"

    print(f"Letöltés: {file_url}...")
    try:
        response = requests.get(file_url, verify=False)
    except requests.RequestException as e:
        return f"Letöltési hiba: {e}"

    with open(file_path, "wb") as f:
        f.write(response.content)

    print(f"Mentve: {file_path}")
    return str(file_path)


def szam_lista() -> list:
    return sorted(_get_issue_map().keys())


def legujabb_szam() -> int:
    issues = _get_issue_map()
    return max(issues.keys()) if issues else 0


# --- PDF PROCESSING ---

def pdf_to_txt(path: str) -> str:
    """
    Konvertálja a megadott PDF fájlt szöveggé hibakezeléssel.
    """
    rsrcmgr = PDFResourceManager()
    retstr = StringIO()
    laparams = LAParams()
    device = None 
    
    try:
        device = TextConverter(rsrcmgr, retstr, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)

        with open(path, "rb") as file:
            for page in PDFPage.get_pages(file):
                interpreter.process_page(page)

        text = retstr.getvalue()
        return text

    except FileNotFoundError:
        print(f"A fájl nem található: {path}")
        return ""
    except Exception as e:
        print(f"Hiba történt a PDF feldolgozása közben ({path}): {e}")
        return ""

    finally:
        if device:
            device.close()
        retstr.close()


def ogy_n_tisztazo(text: str) -> str:
    """Szöveg tisztítása regex segítségével."""
    # Sorvégi elválasztás törlése
    text = re.sub(r"-\n", "", text)
    # Időbélyegek törlése (pl. (9.10))
    text = re.sub(r" \n\n \(\d{1,2}\.\d{2}\) \n\n \n", "", text)
    # Oldalszámok és fejlécek
    text = re.sub(r"\n\n\x0c\d{4,5}|\n\n\d{5}", "", text)
    text = re.sub(r"\n\nAz Országgyűlés.*ülés.*\n", "", text)

    # Whitespace tisztítás
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --- DATA EXTRACTION ---



def get_regex_match(pattern, text, default="Ismeretlen"):
    match = re.search(pattern, text)
    return match.group(1).strip() if match else default


def fix_pdf_typos(text: str) -> str:
    # Hibás alak: Javított alak
    typo_map = {
        "so raiban": "soraiban",
        "padsora iban": "padsoraiban",
        "kor mánypárti": "kormánypárti",
        "pad sor": "padsor",
        "taps vihar": "tapsvihar"
    }
    for typo, fixed in typo_map.items():
        text = text.replace(typo, fixed)
    return text

def szam_extractor(text: str) -> str:
    return get_regex_match(r"(\d{1,3}(?:/\d{1,2})?)\.\sszám", text)


def ciklus(text: str) -> str:
    return get_regex_match(r"(\d{4}-\d{4}\.\sországgyűlési ciklus)", text)


def ules_datum(text: str) -> str:
    return get_regex_match(r"(\d{4}\.\s\w+\s\d{1,2}\.)", text)


def elnok_lista(text: str) -> list:
    raw = get_regex_match(r"Napló (.*) elnöklete alatt", text, "")
    if not raw:
        return []
    return [i.strip() for i in raw.replace("és", ",").split(",")]


def jegyzo_lista(text: str) -> list:
    raw = get_regex_match(r"Jegyzők:(.*)Tárgyai", text, "")
    if not raw:
        return []
    # Tisztítás a speciális karakterektől
    clean = raw.replace("\x0c", "").replace("  ", " ")
    return [i.strip() for i in clean.split(",")]


def torzs_szoveg(text: str) -> str:
    start_match = re.search(r"ELNÖK:", text)
    if not start_match:
        return text

    end_idx = text.find("ülésnapot bezárom.")
    if end_idx == -1:
        return text[start_match.start() :]
    return text[start_match.start() : end_idx]


def kepviselo_lista(text: str) -> list:
    pattern = re.compile(r"((?:DR\.\s)?[A-ZÁÍÉÓÖŐÚÜŰ-]{3,}(?:\s[A-ZÁÍÉÓÖŐÚÜŰ-]{3,})+)")
    matches = pattern.findall(text)
    excluded = ["JEGYZŐK", "NAPLÓ", "MINDEN JOG FENNTARTVA"]
    results = set(m for m in matches if m not in excluded)
    # Remove plain version if DR. version exists
    results = {m for m in results if f"DR. {m}" not in results}
    return sorted(results)


def kepviseloi_felszolalas_szotar(text: str, mp_list: list) -> dict:
    fel_szotar = {}
    for name in mp_list:
        # Megkeressük az összes előfordulást
        starts = [m.start() for m in re.finditer(re.escape(name), text)]
        if not starts:
            continue

        speeches = []
        for start in starts:
            # A beszéd végét az "ELNÖK:" felirat jelzi
            fragment = text[start:]
            end_match = re.search(r"ELNÖK:", fragment[len(name) :])
            if end_match:
                speeches.append(fragment[: end_match.start() + len(name)].strip())
            else:
                speeches.append(fragment.strip())

        fel_szotar[name] = (
            speeches if len(speeches) > 1 else (speeches[0] if speeches else "")
        )
    return fel_szotar



def reakcio_lista(text: str) -> list:
    """
    Kigyűjti a zárójeles reakciókat, kiszűrve a pártneveket és technikai jelzéseket.
    """
    # Regex: (Nagybetűvel kezdődő, bármi ami nem zárójel, zárójel bezárva)
    emot_pat = re.compile(r"\([A-ZÁÍÉÓÖŐÚÜŰ][^)]+\)")
    emot_list = emot_pat.findall(text)
    
    # Prefix alapú szűrés (ha ezzel kezdődik, eldobjuk)
    excluded_prefixes = (
        "szavazás", "szünet", "rövid szünet", "az elnöki széket", "jelzésre:"
        "határozathozatal", "fidesz", "mszp", "jobbik", 
        "lmp", "kdnp", "dk", "momentum"
    )

    sanitized = []
    for item in emot_list:
        cleaned = item.strip("() ").strip()
        cleaned = fix_pdf_typos(cleaned)
        # Szűrés a tiltott kezdő szavakra
        if cleaned.lower().startswith(excluded_prefixes):
            continue

        # Karakterhossz alapú finomhangolás elemenként (nem a listára!)
        # Pl. a túl rövid "(A)" vagy túl hosszú (fél oldalas) technikai szövegek ellen
        if 3 < len(cleaned) < 200:
            sanitized.append(cleaned)
            
    # Mindig listát adunk vissza, maximum üreset
    return sanitized


def reakcio_szotar_keszito(beszed_szotar: dict) -> dict:
    """
    Végigmegy a képviselői beszédek szótárán, és minden beszédhez
    kigyűjti a benne elhangzott reakciókat.
    """
    reakciok = {}
    for nev, beszedek in beszed_szotar.items():
        if isinstance(beszedek, list):
            # Ha több beszéd van, listák listáját kapjuk
            lista = [r for b in beszedek if (r := reakcio_lista(b))]
            if lista:
                reakciok[nev] = lista
        else:
            # Ha csak egy beszéd van
            lista = reakcio_lista(beszedek)
            if lista:
                reakciok[nev] = lista
    return reakciok


# --- CLASS DEFINITION ---


class OgyNaplo:
    """
    Osztály az országgyűlési napló feldolgozásához.
    Lazy loading: a nehéz műveletek csak első lekéréskor futnak le.
    """

    def __init__(self, path: str):
        self.path = path
        self._raw_text: str | None = None
        self._tisztazott: str | None = None
        self._torzs: str | None = None
        self._kepviselok: list | None = None
        self._beszedek: dict | None = None
        self._osszes_reakcio: list | None = None
        self._kepviseloi_reakciok: dict | None = None

    # --- Alap szöveg ---

    @property
    def raw_text(self) -> str:
        if self._raw_text is None:
            self._raw_text = pdf_to_txt(self.path)
        return self._raw_text

    @property
    def tisztazott(self) -> str:
        if self._tisztazott is None:
            self._tisztazott = ogy_n_tisztazo(self.raw_text)
        return self._tisztazott

    # --- Metaadatok (gyors, de a tisztazott szövegtől függ) ---

    @property
    def szam(self) -> str:
        return szam_extractor(self.tisztazott)

    @property
    def ciklus(self) -> str:
        return ciklus(self.tisztazott)

    @property
    def datum(self) -> str:
        return ules_datum(self.tisztazott)

    @property
    def elnokok(self) -> list:
        return elnok_lista(self.tisztazott)

    @property
    def jegyzok(self) -> list:
        return jegyzo_lista(self.tisztazott)

    # --- Tartalmi adatok (nehéz műveletek) ---

    @property
    def torzs(self) -> str:
        if self._torzs is None:
            self._torzs = torzs_szoveg(self.tisztazott)
        return self._torzs

    @property
    def kepviselok(self) -> list:
        if self._kepviselok is None:
            self._kepviselok = kepviselo_lista(self.tisztazott)
        return self._kepviselok

    @property
    def beszedek(self) -> dict:
        if self._beszedek is None:
            self._beszedek = kepviseloi_felszolalas_szotar(self.torzs, self.kepviselok)
        return self._beszedek

    @property
    def osszes_reakcio(self) -> list:
        if self._osszes_reakcio is None:
            self._osszes_reakcio = reakcio_lista(self.torzs)
        return self._osszes_reakcio

    @property
    def kepviseloi_reakciok(self) -> dict:
        if self._kepviseloi_reakciok is None:
            self._kepviseloi_reakciok = reakcio_szotar_keszito(self.beszedek)
        return self._kepviseloi_reakciok

    def __repr__(self):
        return f"<OgyNaplo szam={self.szam}, datum={self.datum}>"

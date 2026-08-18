import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time

# CONFIGURATIE
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "bekende_vacatures.json"

# Doelorganisaties en trefwoorden om op te zoeken en te filteren
KEYWORDS_ORG = ["defensie", "mivd", "aivd", "algemene inlichtingen", "militaire inlichtingen", "jscu", "jdeu"]

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram niet geconfigureerd. Log:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("Telegram-notificatie succesvol verzonden.")
    except Exception as e:
        print(f"Fout bij verzenden Telegram: {e}")

def get_unique_vacancy_links():
    search_terms = ["defensie", "aivd", "mivd", "inlichtingen", "veiligheidsdienst", "jscu", "jdeu"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    unique_links = set()
    
    for term in search_terms:
        search_url = f"https://www.werkenvoornederland.nl/vacatures?term={term}"
        print(f"Zoeken op term: '{term}' via {search_url}...")
        try:
            response = requests.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print(f"⚠️ Fout bij ophalen van zoekresultaten voor '{term}': {e}")
            continue
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Zoek alle links naar vacatures
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/vacatures/" in href and not any(x in href for x in ["/vacatures/ict", "/vacatures/beveiliging", "/vacatures/management"]):
                full_url = href if href.startswith("http") else f"https://www.werkenvoornederland.nl{href}"
                full_url = full_url.split("?")[0].split("#")[0]
                unique_links.add(full_url)
                
        time.sleep(0.5) # Netjes pauzeren
        
    print(f"Totaal {len(unique_links)} unieke kandidaat-vacatures verzameld uit de zoekresultaten.")
    return list(unique_links)

def check_vacancy_details(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Kon details van {url} niet ophalen: {e}")
        return None
        
    soup = BeautifulSoup(response.text, 'html.parser')
    page_text = soup.get_text()
    page_text_lower = page_text.lower()
    
    # 1. Check of het een van de doelorganisaties is
    is_target_org = any(org in page_text_lower or org in url.lower() for org in KEYWORDS_ORG)
    if not is_target_org:
        return None
        
    # 2. Check of het schaal 13 of 14 is
    match_13 = re.search(r"\bschaal\s*13\b", page_text_lower)
    match_14 = re.search(r"\bschaal\s*14\b", page_text_lower)
    
    if not (match_13 or match_14):
        return None
        
    scale = "Schaal 13" if match_13 else "Schaal 14"
    
    # 3. Extraheer titel en organisatie
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else url.split("/")[-1].replace("-", " ").title()
    
    detected_org = "Rijksoverheid (MIVD/AIVD/Defensie)"
    if "mivd" in page_text_lower or "militaire inlichtingen" in page_text_lower:
        detected_org = "MIVD"
    elif "aivd" in page_text_lower or "algemene inlichtingen" in page_text_lower:
        detected_org = "AIVD"
    elif "defensie" in page_text_lower:
        detected_org = "Ministerie van Defensie"
        
    return {
        "title": title,
        "org": f"{detected_org} ({scale})",
        "link": url
    }

def main():
    # 1. Laad reeds bekende vacatures
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            known_ids = set(json.load(f))
    else:
        known_ids = set()
        
    # 2. Verzamel unieke links uit de specifieke zoekopdrachten
    candidate_links = get_unique_vacancy_links()
    
    # 3. Controleer elke vacature op details
    matching_vacancies = []
    print("Details controleren per kandidaat-vacature...")
    for idx, link in enumerate(candidate_links, 1):
        print(f" [{idx}/{len(candidate_links)}] Controleren: {link}")
        vac_details = check_vacancy_details(link)
        if vac_details:
            print(f"   🎯 MATCH GEVONDEN: {vac_details['title']} ({vac_details['org']})")
            matching_vacancies.append(vac_details)
        time.sleep(0.5) # Netjes pauzeren
        
    new_vacancies = []
    
    # 4. Identificeer nieuwe matches
    for vac in matching_vacancies:
        vac_id = vac["link"]
        if vac_id not in known_ids:
            new_vacancies.append(vac)
            known_ids.add(vac_id)
            
    # 5. Verstuur notificaties voor nieuwe vacatures
    if new_vacancies:
        for vac in new_vacancies:
            msg = f"🔔 *Nieuwe Overheidsvacature Hoge Schaal!*\n\n" \
                  f"📌 *Functie:* {vac['title']}\n" \
                  f"🏢 *Organisatie:* {vac['org']}\n\n" \
                  f"🔗 [Bekijk vacature op Werken voor Nederland]({vac['link']})"
            send_telegram_message(msg)
            
        # Sla geüpdatete lijst op
        with open(DATA_FILE, "w") as f:
            json.dump(list(known_ids), f, indent=4)
        print(f"{len(new_vacancies)} nieuwe vacatures gemeld.")
    else:
        print("Geen nieuwe matching vacatures gevonden.")

if __name__ == "__main__":
    main()

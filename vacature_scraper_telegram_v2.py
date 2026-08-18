import requests
from bs4 import BeautifulSoup
import json
import os

# CONFIGURATIE
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "bekende_vacatures.json"

# Doelorganisaties en schalen
KEYWORDS_ORG = ["defensie", "mivd", "aivd", "algemene inlichtingen", "militaire inlichtingen"]
TARGET_SCALES = ["schaal 13", "schaal 14", "13", "14"]

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram niet geconfigureerd. Bericht:")
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

def scrape_vacancies():
    # Basis URL voor Werken voor Nederland
    search_url = "https://www.werkenvoornederland.nl/vacatures"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Fout bij ophalen website: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    vacancies = []
    
    # WerkenvoorNederland gebruikt specifieke klassen voor vacaturekaarten
    cards = soup.find_all("div", class_="vacancy-card")
    
    # Fallback/handmatige selectie en filtering op schaal/organisatie in de tekst:
    for card in cards:
        title_elem = card.find("h3")
        title = title_elem.get_text(strip=True) if title_elem else ""
        
        link_elem = card.find("a")
        link = link_elem["href"] if link_elem and "href" in link_elem.attrs else ""
        
        org_elem = card.find("span", class_="vacancy-card__organisation")
        org = org_elem.get_text(strip=True) if org_elem else ""
        
        meta = card.get_text().lower()
        
        # Filter logica
        is_target_org = any(k in org.lower() or k in title.lower() for k in KEYWORDS_ORG)
        is_target_scale = any(s in meta for s in TARGET_SCALES)
        
        if is_target_org and is_target_scale:
            vac_link = f"https://www.werkenvoornederland.nl{link}" if not link.startswith("http") else link
            vacancies.append({
                "title": title,
                "org": org,
                "link": vac_link
            })
            
    return vacancies

def main():
    # 1. Laad reeds bekende vacatures om duplicaten te voorkomen
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            known_ids = set(json.load(f))
    else:
        known_ids = set()
        
    # 2. Scrape actuele vacatures
    found_vacancies = scrape_vacancies()
    new_vacancies = []
    
    # 3. Identificeer nieuwe matches
    for vac in found_vacancies:
        vac_id = vac["link"] # Gebruik URL als unieke ID
        if vac_id not in known_ids:
            new_vacancies.append(vac)
            known_ids.add(vac_id)
            
    # 4. Verstuur notificaties voor nieuwe vacatures
    if new_vacancies:
        for vac in new_vacancies:
            msg = f"🔔 *Nieuwe Overheidsvacature!*\n\n" \
                  f"📌 *Functie:* {vac['title']}\n" \
                  f"🏢 *Organisatie:* {vac['org']}\n\n" \
                  f"🔗 [Bekijk vacature op Werken voor Nederland]({vac['link']})"
            send_telegram_message(msg)
            
        # Sla geüpdatete lijst op
        with open(DATA_FILE, "w") as f:
            json.dump(list(known_ids), f, indent=4)
        print(f"{len(new_vacancies)} nieuwe vacatures gemeld.")
    else:
        print("Geen nieuwe vacatures gevonden die nog niet gemeld waren.")

if __name__ == "__main__":
    main()

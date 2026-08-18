import requests
from bs4 import BeautifulSoup
import json
import os
import re
import sys

# CONFIGURATIE
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "bekende_vacatures.json"

# Doelorganisaties en schalen
KEYWORDS_ORG = ["defensie", "mivd", "aivd", "algemene inlichtingen", "militaire inlichtingen", "binnenlandse zaken", "justitie", "jenv"]
TARGET_SCALES = ["schaal 13", "schaal 14", "schaal-13", "schaal-14", "salarisschaal 13", "salarisschaal 14"]

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
        print("Telegram-bericht succesvol verzonden.")
    except Exception as e:
        print(f"Fout bij verzenden Telegram: {e}")

def scrape_vacancies():
    # Basis URL voor Werken voor Nederland
    search_url = "https://www.werkenvoornederland.nl/vacatures"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    print(f"Start met ophalen van: {search_url}")
    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        error_msg = f"❌ *Scraper Fout*\nKon de website van Werken voor Nederland niet bereiken: {e}"
        send_telegram_message(error_msg)
        sys.exit(f"Fout bij ophalen website: {e}")

    soup = BeautifulSoup(response.text, 'html.parser')
    all_found_vacancies = []

    # --- METHODE 1: JSON-LD (Meest betrouwbaar voor Google Jobs SEO, overleeft JS-rendering) ---
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            # Normaliseer naar lijst
            items = []
            if isinstance(data, dict):
                if data.get("@type") == "JobPosting":
                    items.append(data)
                elif data.get("@type") == "ItemList" and "itemListElement" in data:
                    for element in data["itemListElement"]:
                        if isinstance(element, dict):
                            job = element.get("item") if "item" in element else element
                            if isinstance(job, dict) and job.get("@type") == "JobPosting":
                                items.append(job)
            elif isinstance(data, list):
                items = [x for x in data if isinstance(x, dict) and x.get("@type") == "JobPosting"]

            for item in items:
                title = item.get("title", "")
                org = item.get("hiringOrganization", {}).get("name", "") if isinstance(item.get("hiringOrganization"), dict) else ""
                link = item.get("url", "")
                desc = item.get("description", "")
                
                # Sla op voor filtering
                all_found_vacancies.append({
                    "title": title,
                    "org": org,
                    "link": link,
                    "full_text": f"{title} {org} {desc}".lower()
                })
        except Exception as e:
            continue

    # --- METHODE 2: Traditionele HTML kaarten (Fallback) ---
    card_selectors = [
        ("div", "vacancy-card"),
        ("a", "vacancy-card"),
        ("div", "card"),
        ("li", "vacancy-item"),
        ("div", "search-result")
    ]
    
    html_cards_found = 0
    for tag, class_name in card_selectors:
        cards = soup.find_all(tag, class_=class_name)
        if cards:
            html_cards_found = len(cards)
            print(f"HTML-kaarten gevonden met selector '{tag}.{class_name}': {html_cards_found}")
            for card in cards:
                title_elem = card.find(["h3", "h2", "div"], class_=re.compile(r"title|header")) or card.find(["h3", "h2"])
                title = title_elem.get_text(strip=True) if title_elem else ""
                
                link_elem = card.find("a") or (card if card.name == "a" else None)
                link = link_elem["href"] if link_elem and "href" in link_elem.attrs else ""
                
                org_elem = card.find(class_=re.compile(r"org|organisation|meta"))
                org = org_elem.get_text(strip=True) if org_elem else ""
                
                meta_text = card.get_text().lower()
                
                if title or link:
                    vac_link = f"https://www.werkenvoornederland.nl{link}" if link and not link.startswith("http") else link
                    all_found_vacancies.append({
                        "title": title,
                        "org": org,
                        "link": vac_link,
                        "full_text": f"{title} {org} {meta_text}".lower()
                    })
            break

    # --- METHODE 3: Generieke Links (Uiterste Fallback) ---
    if not all_found_vacancies:
        print("Geen gestructureerde kaarten of JSON-LD gevonden. Scannen op generieke vacature-links...")
        for link_elem in soup.find_all("a", href=re.compile(r"/vacature/")):
            title = link_elem.get_text(strip=True)
            link = link_elem["href"]
            if title and link:
                vac_link = f"https://www.werkenvoornederland.nl{link}" if not link.startswith("http") else link
                all_found_vacancies.append({
                    "title": title,
                    "org": "",
                    "link": vac_link,
                    "full_text": title.lower()
                })

    # --- DIAGNOSTIEK ---
    total_found = len(all_found_vacancies)
    print(f"Totaal aantal vacatures gedetecteerd op pagina: {total_found}")
    
    if total_found == 0:
        warning_msg = (
            "⚠️ *Scraper Waarschuwing*\n"
            "Er zijn *0 vacatures* gedetecteerd op de pagina.\n"
            "Waarschijnlijk heeft Werken voor Nederland de paginastructuur gewijzigd of blokkeert een Cloudflare-scherm de scraper.\n\n"
            "Controleer de logs van je GitHub Action voor meer technische details."
        )
        send_telegram_message(warning_msg)
        print("DIAGNOSTISCHE INFO:")
        print(f"Pagina-lengte: {len(response.text)} karakters")
        print(f"Eerste 500 karakters: {response.text[:500]}")
        return []

    # --- FILTERING ---
    matched_vacancies = []
    for vac in all_found_vacancies:
        # Check organisatie (moet defensie/aivd/mivd o.i.d. bevatten)
        is_target_org = any(k in vac["full_text"] for k in KEYWORDS_ORG)
        # Check salarisschaal (moet schaal 13 of 14 bevatten)
        is_target_scale = any(s in vac["full_text"] for s in TARGET_SCALES)
        
        # Extra controle voor directe schaal-getallen los in de tekst (bijv. "schaal 13" of "schaal 14")
        if not is_target_scale:
            scale_match = re.search(r"schaal\s*(?:colon|:)?\s*(13|14)\b", vac["full_text"])
            if scale_match:
                is_target_scale = True

        if is_target_org and is_target_scale:
            matched_vacancies.append(vac)

    print(f"Aantal vacatures na filtering (schaal 13/14 + Defensie/AIVD/MIVD): {len(matched_vacancies)}")
    return matched_vacancies

def main():
    # 1. Laad reeds bekende vacatures om duplicaten te voorkomen
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                known_ids = set(json.load(f))
        except Exception as e:
            print(f"Fout bij laden database, we starten met een lege database: {e}")
            known_ids = set()
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
            msg = f"🔔 *Nieuwe Overheidsvacature Hoge Schaal!*\n\n" \
                  f"📌 *Functie:* {vac['title']}\n" \
                  f"🏢 *Organisatie:* {vac['org'] if vac['org'] else 'Onbekend (zie link)'}\n\n" \
                  f"🔗 [Bekijk vacature op Werken voor Nederland]({vac['link']})"
            send_telegram_message(msg)
            
        # Sla geüpdatete lijst op
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(list(known_ids), f, indent=4)
            print(f"{len(new_vacancies)} nieuwe vacatures opgeslagen in database.")
        except Exception as e:
            print(f"Fout bij opslaan database: {e}")
    else:
        print("Geen nieuwe matching vacatures gevonden.")

if __name__ == "__main__":
    main()

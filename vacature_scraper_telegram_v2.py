import requests
from bs4 import BeautifulSoup
import json
import os
import re

# CONFIGURATIE
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "bekende_vacatures.json"

# Doelorganisaties en schalen
KEYWORDS_ORG = ["defensie", "mivd", "aivd", "binnenlandse zaken", "bzk", "veiligheidsdienst", "inlichtingen"]
TARGET_SCALES = ["schaal 13", "schaal 14", "schaal13", "schaal14", "13", "14"]

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

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def scrape_vacancies():
    # We scannen zowel de hoofd-vacaturepagina als de specifieke ICT/Veiligheid paginas voor maximale vindbaarheid
    urls_to_scan = [
        "https://www.werkenvoornederland.nl/vacatures",
        "https://www.werkenvoornederland.nl/vacatures/ict",
        "https://www.werkenvoornederland.nl/vacatures?vakgebied=Orde/vrede/veiligheid"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    all_vacancies = []
    seen_links = set()
    
    for search_url in urls_to_scan:
        print(f"Start met ophalen van: {search_url}")
        try:
            response = requests.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print(f"Fout bij ophalen {search_url}: {e}")
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Strategy 1: Google Jobs / JSON-LD structured data extraction
        print("Proberen vacatures te vinden via gestructureerde JSON-LD data...")
        json_scripts = soup.find_all("script", type="application/ld+json")
        for js in json_scripts:
            try:
                data = json.loads(js.string)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    if "@graph" in data:
                        items = data["@graph"]
                    elif data.get("@type") == "JobPosting":
                        items = [data]
                
                for item in items:
                    if item.get("@type") == "JobPosting":
                        title = item.get("title", "")
                        link = item.get("url", "")
                        org_info = item.get("hiringOrganization", {})
                        org = org_info.get("name", "") if isinstance(org_info, dict) else str(org_info)
                        desc = item.get("description", "").lower()
                        
                        is_target_org = any(k in org.lower() or k in title.lower() for k in KEYWORDS_ORG)
                        is_target_scale = any(s in desc or s in title.lower() for s in TARGET_SCALES)
                        
                        if is_target_org and is_target_scale and link:
                            if link not in seen_links:
                                seen_links.add(link)
                                all_vacancies.append({
                                    "title": clean_text(title),
                                    "org": clean_text(org),
                                    "link": link
                                })
            except Exception as e:
                print(f"Fout bij parsen JSON-LD: {e}")

        # Strategy 2: Nuxt/Next/Webpack hydration state extraction
        print("Proberen vacatures te vinden in Nuxt/Next hydration state...")
        for script in soup.find_all("script"):
            script_text = script.string if script.string else ""
            if "__NUXT__" in script_text or "__NEXT_DATA__" in script_text or "pageData" in script_text:
                links = re.findall(r'/vacatures/[a-zA-Z0-9-]+-[A-Z]+-\d{4}-\d+', script_text)
                for rel_link in links:
                    full_link = f"https://www.werkenvoornederland.nl{rel_link}"
                    if full_link not in seen_links:
                        slug = rel_link.split("/")[-1]
                        parts = slug.split("-")
                        title_parts = parts[:-3]
                        guessed_title = " ".join(title_parts).capitalize()
                        guessed_org = parts[-3]
                        
                        is_target_org = any(k in guessed_org.lower() or k in guessed_title.lower() for k in KEYWORDS_ORG)
                        if is_target_org:
                            seen_links.add(full_link)
                            all_vacancies.append({
                                "title": guessed_title,
                                "org": f"Overheidsorganisatie ({guessed_org.upper()})",
                                "link": full_link
                            })

        # Strategy 3: Parent-Container Link Scanning (The Bulletproof Regex Method)
        print("Proberen vacatures te vinden via slimme HTML-link scanning...")
        vacancy_url_pattern = re.compile(r'/vacatures/[a-zA-Z0-9-]+-[A-Z]+-\d{4}-\d+')
        
        all_links = soup.find_all("a", href=True)
        for link_elem in all_links:
            href = link_elem["href"]
            if vacancy_url_pattern.search(href) or ("/vacatures/" in href and any(str(year) in href for year in [2025, 2026, 2027])):
                full_link = f"https://www.werkenvoornederland.nl{href}" if href.startswith("/") else href
                
                if full_link in seen_links:
                    continue
                
                title = clean_text(link_elem.get_text())
                if not title or len(title) < 5:
                    title = link_elem.get("title", "")
                    if not title and link_elem.find_parent():
                        h_elem = link_elem.find_parent().find(["h2", "h3", "h4"])
                        if h_elem:
                            title = h_elem.get_text()
                
                parent = link_elem.find_parent()
                context_text = ""
                org = "Rijksoverheid"
                
                for _ in range(5):
                    if not parent:
                        break
                    parent_text = parent.get_text().lower()
                    if len(parent_text) > len(context_text):
                        context_text = parent_text
                        for keyword in ["ministerie van defensie", "defensie", "mivd", "aivd", "binnenlandse zaken", "bzk", "justitie en veiligheid", "jenv"]:
                            if keyword in parent_text:
                                org = keyword.title()
                                break
                    parent = parent.find_parent()
                
                meta_lower = f"{title.lower()} {org.lower()} {context_text}"
                is_target_org = any(k in meta_lower for k in KEYWORDS_ORG)
                is_target_scale = any(s in meta_lower for s in TARGET_SCALES)
                
                if is_target_org and is_target_scale and title:
                    seen_links.add(full_link)
                    all_vacancies.append({
                        "title": clean_text(title),
                        "org": clean_text(org),
                        "link": full_link
                    })

    print(f"Diagnostische info: Totaal aantal unieke gefilterde vacatures gevonden: {len(all_vacancies)}")
    return all_vacancies

def main():
    print("--- STARTING VACANCY AGENT SCRAPER ---")
    
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                known_ids = set(json.load(f))
        except Exception as e:
            print(f"Fout bij laden van {DATA_FILE}: {e}")
            known_ids = set()
    else:
        known_ids = set()
        
    found_vacancies = scrape_vacancies()
    new_vacancies = []
    
    for vac in found_vacancies:
        vac_id = vac["link"]
        if vac_id not in known_ids:
            new_vacancies.append(vac)
            known_ids.add(vac_id)
            
    if new_vacancies:
        print(f"Matches gevonden! Meldingen versturen voor {len(new_vacancies)} vacatures.")
        for vac in new_vacancies:
            msg = f"🔔 *Nieuwe Overheidsvacature!*\n\n" \
                  f"📌 *Functie:* {vac['title']}\n" \
                  f"🏢 *Organisatie:* {vac['org']}\n\n" \
                  f"🔗 [Bekijk vacature op Werken voor Nederland]({vac['link']})"
            send_telegram_message(msg)
            
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(list(known_ids), f, indent=4)
            print("Database succesvol bijgewerkt.")
        except Exception as e:
            print(f"Fout bij opslaan database: {e}")
    else:
        print("Geen nieuwe matches gevonden die voldoen aan schaal 13/14 bij Defensie/AIVD/MIVD.")

if __name__ == "__main__":
    main()

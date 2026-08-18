import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time

# CONFIGURATIE
DATA_FILE = "bekende_vacatures.json"

# Doelorganisaties en trefwoorden om op te zoeken en te filteren
KEYWORDS_ORG = ["defensie", "mivd", "aivd", "algemene inlichtingen", "militaire inlichtingen", "jscu", "jdeu"]

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
                
        time.sleep(0.5)
        
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
    
    is_target_org = any(org in page_text_lower or org in url.lower() for org in KEYWORDS_ORG)
    if not is_target_org:
        return None
        
    match_13 = re.search(r"\bschaal\s*13\b", page_text_lower)
    match_14 = re.search(r"\bschaal\s*14\b", page_text_lower)
    
    if not (match_13 or match_14):
        return None
        
    scale = "Schaal 13" if match_13 else "Schaal 14"
    
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
    print("=== START DATABASE SEEDING (NULMETING) ===")
    
    # 1. Verzamel alle unieke links
    candidate_links = get_unique_vacancy_links()
    
    # 2. Controleer elke vacature op details
    matching_vacancies = []
    print("\nDetails controleren per kandidaat-vacature (dit kan even duren)...")
    for idx, link in enumerate(candidate_links, 1):
        print(f" [{idx}/{len(candidate_links)}] Controleren: {link}")
        vac_details = check_vacancy_details(link)
        if vac_details:
            print(f"   🎯 MATCH GEVONDEN: {vac_details['title']} ({vac_details['org']})")
            matching_vacancies.append(vac_details)
        time.sleep(0.5)
        
    if not matching_vacancies:
        print("\n⚠️ Er zijn momenteel geen actieve Schaal 13/14 vacatures gevonden bij Defensie, MIVD of AIVD.")
        print("We maken een lege database aan.")
        with open(DATA_FILE, "w") as f:
            json.dump([], f, indent=4)
        return

    # Toon de gevonden vacatures in de console
    print(f"\n✅ Succes! Er zijn {len(matching_vacancies)} actieve match(es) gevonden op de website:")
    known_links = []
    for i, vac in enumerate(matching_vacancies, 1):
        print(f"  {i}. [{vac['org']}] {vac['title']}")
        print(f"     Link: {vac['link']}")
        known_links.append(vac["link"])
        
    # Schrijf deze direct weg naar het JSON-bestand
    with open(DATA_FILE, "w") as f:
        json.dump(known_links, f, indent=4)
        
    print(f"\n💾 Database '{DATA_FILE}' is succesvol gevuld met deze {len(matching_vacancies)} vacatures.")
    print("Vanaf nu stuurt je wekelijkse scraper ALLEEN nog berichten als er een gloednieuwe vacature verschijnt!")

if __name__ == "__main__":
    main()

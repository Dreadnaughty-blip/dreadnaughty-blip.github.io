import os
import json
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup

# --- CONFIGURATIE VIA GITHUB SECRETS (ENVIRONMENT VARIABLES) ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")  # Gebruik een App-wachtwoord bij Gmail/Outlook!
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

DATA_FILE = "bekende_vacatures.json"

# Doelcriteria
TARGET_ORGANISATIONS = [
    "defensie", "mivd", "aivd", 
    "algemene inlichtingen", "militaire inlichtingen", 
    "binnenlandse zaken"
]
TARGET_SCALES = ["schaal 13", "schaal 14", "13", "14"]

def send_notification_email(new_vacancies):
    """Verstuurt een geconsolideerde HTML-e-mail met de nieuwe vacatures."""
    if not SENDER_EMAIL or not SENDER_PASSWORD or not RECIPIENT_EMAIL:
        print("WAARSCHUWING: E-mailinstellingen ontbreken in de omgevingsvariabelen.")
        print("Nieuwe vacatures die gemeld zouden worden:")
        for v in new_vacancies:
            print(f"- {v['title']} ({v['org']}) -> {v['url']}")
        return

    subject = f"🔔 {len(new_vacancies)} Nieuwe Schaal 13/14 Vacature(s) Gevonden!"
    
    # HTML Body bouwen
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #dddddd; border-radius: 8px;">
            <h2 style="color: #004494; border-bottom: 2px solid #004494; padding-bottom: 10px;">
                WerkenvoorNederland.nl Monitor
            </h2>
            <p>Beste Bob,</p>
            <p>Er zijn <strong>{len(new_vacancies)} nieuwe vacature(s)</strong> gevonden bij jouw doelorganisaties op Schaal 13 of 14:</p>
            <hr style="border: 0; border-top: 1px solid #eeeeee; margin: 20px 0;">
    """
    
    for vac in new_vacancies:
        html_content += f"""
            <div style="margin-bottom: 20px; padding: 15px; background-color: #f9f9f9; border-left: 4px solid #004494; border-radius: 4px;">
                <h3 style="margin-top: 0; color: #333333;">{vac['title']}</h3>
                <p style="margin: 5px 0;"><strong>Organisatie:</strong> {vac['org']}</p>
                <p style="margin: 5px 0;"><strong>Indicatie:</strong> {vac['meta_info']}</p>
                <p style="margin: 15px 0 0 0;">
                    <a href="{vac['url']}" style="background-color: #004494; color: #ffffff; padding: 8px 15px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">
                        Bekijk vacature →
                    </a>
                </p>
            </div>
        """
        
    html_content += """
            <hr style="border: 0; border-top: 1px solid #eeeeee; margin: 20px 0;">
            <p style="font-size: 12px; color: #777777;">
                Dit is een automatische melding gegenereerd door jouw persoonlijke GitHub Scraper Agent.
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Scraper Agent <{SENDER_EMAIL}>"
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        print(f"E-mail succesvol verzonden naar {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"Fout bij het verzenden van e-mail: {e}")

def scrape_vacancies():
    """Scraapt de vacaturepagina en filtert op basis van doelorganisaties en schalen."""
    # We gebruiken de zoekpagina met voor-gefilterde parameters om robuust te blijven
    # Zoeken naar Defensie en Binnenlandse Zaken vacatures direct vermindert ruis
    url = "https://www.werkenvoornederland.nl/vacatures"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Fout bij ophalen van vacatures van {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    found_vacancies = []

    # WerkenvoorNederland gebruikt specifieke zoekresultaat-kaarten (meestal anchors of div's met specifieke attributen)
    # We zoeken breed naar alle links die naar een specifieke vacature verwijzen
    links = soup.find_all("a", href=True)
    
    for link in links:
        href = link["href"]
        if "/vacatures/" in href and not href.endswith("/vacatures"):
            full_url = href if href.startswith("http") else f"https://www.werkenvoornederland.nl{href}"
            
            # Vind de omliggende kaart/container om de tekst (organisatie, schaal) te analyseren
            container = link.find_parent(["div", "article", "li"])
            container_text = container.get_text() if container else link.get_text()
            
            normalized_text = container_text.lower()
            
            # Filter logica:
            # 1. Behoort de vacature tot de gezochte organisaties?
            is_target_org = any(org in normalized_text for org in TARGET_ORGANISATIONS)
            
            # 2. Betreft het Schaal 13 of 14?
            # We zoeken naar "schaal 13", "schaal 14" of losse getallen 13/14 in salariscontext
            has_target_scale = False
            for scale in TARGET_SCALES:
                if scale in normalized_text:
                    # Voorkom false positives (bijvoorbeeld "13e maand" of "binnen 14 dagen")
                    if "schaal" in normalized_text or "bbra" in normalized_text:
                        has_target_scale = True
                        break
                    # Alternatief: controleer met een reguliere expressie op salarisschalen
                    if re.search(r'\b(schaal\s+)?(13|14)\b', normalized_text):
                        has_target_scale = True
                        break
            
            if is_target_org and has_target_scale:
                # Probeer de titel en organisatie netjes te extraheren
                title = "Onbekende Functie"
                org_name = "Onbekende Organisatie"
                
                if container:
                    # Vaak zit de titel in een h2 of h3 kop
                    headings = container.find_all(["h2", "h3", "h4"])
                    if headings:
                        title = headings[0].get_text(strip=True)
                    
                    # Probeer organisatie-informatie te isoleren
                    # WerkenvoorNederland toont vaak de organisatie net boven of onder de titel
                    meta_spans = container.find_all("span")
                    for span in meta_spans:
                        span_text = span.get_text(strip=True)
                        if any(o in span_text.lower() for o in TARGET_ORGANISATIONS):
                            org_name = span_text
                            break
                
                # Fallbacks
                if title == "Onbekende Functie" or len(title) < 5:
                    title = link.get_text(strip=True) or "Beleidsadviseur / Manager"
                
                found_vacancies.append({
                    "title": title,
                    "org": org_name if org_name != "Onbekende Organisatie" else "Ministerie van Defensie / BZK / AIVD",
                    "url": full_url,
                    "meta_info": "Schaal 13 / 14 Match"
                })

    # Dedupliceren op basis van URL
    unique_vacancies = {v["url"]: v for v in found_vacancies}.values()
    return list(unique_vacancies)

def main():
    # 1. Laad reeds bekende vacatures (state)
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                known_urls = set(json.load(f))
        except Exception as e:
            print(f"Kon {DATA_FILE} niet correct lezen, starten met lege staat: {e}")
            known_urls = set()
    else:
        known_urls = set()

    print(f"Bekende vacatures ingeladen: {len(known_urls)}")

    # 2. Scraap actuele vacatures
    current_vacancies = scrape_vacancies()
    print(f"Totaal aantal schaal 13/14 matches op de pagina gevonden: {len(current_vacancies)}")

    # 3. Filter op nieuwe vacatures
    new_vacancies = []
    for vac in current_vacancies:
        if vac["url"] not in known_urls:
            new_vacancies.append(vac)
            known_urls.add(vac["url"])

    # 4. Actie ondernemen bij nieuwe vondsten
    if new_vacancies:
        print(f"Nieuwe vacatures gevonden: {len(new_vacancies)}! Verzenden van e-mail notificatie...")
        send_notification_email(new_vacancies)
        
        # Sla de nieuwe status direct op
        with open(DATA_FILE, "w") as f:
            json.dump(list(known_urls), f, indent=4)
        print("Status succesvol bijgewerkt.")
    else:
        print("Geen nieuwe vacatures gevonden.")

if __name__ == "__main__":
    main()

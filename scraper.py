import json
import os
import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta

# 1. Laad externe configuratie
CONFIG_FILE = "config.json"

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

CPV_CODES = set(config.get("strategische_cpv_codes", []))
POSITIEVE_KEYWORDS = [k.lower() for k in config.get("positieve_keywords", [])]
NEGATIEVE_KEYWORDS = [k.lower() for k in config.get("negatieve_keywords", [])]
MANTEL_ROUTES = config.get("mantel_inkooproutes", {})
LEAD_TIME_MONTHS = config.get("instellingen", {}).get("voorbereidingstijd_overheid_maanden", 9)
DEFAULT_DURATION = config.get("instellingen", {}).get("standaard_looptijd_maanden", 48)

def fetch_tenderned_publicaties():
    """Haalt recente openbare publicaties op via TenderNed Open Data endpoint."""
    url = "https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page=0&size=100"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json().get("content", [])
    except Exception as e:
        print(f"Fout bij ophalen TenderNed data: {e}")
    return []

def kwalificeer_tender(item):
    """Controleert op basis van config.json of tender aansluit op de strategie."""
    titel = str(item.get("titel", "")).lower()
    beschrijving = str(item.get("beschrijving", "")).lower()
    volledige_tekst = f"{titel} {beschrijving}"

    # Exclusiefilter: Bevat uitvoerende trefwoorden?
    if any(neg in volledige_tekst for neg in NEGATIEVE_KEYWORDS):
        return False, "Bevat uitsluitingscriteria (uitvoerend)"

    # Inclusiefilter: Bevat strategische trefwoorden?
    if any(pos in volledige_tekst for pos in POSITIEVE_KEYWORDS):
        return True, "Strategische fit"

    return False, "Geen strategische overlap"

def match_inkooproute(aanbestedende_dienst):
    """Koppelt de klant aan de geconfigureerde mantel- en brokerroute."""
    dienst_str = str(aanbestedende_dienst).lower()
    for sleutel, route in MANTEL_ROUTES.items():
        if sleutel.lower() in dienst_str:
            return route
    return "Geen bestaande mantel — Consortium / Vrije inschrijving"

def bereken_tijdlijn(publicatie_datum_str):
    """Berekent einddatum en Eraneos actiedatum."""
    try:
        start_dt = datetime.strptime(publicatie_datum_str[:10], "%Y-%m-%d")
    except Exception:
        start_dt = datetime.now()

    eind_dt = start_dt + relativedelta(months=DEFAULT_DURATION)
    actie_dt = eind_dt - relativedelta(months=LEAD_TIME_MONTHS)
    nu = datetime.now()

    if nu >= eind_dt:
        status = "Verlopen / Heraanbesteding loopt"
        badge_class = "badge-danger"
    elif nu >= actie_dt:
        status = "URGENT: Voorbereiding gaande"
        badge_class = "badge-danger"
    elif (actie_dt - nu).days <= 180:
        status = "Actie vereist binnen 6 mnd"
        badge_class = "badge-warning"
    else:
        status = "Lopend (Monitoring)"
        badge_class = "badge-success"

    return eind_dt.strftime("%Y-%m-%d"), actie_dt.strftime("%Y-%m-%d"), status, badge_class

def genereer_dashboard(leads):
    """Genereert een responsive index.html pagina."""
    nu_str = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    rijen_html = ""
    for lead in leads:
        rijen_html += f"""
        <tr>
            <td><strong>{lead['dienst']}</strong></td>
            <td>{lead['titel']}</td>
            <td>{lead['route']}</td>
            <td>{lead['startdatum']}</td>
            <td>{lead['einddatum']}</td>
            <td><strong>{lead['actiedatum']}</strong></td>
            <td><span class="badge {lead['badge_class']}">{lead['status']}</span></td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Eraneos Tender Strategy & Forecast Dashboard</title>
    <style>
        :root {{
            --primary: #1F4E78;
            --background: #f8fafc;
            --surface: #ffffff;
            --text: #1e293b;
            --border: #e2e8f0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 30px;
            background-color: var(--background);
            color: var(--text);
        }}
        .header {{
            margin-bottom: 25px;
        }}
        h1 {{
            color: var(--primary);
            margin: 0 0 8px 0;
        }}
        .subtitle {{
            color: #64748b;
            font-size: 0.95rem;
        }}
        .table-container {{
            background: var(--surface);
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            overflow-x: auto;
            border: 1px solid var(--border);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }}
        th {{
            background-color: var(--primary);
            color: white;
            padding: 14px 16px;
            font-weight: 600;
        }}
        td {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
        }}
        tr:hover {{
            background-color: #f1f5f9;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-danger {{ background-color: #fee2e2; color: #991b1b; }}
        .badge-warning {{ background-color: #fef3c7; color: #92400e; }}
        .badge-success {{ background-color: #dcfce7; color: #166534; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Eraneos Aanbestedingen & Heraanbesteding Forecast</h1>
        <div class="subtitle">Laatste pipeline run: {nu_str} | Gefilterd op IT-strategie, architectuur en Rijksmantels</div>
    </div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Aanbestedende Dienst</th>
                    <th>Aanbesteding / Tender</th>
                    <th>Inkooproute / Mantel</th>
                    <th>Startdatum</th>
                    <th>Verwachte Einddatum</th>
                    <th>Actiedatum Acquisitie</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {rijen_html if rijen_html else "<tr><td colspan='7'>Geen relevante strategische publicaties gevonden in de huidige feed.</td></tr>"}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

def main():
    publicaties = fetch_tenderned_publicaties()
    gekwalificeerde_leads = []

    for pub in publicaties:
        is_fit, reden = kwalificeer_tender(pub)
        if not is_fit:
            continue

        dienst = pub.get("aanbestedendeDienst", "Onbekend")
        titel = pub.get("titel", "Zonder titel")
        pub_datum = pub.get("publicatieDatum", datetime.now().strftime("%Y-%m-%d"))

        eind_dt, actie_dt, status, badge = bereken_tijdlijn(pub_datum)
        route = match_inkooproute(dienst)

        gekwalificeerde_leads.append({
            "dienst": dienst,
            "titel": titel,
            "route": route,
            "startdatum": pub_datum[:10],
            "einddatum": eind_dt,
            "actiedatum": actie_dt,
            "status": status,
            "badge_class": badge
        })

    # Sorteer op urgentie (dichtstbijzijnde actiedatum eerst)
    gekwalificeerde_leads.sort(key=lambda x: x["actiedatum"])
    genereer_dashboard(gekwalificeerde_leads)
    print(f"Succesvol verwerkt: {len(gekwalificeerde_leads)} gekwalificeerde leads.")

if __name__ == "__main__":
    main()
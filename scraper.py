import json
import os
import requests
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

# 1. Configuratie laden
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
    """Haalt de laatste 10.000 publicaties op (100 pagina's) met ingebouwde adempauze."""
    alle_publicaties = []
    headers = {"Accept": "application/json"}
    
    # We itereren door 100 pagina's (0 tot 99)
    for page in range(100):
        url = f"https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page={page}&size=100"
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json().get("content", [])
                alle_publicaties.extend(data)
                print(f"Pagina {page} succesvol binnengehaald ({len(data)} items).")
                
                # Een halve seconde wachten voorkomt een blokkade door de overheid
                time.sleep(0.5)
            else:
                print(f"Gestopt bij pagina {page} vanwege statuscode {response.status_code}")
                break
        except Exception as e:
            print(f"Fout bij ophalen TenderNed data pagina {page}: {e}")
            break
            
    return alle_publicaties

def kwalificeer_tender(item):
    titel = str(item.get("titel", "")).lower()
    beschrijving = str(item.get("beschrijving", "")).lower()
    volledige_tekst = f"{titel} {beschrijving}"

    if any(neg in volledige_tekst for neg in NEGATIEVE_KEYWORDS):
        return False, "Uitsluitingscriterium"

    if any(pos in volledige_tekst for pos in POSITIEVE_KEYWORDS):
        return True, "Strategische fit"

    return False, "Geen overlap"

def match_inkooproute(aanbestedende_dienst):
    dienst_str = str(aanbestedende_dienst).lower()
    for sleutel, route in MANTEL_ROUTES.items():
        if sleutel.lower() in dienst_str:
            return route
    return "Vrije inschrijving / Consortium vormen"

def bereken_tijdlijn(publicatie_datum_str):
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
        is_urgent = True
    elif nu >= actie_dt:
        status = "URGENT: Voorbereiding gaande"
        badge_class = "badge-danger"
        is_urgent = True
    elif (actie_dt - nu).days <= 180:
        status = "Actie binnen 6 mnd"
        badge_class = "badge-warning"
        is_urgent = False
    else:
        status = "Lopend"
        badge_class = "badge-success"
        is_urgent = False

    return eind_dt.strftime("%Y-%m-%d"), actie_dt.strftime("%Y-%m-%d"), status, badge_class, is_urgent

def genereer_microsite(leads):
    os.makedirs("tenderned", exist_ok=True)
    nu_str = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    totaal_leads = len(leads)
    urgent_count = sum(1 for l in leads if l["is_urgent"])
    directe_mantel_count = sum(1 for l in leads if "Directe" in l["route"])

    rijen_html = ""
    for lead in leads:
        rijen_html += f"""
        <tr class="tender-row">
            <td class="client-cell"><strong>{lead['dienst']}</strong></td>
            <td class="title-cell">{lead['titel']}</td>
            <td><span class="route-tag">{lead['route']}</span></td>
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
    <title>BobSVP TN Tender Pipeline & Forecast</title>
    <style>
        :root {{
            --primary: #0f172a;
            --accent: #2563eb;
            --bg: #f1f5f9;
            --card-bg: #ffffff;
            --text-main: #334155;
            --text-muted: #64748b;
            --border: #e2e8f0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 30px;
        }}
        .container {{
            max-width: 1250px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 25px;
            border-bottom: 2px solid var(--border);
            padding-bottom: 15px;
        }}
        h1 {{
            margin: 0;
            color: var(--primary);
            font-size: 1.6rem;
            letter-spacing: -0.5px;
        }}
        .timestamp {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}
        .kpi-card {{
            background: var(--card-bg);
            padding: 18px 20px;
            border-radius: 10px;
            border: 1px solid var(--border);
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }}
        .kpi-title {{
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            font-weight: 600;
        }}
        .kpi-value {{
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--primary);
            margin-top: 6px;
        }}
        .toolbar {{
            margin-bottom: 15px;
            display: flex;
            gap: 10px;
        }}
        .search-box {{
            flex: 1;
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 0.9rem;
            background: var(--card-bg);
        }}
        .table-card {{
            background: var(--card-bg);
            border-radius: 10px;
            border: 1px solid var(--border);
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.88rem;
        }}
        th {{
            background: #f8fafc;
            color: var(--text-muted);
            padding: 12px 16px;
            font-weight: 600;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
        }}
        tr:last-child td {{ border-bottom: none; }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-danger {{ background: #fee2e2; color: #991b1b; }}
        .badge-warning {{ background: #fef3c7; color: #92400e; }}
        .badge-success {{ background: #dcfce7; color: #166534; }}
        .route-tag {{
            font-size: 0.78rem;
            background: #e0f2fe;
            color: #0369a1;
            padding: 3px 8px;
            border-radius: 4px;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>BobSVP TN Tender Pipeline & Forecast</h1>
                <div class="timestamp">Laatste update: {nu_str}</div>
            </div>
            <a href="/" style="font-size: 0.85rem; color: var(--accent); text-decoration: none; font-weight: 500;">← Terug naar hoofdsite</a>
        </div>

        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Relevante Leads</div>
                <div class="kpi-value">{totaal_leads}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Directe Actie Vereist</div>
                <div class="kpi-value" style="color: #b91c1c;">{urgent_count}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Directe Mantels</div>
                <div class="kpi-value" style="color: #0369a1;">{directe_mantel_count}</div>
            </div>
        </div>

        <div class="toolbar">
            <input type="text" id="searchInput" class="search-box" placeholder="Filter op ministerie, broker, trefwoord..." onkeyup="filterTable()">
        </div>

        <div class="table-card">
            <table id="tenderTable">
                <thead>
                    <tr>
                        <th>Aanbestedende Dienst</th>
                        <th>Titel</th>
                        <th>Inkooproute</th>
                        <th>Startdatum</th>
                        <th>Verwachte Einddatum</th>
                        <th>Actiedatum Acquisitie</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rijen_html if rijen_html else "<tr><td colspan='7'>Geen items gevonden.</td></tr>"}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function filterTable() {{
            const input = document.getElementById("searchInput").value.toLowerCase();
            const rows = document.querySelectorAll("#tenderTable tbody tr.tender-row");
            
            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                row.style.display = text.includes(input) ? "" : "none";
            }});
        }}
    </script>
</body>
</html>
"""
    with open("tenderned/index.html", "w", encoding="utf-8") as f:
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

        eind_dt, actie_dt, status, badge, is_urgent = bereken_tijdlijn(pub_datum)
        route = match_inkooproute(dienst)

        gekwalificeerde_leads.append({
            "dienst": dienst,
            "titel": titel,
            "route": route,
            "startdatum": pub_datum[:10],
            "einddatum": eind_dt,
            "actiedatum": actie_dt,
            "status": status,
            "badge_class": badge,
            "is_urgent": is_urgent
        })

    gekwalificeerde_leads.sort(key=lambda x: x["actiedatum"])
    genereer_microsite(gekwalificeerde_leads)
    print(f"Microsite gegenereerd in tenderned/index.html ({len(gekwalificeerde_leads)} leads).")

if __name__ == "__main__":
    main()

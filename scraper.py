import json
import os
import requests
import time
import zoneinfo
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

# Nederlandse tijdzone instellen
TZ_NL = zoneinfo.ZoneInfo("Europe/Amsterdam")

def fetch_tenderned_publicaties():
    """Tijdmachine: Haalt tot ~8 jaar aan historie op door 2.000 pagina's te scrapen (200.000 items)."""
    alle_publicaties = []
    headers = {"Accept": "application/json"}
    
    for page in range(2000):
        url = f"https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page={page}&size=100"
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json().get("content", [])
                if not data:
                    break # Einde database bereikt
                
                alle_publicaties.extend(data)
                
                # Feedback voor in de GitHub log
                if page % 50 == 0:
                    print(f"Tijdmachine draait: Pagina {page} (Jaar ~{str(data[0].get('publicatieDatum'))[:4]})...")
                
                time.sleep(0.1) # Korte pauze om blokkades te voorkomen
            else:
                break
        except Exception as e:
            print(f"Fout bij ophalen TenderNed data pagina {page}: {e}")
            break
            
    return alle_publicaties

def kwalificeer_tender(item):
    volledige_tekst = json.dumps(item).lower()

    if any(neg in volledige_tekst for neg in NEGATIEVE_KEYWORDS):
        return False, "Uitsluitingscriterium"

    if any(pos in volledige_tekst for pos in POSITIEVE_KEYWORDS):
        return True, "Strategische fit"

    return False, "Geen overlap"

def vind_veld(data, verwachte_sleutels_delen):
    queue = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for k, v in current.items():
                k_lower = k.lower()
                if any(deel in k_lower for deel in verwachte_sleutels_delen):
                    if isinstance(v, str) and v.strip() and v.strip().lower() != "self":
                        return v.strip()
                    elif isinstance(v, (int, float)):
                        return str(v)
            
            for k, v in current.items():
                if not k.startswith('_') and isinstance(v, (dict, list)):
                    queue.append(v)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    queue.append(item)
    return None

def vind_titel(data):
    exacte_sleutels = ['opdrachtnaam', 'aanbestedingnaam', 'publicatienaam', 'benaming', 'titel', 'title', 'naamopdracht', 'projectnaam', 'omschrijving', 'korteomschrijving']
    queue = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for k, v in current.items():
                if k.lower() in exacte_sleutels:
                    if isinstance(v, str) and v.strip() and v.strip().lower() != "self":
                        return v.strip()
            
            for k, v in current.items():
                if k.lower() in ['aanbesteding', 'opdracht', 'tender', 'publicatie', 'aankondiging']:
                    if isinstance(v, dict):
                        for sub_k, sub_v in v.items():
                            if sub_k.lower() in ['naam', 'name', 'titel'] and isinstance(sub_v, str) and sub_v.strip() and sub_v.strip().lower() != 'self':
                                return sub_v.strip()

            for k, v in current.items():
                if not k.startswith('_') and isinstance(v, (dict, list)):
                    queue.append(v)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    queue.append(item)
    return "Zonder titel"

def match_inkooproute(aanbestedende_dienst):
    if not aanbestedende_dienst or aanbestedende_dienst == "Onbekend":
        return "Vrije inschrijving / Consortium vormen"
        
    dienst_str = str(aanbestedende_dienst).lower()
    for sleutel, route in MANTEL_ROUTES.items():
        if sleutel.lower() in dienst_str:
            return route
    return "Vrije inschrijving / Consortium vormen"

def bereken_tijdlijn(publicatie_datum_str, ruwe_data):
    # Probeer specifieke looptijd te vinden, anders default (48 mnd)
    looptijd_str = vind_veld(ruwe_data, ["looptijdinmaanden", "contractduration", "duration", "looptijd", "duur"])
    looptijd_maanden = DEFAULT_DURATION
    if looptijd_str:
        try: looptijd_maanden = int(float(looptijd_str))
        except: pass

    try:
        start_dt = datetime.strptime(str(publicatie_datum_str)[:10], "%Y-%m-%d")
    except Exception:
        start_dt = datetime.now(TZ_NL).replace(tzinfo=None)

    eind_dt = start_dt + relativedelta(months=looptijd_maanden)
    actie_dt = eind_dt - relativedelta(months=LEAD_TIME_MONTHS)
    
    # Gebruik Nederlandse tijd voor het vaststellen van 'nu'
    nu = datetime.now(TZ_NL).replace(tzinfo=None)

    # Bepaal de status en de sorteerprioriteit
    if actie_dt < (nu - relativedelta(months=18)):
        aandacht = "🔍 Check (Mogelijk 8jr looptijd)"
        badge_class = "badge-secondary"
        sort_score = 4
    elif actie_dt <= nu:
        aandacht = "🚨 NU ACTIE"
        badge_class = "badge-danger"
        sort_score = 1
    elif (actie_dt - nu).days <= 180:
        aandacht = "⚠️ Binnen 6 mnd"
        badge_class = "badge-warning"
        sort_score = 2
    else:
        aandacht = "✅ Lopend"
        badge_class = "badge-success"
        sort_score = 3

    return eind_dt.strftime("%Y-%m-%d"), actie_dt.strftime("%Y-%m-%d"), aandacht, badge_class, sort_score

def genereer_microsite(leads):
    os.makedirs("tenderned", exist_ok=True)
    nu_str = datetime.now(TZ_NL).strftime("%d-%m-%Y %H:%M")
    
    totaal_leads = len(leads)
    urgent_count = sum(1 for l in leads if l["sort_score"] == 1)
    directe_mantel_count = sum(1 for l in leads if "Directe" in l["route"])

    rijen_html = ""
    for lead in leads:
        rijen_html += f"""
        <tr class="tender-row">
            <td class="client-cell" style="max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{lead['dienst']}"><strong>{lead['dienst']}</strong></td>
            <td class="title-cell" style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{lead['titel']}">{lead['titel']}</td>
            <td><span class="route-tag">{lead['route']}</span></td>
            <td>{lead['startdatum']}</td>
            <td>{lead['einddatum']}</td>
            <td><strong>{lead['actiedatum']}</strong></td>
            <td><span class="badge {lead['badge_class']}">{lead['aandacht']}</span></td>
            <td><a href="{lead['link']}" target="_blank" class="btn-link">Bekijk</a></td>
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
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg); color: var(--text-main); margin: 0; padding: 30px; }}
        .container {{ max-width: 1500px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 25px; border-bottom: 2px solid var(--border); padding-bottom: 15px; }}
        h1 {{ margin: 0; color: var(--primary); font-size: 1.6rem; letter-spacing: -0.5px; }}
        .timestamp {{ font-size: 0.85rem; color: var(--text-muted); }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px; }}
        .kpi-card {{ background: var(--card-bg); padding: 18px 20px; border-radius: 10px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
        .kpi-title {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); font-weight: 600; }}
        .kpi-value {{ font-size: 1.8rem; font-weight: 700; color: var(--primary); margin-top: 6px; }}
        .toolbar {{ margin-bottom: 15px; display: flex; gap: 10px; }}
        .search-box {{ flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); font-size: 0.9rem; background: var(--card-bg); }}
        .table-card {{ background: var(--card-bg); border-radius: 10px; border: 1px solid var(--border); overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; table-layout: fixed; }}
        th {{ background: #f8fafc; color: var(--text-muted); padding: 12px 16px; font-weight: 600; border-bottom: 1px solid var(--border); }}
        td {{ padding: 14px 16px; border-bottom: 1px solid var(--border); }}
        tr:last-child td {{ border-bottom: none; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
        .badge-danger {{ background: #fee2e2; color: #991b1b; }}
        .badge-warning {{ background: #fef3c7; color: #92400e; }}
        .badge-success {{ background: #dcfce7; color: #166534; }}
        .badge-secondary {{ background: #e2e8f0; color: #475569; }}
        .route-tag {{ font-size: 0.78rem; background: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 4px; display: inline-block; line-height: 1.3; }}
        .btn-link {{ background-color: var(--accent); color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-size: 0.75rem; font-weight: 600; display: inline-block; transition: background-color 0.2s; white-space: nowrap; }}
        .btn-link:hover {{ background-color: #1d4ed8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>BobSVP TN Tender Pipeline & Forecast</h1>
                <div class="timestamp">Laatste update: {nu_str} (Lokale Tijd)</div>
            </div>
            <a href="/" style="font-size: 0.85rem; color: var(--accent); text-decoration: none; font-weight: 500;">← Terug naar hoofdsite</a>
        </div>

        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Totaal Gekwalificeerd</div>
                <div class="kpi-value">{totaal_leads}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Nu Actie / Voorbereiden</div>
                <div class="kpi-value" style="color: #b91c1c;">{urgent_count}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Via Directe Mantels</div>
                <div class="kpi-value" style="color: #0369a1;">{directe_mantel_count}</div>
            </div>
        </div>

        <div class="toolbar">
            <input type="text" id="searchInput" class="search-box" placeholder="Filter op ministerie, broker, titel of status..." onkeyup="filterTable()">
        </div>

        <div class="table-card">
            <table id="tenderTable">
                <thead>
                    <tr>
                        <th style="width: 15%;">Aanbestedende Dienst</th>
                        <th style="width: 25%;">Titel</th>
                        <th style="width: 15%;">Inkooproute / Mantel</th>
                        <th style="width: 8%;">Gepubliceerd</th>
                        <th style="width: 8%;">Einddatum</th>
                        <th style="width: 9%;">Acquisitie Start</th>
                        <th style="width: 15%;">Aandacht</th>
                        <th style="width: 5%;">Actie</th>
                    </tr>
                </thead>
                <tbody>
                    {rijen_html if rijen_html else "<tr><td colspan='8'>Geen items gevonden.</td></tr>"}
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

        dienst = vind_veld(pub, ["aanbestedendedienst", "organisatie", "opdrachtgever", "publicerendondernemer"]) or "Onbekend"
        titel = vind_titel(pub)
        pub_datum = vind_veld(pub, ["publicatiedatum", "datumpublicatie"]) or datetime.now(TZ_NL).strftime("%Y-%m-%d")
        
        # Stop extreem oude vervuiling (bijv data uit 2012)
        try:
            pub_jaar = int(str(pub_datum)[:4])
            if pub_jaar < 2016:
                continue
        except: pass
        
        pub_id = vind_veld(pub, ["publicatieid", "kenmerk", "uuid", "referentie"])
        link = f"https://www.tenderned.nl/aankondigingen/overzicht/{pub_id}" if pub_id else "https://www.tenderned.nl/"

        eind_dt, actie_dt, aandacht, badge, sort_score = bereken_tijdlijn(pub_datum, pub)
        route = match_inkooproute(dienst)

        gekwalificeerde_leads.append({
            "dienst": dienst.replace("\n", " ").strip(),
            "titel": titel.replace("\n", " ").strip(),
            "route": route,
            "startdatum": str(pub_datum)[:10],
            "einddatum": eind_dt,
            "actiedatum": actie_dt,
            "aandacht": aandacht,
            "badge_class": badge,
            "sort_score": sort_score,
            "link": link
        })

    # Magie zit hier: sorteer EERST op de categorie (score 1 tot 4), DAARNA op de datum
    gekwalificeerde_leads.sort(key=lambda x: (x["sort_score"], x["actiedatum"]))
    
    genereer_microsite(gekwalificeerde_leads)
    print(f"Microsite gegenereerd in tenderned/index.html ({len(gekwalificeerde_leads)} leads).")

if __name__ == "__main__":
    main()

import json
import os
import requests
import time
import zoneinfo
import re
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

TZ_NL = zoneinfo.ZoneInfo("Europe/Amsterdam")

def fetch_tenderned_publicaties():
    """Omzeilt de 10.000 limiet door de data per kwartaal vanaf 2017 op te halen."""
    alle_publicaties = []
    headers = {"Accept": "application/json"}
    
    huidig_jaar = datetime.now(TZ_NL).year
    
    for jaar in range(2017, huidig_jaar + 1):
        kwartalen = [
            (f"{jaar}-01-01", f"{jaar}-03-31"),
            (f"{jaar}-04-01", f"{jaar}-06-30"),
            (f"{jaar}-07-01", f"{jaar}-09-30"),
            (f"{jaar}-10-01", f"{jaar}-12-31")
        ]
        
        for start_dt, eind_dt in kwartalen:
            print(f"Tijdmachine: Scrapen van Q-periode {start_dt} t/m {eind_dt}...")
            
            for page in range(100): # Blijft veilig onder de 10k per kwartaal
                url = f"https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page={page}&size=100&publicatieDatumVanaf={start_dt}&publicatieDatumTot={eind_dt}"
                
                try:
                    response = requests.get(url, headers=headers, timeout=30)
                    if response.status_code == 200:
                        data = response.json().get("content", [])
                        if not data:
                            break # Einde van dit specifieke kwartaal bereikt
                        
                        alle_publicaties.extend(data)
                        time.sleep(0.1) # Korte pauze tegen blokkades
                    else:
                        break
                except Exception as e:
                    print(f"Fout bij kwartaal {start_dt} pagina {page}: {e}")
                    break
            
    return alle_publicaties

def kwalificeer_tender(item):
    volledige_tekst = json.dumps(item).lower()
    if any(neg in volledige_tekst for neg in NEGATIEVE_KEYWORDS): return False, "Uitsluitingscriterium"
    if any(pos in volledige_tekst for pos in POSITIEVE_KEYWORDS): return True, "Strategische fit"
    return False, "Geen overlap"

def vind_veld(data, verwachte_sleutels_delen):
    queue = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for k, v in current.items():
                k_lower = k.lower()
                if any(deel in k_lower for deel in verwachte_sleutels_delen):
                    if isinstance(v, str) and v.strip() and v.strip().lower() != "self": return v.strip()
                    elif isinstance(v, (int, float)): return str(v)
            for k, v in current.items():
                if not k.startswith('_') and isinstance(v, (dict, list)): queue.append(v)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)): queue.append(item)
    return None

def vind_titel(data):
    exacte_sleutels = ['opdrachtnaam', 'aanbestedingnaam', 'publicatienaam', 'benaming', 'titel', 'title', 'naamopdracht', 'projectnaam', 'omschrijving']
    queue = [data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for k, v in current.items():
                if k.lower() in exacte_sleutels:
                    if isinstance(v, str) and v.strip() and v.strip().lower() != "self": return v.strip()
            for k, v in current.items():
                if k.lower() in ['aanbesteding', 'opdracht', 'tender', 'publicatie', 'aankondiging']:
                    if isinstance(v, dict):
                        for sub_k, sub_v in v.items():
                            if sub_k.lower() in ['naam', 'name', 'titel'] and isinstance(sub_v, str) and sub_v.strip() and sub_v.strip().lower() != 'self': return sub_v.strip()
            for k, v in current.items():
                if not k.startswith('_') and isinstance(v, (dict, list)): queue.append(v)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)): queue.append(item)
    return "Zonder titel"

def bepaal_type_dienst(dienst_naam):
    naam = str(dienst_naam).lower()
    if "gemeente" in naam: return "Gemeente"
    if any(x in naam for x in ["ministerie", "rijk", "belastingdienst", "defensie", "politie"]): return "Rijksoverheid"
    if any(x in naam for x in ["omgevingsdienst", "rud "]): return "Omgevingsdienst"
    if any(x in naam for x in ["uwv", "svb", "kadaster", "cibg", "duo", "cbs", "rvo", "cbr", "cjib"]): return "Uitvoeringsorganisatie"
    if any(x in naam for x in ["stichting", "universiteit", "hogeschool", "college", "onderwijs", "scholengroep", "roc "]): return "Onderwijs"
    if "provincie" in naam: return "Provincie"
    if "waterschap" in naam or "hoogheemraadschap" in naam: return "Waterschap"
    if "ziekenhuis" in naam or "ggz" in naam or "zorg" in naam: return "Zorg"
    return "Overig"

def normaliseer_titel(titel):
    """Verwijdert jaartallen en stopwoorden om tenders netjes aan elkaar te koppelen (voor deduplicatie)"""
    t = str(titel).lower()
    t = re.sub(r'\b20\d{2}\b', '', t)
    for w in ['aanbesteding', 'europese', 'marktconsultatie', 'raamovereenkomst', 'nadere', 'overeenkomst', 'voor', 'inzake']:
        t = t.replace(w, '')
    return " ".join(t.split())

def match_inkooproute(aanbestedende_dienst):
    if not aanbestedende_dienst or aanbestedende_dienst == "Onbekend": return "Vrije inschrijving / Consortium"
    dienst_str = str(aanbestedende_dienst).lower()
    for sleutel, route in MANTEL_ROUTES.items():
        if sleutel.lower() in dienst_str: return route
    return "Vrije inschrijving / Consortium"

def bereken_tijdlijn(publicatie_datum_str, ruwe_data):
    looptijd_str = vind_veld(ruwe_data, ["looptijdinmaanden", "contractduration", "duration", "looptijd", "duur"])
    looptijd_maanden = DEFAULT_DURATION
    if looptijd_str:
        try: looptijd_maanden = int(float(looptijd_str))
        except: pass

    try: start_dt = datetime.strptime(str(publicatie_datum_str)[:10], "%Y-%m-%d")
    except: start_dt = datetime.now(TZ_NL).replace(tzinfo=None)

    eind_dt = start_dt + relativedelta(months=looptijd_maanden)
    actie_dt = eind_dt - relativedelta(months=LEAD_TIME_MONTHS)
    nu = datetime.now(TZ_NL).replace(tzinfo=None)

    # Filter: Als het contract langer dan 1 jaar geleden is afgelopen, verberg het.
    # Als een contract UIT 2018 NU (of eind 2025/2026) afloopt, komt hij prachtig in beeld!
    if eind_dt < (nu - relativedelta(months=12)):
        aandacht = "Verjaard (Verborgen)"
        badge_class = "badge-secondary"
        sort_score = 5
    elif actie_dt <= nu:
        aandacht = "🚨 Nu Actie"
        badge_class = "badge-danger"
        sort_score = 1
    elif (actie_dt - nu).days <= 365:
        aandacht = "⚠️ Korte termijn"
        badge_class = "badge-warning"
        sort_score = 2
    else:
        aandacht = "🔭 Anticiperen"
        badge_class = "badge-success"
        sort_score = 3

    is_te_laat = (sort_score == 5)
    return eind_dt.strftime("%Y-%m-%d"), actie_dt.strftime("%Y-%m-%d"), aandacht, badge_class, sort_score, is_te_laat

def genereer_microsite(leads):
    os.makedirs("tenderned", exist_ok=True)
    nu_str = datetime.now(TZ_NL).strftime("%d-%m-%Y %H:%M")
    
    totaal_leads = len(leads)
    urgent_count = sum(1 for l in leads if l["sort_score"] == 1)

    rijen_html = ""
    for lead in leads:
        count_html = f'<span class="count-badge" title="Dit traject is {lead["cyclus_count"]} keer voorgekomen">{lead["cyclus_count"]}x</span>' if lead["cyclus_count"] > 1 else ''
        
        rijen_html += f"""
        <tr class="tender-row" data-type="{lead['type_dienst']}">
            <td class="client-cell" style="max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{lead['dienst']}"><strong>{lead['dienst']}</strong></td>
            <td class="title-cell" style="max-width: 270px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="{lead['titel']}">{lead['titel']} {count_html}</td>
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
        :root {{ --primary: #0f172a; --accent: #2563eb; --bg: #f1f5f9; --card-bg: #ffffff; --text-main: #334155; --text-muted: #64748b; --border: #e2e8f0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--bg); color: var(--text-main); margin: 0; padding: 30px; }}
        .container {{ max-width: 1550px; margin: 0 auto; }}
        .header {{ display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 25px; border-bottom: 2px solid var(--border); padding-bottom: 15px; }}
        h1 {{ margin: 0; color: var(--primary); font-size: 1.6rem; letter-spacing: -0.5px; }}
        .timestamp {{ font-size: 0.85rem; color: var(--text-muted); }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin-bottom: 25px; }}
        .kpi-card {{ background: var(--card-bg); padding: 18px 20px; border-radius: 10px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
        .kpi-title {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); font-weight: 600; }}
        .kpi-value {{ font-size: 1.8rem; font-weight: 700; color: var(--primary); margin-top: 6px; }}
        
        .filter-group {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }}
        .filter-btn {{ background: var(--card-bg); border: 1px solid var(--border); padding: 8px 16px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; color: var(--text-muted); cursor: pointer; transition: all 0.2s; }}
        .filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
        .filter-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
        
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
        .count-badge {{ background: #1e293b; color: white; font-size: 0.65rem; padding: 2px 6px; border-radius: 10px; margin-left: 6px; vertical-align: top; }}
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
                <div class="timestamp">Laatste update: {nu_str} (Lokaal)</div>
            </div>
            <a href="/" style="font-size: 0.85rem; color: var(--accent); text-decoration: none; font-weight: 500;">← Terug naar hoofdsite</a>
        </div>

        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Unieke Pipeline Projecten</div>
                <div class="kpi-value">{totaal_leads}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Directe Actie (Nu of Binnenkort)</div>
                <div class="kpi-value" style="color: #b91c1c;">{urgent_count}</div>
            </div>
        </div>

        <div class="filter-group">
            <button class="filter-btn active" onclick="setFilter('Alle', event)">Alle Categorieën</button>
            <button class="filter-btn" onclick="setFilter('Gemeente', event)">Gemeentes</button>
            <button class="filter-btn" onclick="setFilter('Rijksoverheid', event)">Rijksoverheid</button>
            <button class="filter-btn" onclick="setFilter('Uitvoeringsorganisatie', event)">Uitvoeringsorganisaties</button>
            <button class="filter-btn" onclick="setFilter('Omgevingsdienst', event)">Omgevingsdiensten</button>
            <button class="filter-btn" onclick="setFilter('Onderwijs', event)">Onderwijs</button>
            <button class="filter-btn" onclick="setFilter('Zorg', event)">Zorg & Welzijn</button>
        </div>

        <div class="toolbar">
            <input type="text" id="searchInput" class="search-box" placeholder="Filter op dienst, titel of status..." onkeyup="filterTable()">
        </div>

        <div class="table-card">
            <table id="tenderTable">
                <thead>
                    <tr>
                        <th style="width: 15%;">Aanbestedende Dienst</th>
                        <th style="width: 25%;">Titel</th>
                        <th style="width: 16%;">Inkooproute / Mantel</th>
                        <th style="width: 8%;">Gepubliceerd</th>
                        <th style="width: 8%;">Einddatum</th>
                        <th style="width: 9%;">Acquisitie Start</th>
                        <th style="width: 14%;">Prioriteit</th>
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
        let currentType = 'Alle';
        
        function setFilter(type, event) {{
            currentType = type;
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            filterTable();
        }}

        function filterTable() {{
            const input = document.getElementById("searchInput").value.toLowerCase();
            const rows = document.querySelectorAll("#tenderTable tbody tr.tender-row");
            
            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                const rowType = row.getAttribute('data-type');
                
                const matchesSearch = text.includes(input);
                const matchesType = (currentType === 'Alle' || rowType === currentType);
                
                row.style.display = (matchesSearch && matchesType) ? "" : "none";
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
    
    ruwe_leads = []
    # Stap 1: Filter de strategische hits
    for pub in publicaties:
        is_fit, reden = kwalificeer_tender(pub)
        if not is_fit: continue

        dienst = vind_veld(pub, ["aanbestedendedienst", "organisatie", "opdrachtgever", "publicerendondernemer"]) or "Onbekend"
        titel = vind_titel(pub)
        pub_datum = vind_veld(pub, ["publicatiedatum", "datumpublicatie"]) or datetime.now(TZ_NL).strftime("%Y-%m-%d")
        pub_id = vind_veld(pub, ["publicatieid", "kenmerk", "uuid", "referentie"])
        
        ruwe_leads.append({
            "dienst": dienst.replace("\n", " ").strip(),
            "titel": titel.replace("\n", " ").strip(),
            "startdatum": str(pub_datum)[:10],
            "ruwe_data": pub,
            "pub_id": pub_id
        })

    # Stap 2: Groeperen en ontdubbelen
    project_groepen = {}
    for lead in ruwe_leads:
        norm_titel = normaliseer_titel(lead['titel'])
        key = (lead['dienst'], norm_titel)
        
        if key not in project_groepen:
            project_groepen[key] = []
        project_groepen[key].append(lead)

    gekwalificeerde_leads = []
    for key, leads_in_project in project_groepen.items():
        jaren = set([l['startdatum'][:4] for l in leads_in_project])
        cyclus_count = len(jaren)
        
        leads_in_project.sort(key=lambda x: x['startdatum'], reverse=True)
        laatste_lead = leads_in_project[0]
        
        eind_dt, actie_dt, aandacht, badge, sort_score, is_te_laat = bereken_tijdlijn(laatste_lead['startdatum'], laatste_lead['ruwe_data'])
        
        # De absolute opschoning: gooi 2012 lijken weg, bewaar wat NU/Binnenkort afloopt!
        if is_te_laat: continue

        link = f"https://www.tenderned.nl/aankondigingen/overzicht/{laatste_lead['pub_id']}" if laatste_lead['pub_id'] else "https://www.tenderned.nl/"

        gekwalificeerde_leads.append({
            "dienst": laatste_lead['dienst'],
            "titel": laatste_lead['titel'],
            "type_dienst": bepaal_type_dienst(laatste_lead['dienst']),
            "route": match_inkooproute(laatste_lead['dienst']),
            "startdatum": laatste_lead['startdatum'],
            "einddatum": eind_dt,
            "actiedatum": actie_dt,
            "aandacht": aandacht,
            "badge_class": badge,
            "sort_score": sort_score,
            "cyclus_count": cyclus_count,
            "link": link
        })

    # Sortering: Alles wat NU actie vereist staat direct bovenaan
    gekwalificeerde_leads.sort(key=lambda x: (x["sort_score"], x["actiedatum"]))
    
    genereer_microsite(gekwalificeerde_leads)
    print(f"Microsite gegenereerd in tenderned/index.html ({len(gekwalificeerde_leads)} unieke leads).")

if __name__ == "__main__":
    main()

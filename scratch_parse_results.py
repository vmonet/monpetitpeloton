import csv
from bs4 import BeautifulSoup

# Ouvre et parse le fichier HTML
with open("scratch_result.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

# Trouve le tableau principal
table = soup.find("table")
thead = table.find("thead")
tbody = table.find("tbody")

# Récupère les noms de colonnes visibles
headers = []
for th in thead.find_all("th"):
    if "hide" not in th.get("class", []):
        headers.append(th.get_text(strip=True))

# Prépare les lignes de données
rows = []
for tr in tbody.find_all("tr"):
    row = []
    tds = tr.find_all("td")
    visible_tds = [td for td in tds if "hide" not in td.get("class", [])]
    for td in visible_tds:
        # Pour la colonne Rider, récupère juste le nom
        if td.find("a"):
            row.append(td.find("a").get_text(strip=True))
        else:
            row.append(td.get_text(strip=True))
    rows.append(row)

# Écrit le CSV
with open("resultats.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(rows)

print("Export terminé : resultats.csv")
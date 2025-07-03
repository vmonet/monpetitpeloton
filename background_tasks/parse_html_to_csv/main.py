import os
from google.cloud import storage
from bs4 import BeautifulSoup
import csv

def parse_html_to_csv(event, context):
    bucket_name = event['bucket']
    file_name = event['name']
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)

    # Télécharge le HTML
    html_content = blob.download_as_text()

    # Parse le HTML (adapter selon ton format)
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows = []
    for tr in table.find_all("tr")[1:]:
        rows.append([td.get_text(strip=True) for td in tr.find_all("td")])

    # Écrit le CSV localement
    csv_file = "/tmp/result.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    # Upload le CSV dans un autre bucket
    output_bucket = storage_client.bucket(os.environ["OUTPUT_BUCKET"])
    output_blob = output_bucket.blob(file_name.replace(".html", ".csv"))
    output_blob.upload_from_filename(csv_file)

    # Archive le HTML dans un bucket d'archive
    archive_bucket = storage_client.bucket(os.environ["ARCHIVE_BUCKET"])
    archive_blob = archive_bucket.blob(file_name)
    archive_blob.upload_from_string(html_content)

    # Déclenchement de la 2e fonction :
    # (à compléter selon ton choix de trigger, ex: Pub/Sub, HTTP, ou trigger sur upload du CSV) 
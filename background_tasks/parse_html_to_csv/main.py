import os
from google.cloud import storage
from bs4 import BeautifulSoup
import csv

DEFAULT_BUCKET = "mpp-bucket-source-1751476837"
DEFAULT_ARCHIVE_BUCKET = "mpp-bucket-archive-1751476837"
DEFAULT_CSV_BUCKET = "mpp-bucket-csv-1751476837"


def parse_html_to_csv(bucket=DEFAULT_BUCKET):
    bucket_name = bucket
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    print(bucket)

    # Parcourt tous les fichiers du bucket
    blobs = bucket.list_blobs()
    for blob in blobs:
        print(blob.name)
        file_name = blob.name
        if not file_name.lower().endswith('.html'):
            continue
        # Télécharge le HTML
        html_content = blob.download_as_text()

        # Parse le HTML (adapter selon ton format)
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table")
        if not table:
            continue  # Ignore si pas de table
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        rows = []
        for tr in table.find_all("tr")[1:]:
            rows.append([td.get_text(strip=True) for td in tr.find_all("td")])

        # Écrit le CSV localement
        csv_file = f"/tmp/{os.path.basename(file_name).replace('.html', '.csv')}"
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        # Upload le CSV dans un autre bucket
        output_bucket = storage_client.bucket(DEFAULT_CSV_BUCKET)
        output_blob = output_bucket.blob(file_name.replace(".html", ".csv"))
        output_blob.upload_from_filename(csv_file)

        # Archive le HTML dans un bucket d'archive
        archive_bucket = storage_client.bucket(DEFAULT_ARCHIVE_BUCKET)
        archive_blob = archive_bucket.blob(file_name)
        archive_blob.upload_from_string(html_content)

        # Supprime le fichier source du bucket d'origine
        blob.delete()


if __name__ == "__main__":
    print("Starting parse_html_to_csv")
    parse_html_to_csv()


#!/bin/bash
gcloud functions deploy load_csv_to_db \
  --runtime python310 \
  --trigger-resource <BUCKET_CSV> \
  --trigger-event google.storage.object.finalize \
  --entry-point load_csv_to_db \
  --region europe-west1 
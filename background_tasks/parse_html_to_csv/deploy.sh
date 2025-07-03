#!/bin/bash

BUCKET_SOURCE=mpp-bucket-source-1751476837
BUCKET_CSV=mpp-bucket-csv-1751476837
BUCKET_ARCHIVE=mpp-bucket-archive-1751476837

gcloud functions deploy parse_html_to_csv \
  --runtime python310 \
  --trigger-resource $BUCKET_SOURCE \
  --trigger-event google.storage.object.finalize \
  --set-env-vars OUTPUT_BUCKET=$BUCKET_CSV,ARCHIVE_BUCKET=$BUCKET_ARCHIVE \
  --entry-point parse_html_to_csv \
  --region europe-west1 
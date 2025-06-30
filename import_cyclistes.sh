#!/bin/bash

# Exemple : ./import_cyclistes.sh cyclistes.csv

CSV_FILE=$1

if [ -z "$CSV_FILE" ]; then
  echo "Usage: $0 chemin/vers/fichier.csv"
  exit 1
fi

echo "Import des cyclistes depuis $CSV_FILE..."
python manage.py import_cyclists "$CSV_FILE"

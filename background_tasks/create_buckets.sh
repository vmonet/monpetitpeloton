#!/bin/bash

# À personnaliser
PROJECT_ID="peloton-prod"
REGION="europe-west1"
BUCKET_SOURCE="mpp-bucket-source-$(date +%s)"
BUCKET_CSV="mpp-bucket-csv-$(date +%s)"
BUCKET_ARCHIVE="mpp-bucket-archive-$(date +%s)"

# 1. Créer les buckets (storage class standard, région Europe)
gcloud storage buckets create gs://$BUCKET_SOURCE --project=$PROJECT_ID --location=$REGION --uniform-bucket-level-access
gcloud storage buckets create gs://$BUCKET_CSV --project=$PROJECT_ID --location=$REGION --uniform-bucket-level-access
gcloud storage buckets create gs://$BUCKET_ARCHIVE --project=$PROJECT_ID --location=$REGION --uniform-bucket-level-access

echo "Buckets créés :"
echo "  Source  : $BUCKET_SOURCE"
echo "  CSV     : $BUCKET_CSV"
echo "  Archive : $BUCKET_ARCHIVE"

# 2. (Optionnel) Rendre les buckets privés (par défaut) ou publics (déconseillé)
#gcloud storage buckets update gs://$BUCKET_SOURCE --public-access-prevention
#gcloud storage buckets update gs://$BUCKET_CSV --public-access-prevention
#gcloud storage buckets update gs://$BUCKET_ARCHIVE --public-access-prevention

# 3. Donner accès aux Cloud Functions (remplace <SERVICE_ACCOUNT> si besoin)
# Par défaut, les Cloud Functions utilisent le service account du projet
# Pour donner accès en écriture/lecture :
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

echo "Droits attribués au service account par défaut du projet."

# 4. Afficher les variables à utiliser dans tes scripts de déploiement
echo ""
echo "À utiliser dans tes scripts de déploiement :"
echo "BUCKET_SOURCE=$BUCKET_SOURCE"
echo "BUCKET_CSV=$BUCKET_CSV"
echo "BUCKET_ARCHIVE=$BUCKET_ARCHIVE"
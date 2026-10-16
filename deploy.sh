#!/usr/bin/env bash
# Deploy all three Cloud Run services.
# Usage: GCP_PROJECT_ID=your-project ./deploy.sh
set -euo pipefail

PROJECT=${GCP_PROJECT_ID:?"Set GCP_PROJECT_ID"}
REGION=${GCP_REGION:-us-central1}

echo "=== Groundswell Deploy to $PROJECT / $REGION ==="

# Build and push images
gcloud builds submit --tag "gcr.io/$PROJECT/gs-api" --dockerfile Dockerfile.api .
gcloud builds submit --tag "gcr.io/$PROJECT/gs-mcp" --dockerfile Dockerfile.mcp .
gcloud builds submit --tag "gcr.io/$PROJECT/gs-inventory-a2a" --dockerfile Dockerfile.inventory .

# Deploy gs-mcp (internal only)
gcloud run deploy gs-mcp \
  --image "gcr.io/$PROJECT/gs-mcp" \
  --region "$REGION" \
  --ingress internal \
  --no-allow-unauthenticated \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT,GCP_REGION=$REGION,BQ_DATASET=groundswell,FIRESTORE_DB=groundswell-db,APP_ENV=production"

MCP_URL=$(gcloud run services describe gs-mcp --region "$REGION" --format 'value(status.url)')
echo "MCP URL: $MCP_URL"

# Deploy gs-inventory-a2a (internal only)
gcloud run deploy gs-inventory-a2a \
  --image "gcr.io/$PROJECT/gs-inventory-a2a" \
  --region "$REGION" \
  --ingress internal \
  --no-allow-unauthenticated \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT,GCP_REGION=$REGION,BQ_DATASET=groundswell,FIRESTORE_DB=groundswell-db,INVENTORY_A2A_URL=https://gs-inventory-a2a-${REGION}-run.app,APP_ENV=production"

INVENTORY_URL=$(gcloud run services describe gs-inventory-a2a --region "$REGION" --format 'value(status.url)')
echo "Inventory A2A URL: $INVENTORY_URL"

# Deploy gs-api (public)
gcloud run deploy gs-api \
  --image "gcr.io/$PROJECT/gs-api" \
  --region "$REGION" \
  --ingress all \
  --allow-unauthenticated \
  --min-instances 1 \
  --set-env-vars "GCP_PROJECT_ID=$PROJECT,GCP_REGION=$REGION,MCP_SERVICE_URL=$MCP_URL,INVENTORY_A2A_URL=$INVENTORY_URL,BQ_DATASET=groundswell,FIRESTORE_DB=groundswell-db,APP_ENV=production"

API_URL=$(gcloud run services describe gs-api --region "$REGION" --format 'value(status.url)')
echo ""
echo "=== Deploy complete ==="
echo "  Shopper UI : $API_URL"
echo "  Manager UI : $API_URL/manager"
echo "  Health     : $API_URL/health"
echo "  Inventory  : $INVENTORY_URL (internal only)"
echo "  MCP        : $MCP_URL (internal only)"

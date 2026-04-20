#!/usr/bin/env bash

# Identity Check
CURRENT_USER=$(gcloud config get-value account 2>/dev/null)
KENYON_EMAILS=("kjones.px10pro@gmail.com" "kjones@shy2shy.com" "kjonesmle@gmail.com")

IS_PROD_USER=false
for email in "${KENYON_EMAILS[@]}"; do
    if [ "$CURRENT_USER" == "$email" ]; then
        IS_PROD_USER=true
        break
    fi
done

echo "👤 Current Identity: $CURRENT_USER"

# Define Secret Mapping
if [ "$IS_PROD_USER" = true ]; then
    echo "🔓 LEAD ARCHITECT DETECTED: Syncing PRODUCTION keys..."
    SECRETS=("TWILIO_ACCOUNT_SID" "TWILIO_AUTH_TOKEN" "GEMINI_API_KEY" "SMTP_PASSWORD")
else
    echo "🛡️  OPERATOR DETECTED: Syncing SANDBOX/TEST keys..."
    # These secrets must exist in GCP with these names (e.g., TWILIO_TEST_AUTH_TOKEN)
    SECRETS=("TWILIO_TEST_ACCOUNT_SID" "TWILIO_TEST_AUTH_TOKEN" "GEMINI_TEST_KEY")
fi

# Sync Loop
for secret in "${SECRETS[@]}"; do
    if gcloud secrets versions access latest --secret="$secret" &>/dev/null; then
        VALUE=$(gcloud secrets versions access latest --secret="$secret")
        # Map Test keys to standard names in the local .env so code doesn't break
        ENV_KEY=$(echo "$secret" | sed 's/_TEST//')
        
        if grep -q "^$ENV_KEY=" .env; then
            sed -i "s|^$ENV_KEY=.*|$ENV_KEY=$VALUE|" .env
        else
            echo "$ENV_KEY=$VALUE" >> .env
        fi
        echo "✅ Synced: $ENV_KEY"
    else
        echo "❌ Missing Secret: $secret"
    fi
done

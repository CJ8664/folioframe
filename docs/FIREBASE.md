# SpectraFrame on Firebase — runbook

Production topology:

- **Cloud Run** (`spectraframe`, `us-west1`): the Python service (device API +
  web console). Built from `Dockerfile` at repo root.
- **Firebase Hosting**: `https://<project>.web.app` rewrites everything to
  Cloud Run (`firebase.json`).
- **Sign-in**: direct Google ID-token verification (bring-your-own OAuth
  client per user, via the welcome page). **No Firebase Authentication
  setup needed** -- the admin configures zero OAuth.
- **Firestore**: users, devices, sessions, rotation state, per-user Photos
  tokens (`firestore.rules` denies all direct client access — server only).
- **Cloud Storage**: override frames/previews + per-user Google Photos cache
  (`storage.rules` denies all direct client access — server only).

## Why Blaze is required

Cloud Run cannot run on the Spark (free, no-billing) plan — Blaze
(pay-as-you-go) is a hard platform requirement, even when usage stays inside
the free quotas. Expected bill for one frame + occasional console use: **$0**
(Cloud Run free tier: 2M requests/mo; Firestore: 50k reads/day; the frame
wakes ~hourly). Set a **$5 budget alert** so you'd hear about it long before
anything real accrues.

## One-time setup (Chirag clicks)

1. Create the project: https://console.firebase.google.com → Add project →
   name `SpectraFrame`, disable Analytics (optional). Note the **project ID**.
2. Upgrade to Blaze: bottom-left gear → Usage and billing → Modify plan →
   Blaze. Attach billing when asked.
3. Billing → Budgets & alerts → create a **$5** budget alert on the project.
4. Firestore: Build → Firestore Database → Create database → `us-west1`,
   Native mode, then deploy the locked-down rules below.
5. Storage: Build → Storage → Get started → `us-west1`, then deploy rules.
   (No Authentication setup: sign-in is direct Google ID-token verification
   with each user's own OAuth client -- see the welcome page.)

## Deploy (from a machine with firebase-tools + gcloud)

```bash
cd ~/workspace/spectra-frame
# 1. point at the project
firebase use <project-id>          # (or edit .firebaserc)

# 2. Firestore DB (once)
gcloud firestore databases create --database='(default)' \
  --location=us-west1 --type=firestore-native --project=<project-id>

# 3. enable APIs (once)
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firebasehosting.googleapis.com \
  --project=<project-id>

# 4. rules + hosting config
firebase deploy --only firestore:rules,storage,hosting

# 5. service config (secret: use Secret Manager in production;
#    env var is fine to start -- see below)
export SPECTRA_CONFIG_JSON='<json>'

# 6. build + deploy the service
gcloud run deploy spectraframe --source . --region=us-west1 \
  --project=<project-id> --allow-unauthenticated \
  --set-env-vars=SPECTRA_CONFIG_JSON="$SPECTRA_CONFIG_JSON" \
  --min-instances=0 --max-instances=2 --memory=512Mi
```

`SPECTRA_CONFIG_JSON` (top-level keys replace `server/config.json`):

```json
{
  "firebase": {
    "project_id": "<project-id>",
    "storage_bucket": "<project-id>.appspot.com",
    "public_url": "https://<project-id>.web.app"
  },
  "auth": {
    "allowlist": ["er.chiragjain92@gmail.com"]
  }
}
```

No OAuth anywhere in this JSON: the admin deploys; each user brings their
own Google OAuth client via the welcome page (sign-in + Photos, per user).

Notes:

- `auth.allowlist`: empty = any Google account may create an account (each
  account's devices, Photos, and tokens are isolated per user). The value
  above restricts sign-in to Chirag only.
- Each user's Photos OAuth client must be a **Web** client whose authorized
  redirect URIs include `https://<project-id>.web.app/api/gphotos/callback`
  (the welcome page shows the exact URI for the deployment).
- The deny-all Firestore/Storage rules stand: all data access is
  server-side, behind the user's session.

## Recommended: GitHub Actions deploy (mirrors pregnancy-super-app)

Same OIDC pattern as the pregnancy app — no service-account keys:

1. In the GCP console: IAM → Workload Identity Federation → create a pool
   (e.g. `github-actions`) + provider for
   `https://token.actions.githubusercontent.com`, attribute condition
   restricting to repo `CJ8664/spectra-frame`.
2. Grant the pool's service account: Cloud Run Admin, Artifact Registry
   Writer, Firebase Hosting Admin.
3. `.github/workflows/deploy.yml`: build the Docker image, push to Artifact
   Registry, `gcloud run deploy`, `firebase deploy --only hosting`.
4. `SPECTRA_CONFIG_JSON` lives as a GitHub **secret**, never in the repo.

## Verify after deploy

1. Open `https://<project-id>.web.app/login` → sign in with Google →
   console loads, no devices yet.
2. `GET https://<project-id>.web.app/api/config` → shows the firebase web
   block (public values only).
3. Pairing dry-run comes with the firmware (Phase 2): the device's
   `POST /v1/device/register` must return a claim code over public HTTPS.
4. Firestore console: `devices/`, `users/`, `sessions/`, `_service/`
   collections appear as you use the app.

## Local dev is unchanged

Without `firebase.project_id` in config, everything runs exactly as before:
local JSON store, local disk blobs, direct Google ID-token verification.
`SPECTRA_CONFIG_JSON` is ignored unless set.

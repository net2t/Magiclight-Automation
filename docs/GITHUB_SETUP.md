# GitHub Actions — Secrets & Variables Setup Guide
**MagicLight Auto Pipeline**

> [!IMPORTANT]
> Complete ALL secrets before triggering the workflow. Missing even one required secret will cause the run to fail immediately.

---

## Where to Set Secrets and Variables

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Two tabs: **Secrets** (encrypted, hidden) and **Variables** (plain text, visible in logs)

---

## 🔴 Required SECRETS

These are encrypted and never shown in logs. Go to **Secrets tab** → **New repository secret**.

---

### `GCP_CREDENTIALS`
**What it is:** The Google Service Account JSON key file that allows writing to Google Sheets and Google Drive.

**How to get it:**
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project (or use existing)
3. Enable APIs: **Google Sheets API** + **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Download the JSON key file
6. Share your Google Sheet with the service account email (give it **Editor** access)
7. Share your Google Drive folder with the service account email (give it **Editor** access)

**Value to paste:** The entire JSON content of the downloaded key file. Example format:
```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
  "client_email": "magiclight@your-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

---

### `ENV_FILE`
**What it is:** The entire content of your local `.env` file — all configuration in one secret.

**How to get it:** Copy the content of your `e:\Pythons\AMagicLight\.env` file.

**Value to paste** (fill in your actual values):
```
EMAIL=your@email.com
PASSWORD=yourPasswordHere

SHEET_ID=1p5sg2j-6IZhbj-7s2giJM_9e9rWnK-ixgcrt3jgR7Gc
SHEET_NAME=Database
CREDS_JSON=credentials.json

DRIVE_FOLDER_ID=1JPz4lfkhbdNInVGUOkgFNM5QIIqPygrt

PIPELINE_MODE=local
LOCAL_OUTPUT_ENABLED=false
UPLOAD_TO_DRIVE=true

STEP1_WAIT=45
STEP2_WAIT=20
STEP3_WAIT=120
STEP4_RENDER_TIMEOUT=900

LOGO_PATH=assets/logo.png
ENDSCREEN_VIDEO=assets/endscreen.mp4
TRIM_SECONDS=4
LOGO_X=7
LOGO_Y=5
LOGO_WIDTH=300
LOGO_OPACITY=1.0
ENDSCREEN_ENABLED=false

DEBUG=0
```

> [!TIP]
> Set `LOCAL_OUTPUT_ENABLED=false` on GitHub Actions — there's no persistent storage, so saving files locally is pointless. Videos will be uploaded directly to Drive.

---

### `ACCOUNTS_TXT`
**What it is:** The `accounts.txt` file content — one `email:password` per line for MagicLight accounts. Pipeline rotates accounts when credits run low.

**Value to paste:**
```
account1@gmail.com:Password123
account2@gmail.com:AnotherPass456
account3@gmail.com:YetAnother789
```

> [!NOTE]
> If you only have one account, just put one line. The pipeline will stop when it runs out of credits.

---

### `OAUTH_TOKEN`
**What it is:** Your `token.json` file — the saved Google OAuth token that allows the pipeline to authenticate without a browser popup.

**How to get it:**
1. Run `python main.py` locally once — it will open a browser for Google auth
2. After authorizing, `token.json` is created in your project folder
3. Copy the content of `token.json`

**Value to paste:** The entire JSON content of `token.json`:
```json
{
  "token": "ya29.a0AfH6...",
  "refresh_token": "1//0eXxx...",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "123456789-abc.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxxx",
  "scopes": ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"],
  "expiry": "2026-05-01T10:00:00.000000Z"
}
```

> [!WARNING]
> OAuth tokens expire! If runs start failing with auth errors, regenerate `token.json` locally and update this secret.

---

### `OAUTH_CREDENTIALS` *(optional)*
**What it is:** Your `oauth_credentials.json` (OAuth 2.0 Client ID file from Google Cloud). Only needed if using OAuth instead of service account.

**How to get it:** Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON

---

## 🟡 Optional SECRETS (fallback for Variables)

These are alternatives to setting the values as Repo Variables. Use secrets if the values are sensitive.

| Secret Name | Description |
|---|---|
| `SHEET_ID` | Your Google Sheet ID (from the URL: `spreadsheets/d/THIS_PART/edit`) |
| `SHEET_NAME` | Sheet/tab name (default: `Database`) |
| `DRIVE_FOLDER_ID` | Google Drive folder ID where videos are uploaded |

---

## 🟢 Repository VARIABLES (non-sensitive, editable)

Go to **Variables tab** → **New repository variable**. These override values from `ENV_FILE`.

| Variable | Example Value | Description |
|---|---|---|
| `SHEET_ID` | `1aBcDeFgHiJkLmNoPqRsTuVwXyZ` | Google Sheet ID |
| `SHEET_NAME` | `Database` | Sheet tab name |
| `DRIVE_FOLDER_ID` | `1AbCdEfGhIjKl_folderId` | Drive folder ID for uploads |
| `LOCAL_OUTPUT_ENABLED` | `false` | Disable local file saves on runner |

> [!TIP]
> Use **Variables** for `SHEET_ID`, `SHEET_NAME`, `DRIVE_FOLDER_ID` — they're not sensitive and you'll edit them more often. Secrets are harder to debug.

---

## 📋 Quick Checklist

Before running the workflow, confirm:

- [ ] `GCP_CREDENTIALS` secret set with full service account JSON
- [ ] Service account email has **Editor** access on your Google Sheet
- [ ] Service account email has **Editor** access on your Google Drive folder
- [ ] `ENV_FILE` secret set with complete `.env` content
- [ ] `ACCOUNTS_TXT` secret set with at least one `email:password` line
- [ ] `OAUTH_TOKEN` secret set with content of `token.json` (from a local run)
- [ ] `SHEET_ID` set (either as Variable or inside `ENV_FILE`)
- [ ] `DRIVE_FOLDER_ID` set (either as Variable or inside `ENV_FILE`)
- [ ] Google Sheets API enabled in GCP project
- [ ] Google Drive API enabled in GCP project

---

## 🚀 Running the Workflow

### Manual Trigger
1. Go to your repo → **Actions** tab
2. Select **MagicLight Generation Pipeline**
3. Click **Run workflow**
4. Fill in the inputs:
   - **Mode:** `combined` (generate + upload)
   - **Quantity:** `1` (or more)
   - **Upload to Drive:** ✅ checked
   - **Loop mode:** ✅ for continuous runs
   - **Debug:** ✅ only if troubleshooting

### Automatic Schedule
The workflow runs automatically **every hour** via the cron schedule.
It always uses: `combined --max 1 --headless --upload-drive`

To disable scheduled runs, remove or comment out the `schedule:` section in the workflow file.

---

## 🔍 Troubleshooting Common Failures

| Error | Likely Cause | Fix |
|---|---|---|
| `SHEET_ID missing` | `SHEET_ID` not in `.env` or Variables | Set `SHEET_ID` as a repo Variable |
| `Login failed` | Wrong email/password in `ACCOUNTS_TXT` | Check `accounts.txt` content |
| `Service account credentials not found` | `GCP_CREDENTIALS` secret empty | Re-paste the full JSON |
| `Token expired` | OAuth token in `OAUTH_TOKEN` is stale | Regenerate locally and update secret |
| `Drive upload failed` | Service account lacks Drive folder permission | Share folder with service account email |
| Playwright timeout | Site slow or selector changed | Increase `STEP3_WAIT` in `ENV_FILE` |
| `No_Video` status | Download failed (selectors changed) | Enable `DEBUG=1` in `ENV_FILE` and check artifacts |

---

## 📁 Artifacts

After each run, output files are saved as **GitHub Artifacts** (7-day retention):
- `output/` — downloaded videos and thumbnails (if `LOCAL_OUTPUT_ENABLED=true`)
- `output/screenshots/` — debug screenshots on errors
- `pipeline.log` — full console output

Go to the Actions run → scroll down → **Artifacts** section to download.

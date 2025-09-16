
# TRMNL — Singapore Bus Timings (3 stops)

Public TRMNL plugin that renders Singapore bus arrivals for **3 bus stops**.
- **Installation URL**: `/install`
- **Installation Success Webhook URL**: `/installed`
- **Plugin Management URL**: `/manage`
- **Plugin Markup URL**: `/markup`
- **Uninstallation Webhook URL**: `/uninstalled`
- **Knowledge Base URL**: `/kb`

## One‑click deploy (Render)
1. Push this folder to a new GitHub repo.
2. Visit https://render.com/deploy and import your repo. (This repo includes `render.yaml` for blueprint deploy.)
3. Set environment variables:
   - `LTA_API_KEY` (required)
   - `TRMNL_CLIENT_ID`, `TRMNL_CLIENT_SECRET` (required)
   - `DEFAULT_STOP_A`, `DEFAULT_STOP_B`, `DEFAULT_STOP_C` (optional)
4. Once live, copy your base URL and paste the following in TRMNL **Plugin Creation**:
   - Installation URL → `https://YOURDOMAIN/install`
   - Installation Success Webhook URL → `https://YOURDOMAIN/installed`
   - Plugin Management URL → `https://YOURDOMAIN/manage`
   - Plugin Markup URL → `https://YOURDOMAIN/markup`
   - Uninstallation Webhook URL → `https://YOURDOMAIN/uninstalled`
   - Knowledge Base URL → `https://YOURDOMAIN/kb`

## Local run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in values
export $(grep -v '^#' .env | xargs)  # or use a dotenv loader
python app.py
```

## Notes
- We store per‑user settings in **SQLite** keyed by UUID sent by TRMNL. Access tokens are saved on install for optional validation.
- LTA requests are server‑side; don't expose your `LTA_API_KEY` in the browser.
- Markup returns HTML for **all TRMNL layouts** (`markup`, `markup_half_horizontal`, `markup_half_vertical`, `markup_quadrant`) as required for public marketplace submissions.

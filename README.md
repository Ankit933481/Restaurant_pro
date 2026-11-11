# Restaurant Pro — Browser Edition

Responsive restaurant management dashboard based on the existing Restaurant Pro Flask API.

## Start locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
# Windows PowerShell: $env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
python run_web.py
```

Open http://127.0.0.1:5000

Create a restaurant owner account to use live data and save records. The Explore Demo button displays illustrative sample data only and does not modify the backend.

## Features
- Modern responsive dashboard, sales chart and table availability
- Login / owner registration
- Menu item creation and editing; category creation
- Table creation and status updates
- Order creation
- Billing history and analytics
- Export order list as CSV
- Original Flask API preserved at `/api/v1/` and documentation at `/api/docs`

## Notes
- Food photos load from Unsplash and require an internet connection. These are illustrative images, not original product photography.
- Backend prices are stored in minor currency units (paise).
- Browser interface covers core academic modules; advanced backend features are available via API but not all are exposed in the web UI.
- Keep SECRET_KEY and DATABASE_URL private. Do not commit real production credentials.

## Independent starter restaurants (new)

Each **new registration** now creates a separate restaurant and copies the same
8 starter dishes, 4 categories and 16 tables (T01–T16, initially available)
into that restaurant's own records. Changes to food, prices, tables, orders,
bills and reports are private to the account's restaurant. A second account
starts with its own independent copy, not shared database rows.

**Existing registered accounts are not overwritten or reset.** To see the
starter setup, register a new account. Staff accounts belonging to one
restaurant intentionally share that restaurant's records.

Set `SEED_NEW_RESTAURANTS=false` to disable automatic starter data.
Starter images in the browser are visual illustrations, not stored uploads.

Run the isolation test with `python -m unittest tests.test_starter_isolation`.

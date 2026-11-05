# Setup and start, step by step

You need two programs running at the same time: the **backend** (Python, port 8000) and the **frontend** (Node, port 5173).
Use two terminal windows.

## 0. Install once
| Tool | Version | Check with |
|---|---|---|
| Python | 3.11 or newer | `python --version` (Windows: `py --version`) |
| Node.js (includes npm) | 18 or newer | `node --version` |

Download them from python.org and nodejs.org if missing. On Windows, tick "Add Python to PATH" in the installer.

## 1. Open the project folder
```bash
cd path/to/hospital-ops-ai
```

## 2. Create the sample data (once)
```bash
python data/generate_synthetic.py        # Windows: py data\generate_synthetic.py
```
This writes `data/synthetic/hospital_operations.csv` (52,560 rows). If the file is already there, skip this step.

## 3. Start the backend (terminal 1)
macOS / Linux:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```
Windows (PowerShell):
```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```
- If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `.venv\Scripts\activate.bat` in Command Prompt.
- Open `backend/.env` and replace `SECRET_KEY` with any long random text.
- `pip install` takes a few minutes the first time (it installs scikit-learn and SHAP).
- Success looks like `Uvicorn running on http://127.0.0.1:8000`. Check: open http://127.0.0.1:8000/docs.
- The database file `backend/hospital_ops.db` and the admin user are created automatically on first start.

## 4. Start the frontend (terminal 2)
```bash
cd frontend
npm install
npm run dev
```
Success looks like `Local: http://localhost:5173/`.

## 5. Use it
1. Open http://localhost:5173 and sign in with **admin** / **Admin@123**.
2. Go to **Data Upload** and either:
   - click **Upload dataset** (top right, or the **Upload data** button in the top bar) and choose a `.csv` or `.xlsx` file, for example `data/synthetic/hospital_operations.csv`, or
   - click **Load sample dataset** to load the bundled data in one click.
3. Wait for the validation report (about 20 seconds for the sample), then open any other page. Start with the Dashboard.
4. For the guided tour see `docs/DEMO.md`.

Your own file needs these columns (names can vary, common synonyms are recognised): a date (or `timestamp`), `time`, `department`,
and `arrivals` or `admissions`; the other columns are optional. Click **Template** on the Data Upload page for an example.
Files must be .csv or .xlsx, up to 10 MB and 300,000 rows, and must not contain patient names, phone numbers, e-mails or IDs.

## 6. Stop and restart
- Stop each program with `Ctrl+C` in its terminal.
- Next time, skip the installs: backend `cd backend`, activate the venv, run the `uvicorn` line; frontend `cd frontend`, `npm run dev`.
- To start from a clean slate, stop the backend and delete `backend/hospital_ops.db` (and the `backend/ml_artifacts` folder contents).

## 7. Run the tests (optional)
```bash
cd backend && python -m pytest -q       # with the venv active; about 2 minutes
```

## Troubleshooting
| Problem | Fix |
|---|---|
| Top bar says "API offline" | The backend is not running, or is on another port. Start it (step 3). |
| Login fails | Use `admin` / `Admin@123`, or the values in `backend/.env` (`SEED_ADMIN_*`) if you changed them before the first start. |
| `pip install` fails on a package | Check `python --version` is 3.11 or newer. Upgrade pip: `python -m pip install --upgrade pip`. |
| `Address already in use` | Another program uses the port. Stop it, or use `--port 8001` and change the proxy target in `frontend/vite.config.js`. |
| Upload is rejected | Read the message on the page: it lists exactly which column or value is the problem. |
| First visit to Recommendations is slow | It trains the forecasts once (about 15 to 30 seconds), then it is cached. |
| Blank page after an update | Hard refresh the browser (Ctrl+Shift+R). |

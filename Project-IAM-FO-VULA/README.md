# VULA Control Center

VULA Control Center is a local operations tool for checking VULA eligibility, PCO capacity, customer assignments, and launching step-by-step studies in WimTech.

## Features

- Search for a PCO and determine whether it is inside a VULA polygon.
- Test a GPS coordinate against VULA coverage.
- Analyze PCOs by network zone or from a manual/Excel list.
- Combine PCO capacity and occupation data to identify free or saturated PCOs.
- Search a customer database by address, name, login, or ONT serial number.
- Extract a CMD installation address from WimTech and launch an automated study.
- Store imported operational files locally in the browser.

## Requirements

- Windows with Python 3.10 or newer
- Google Chrome
- Network access to the internal WimTech application
- Internet access on the first setup to install Python packages

## Quick start on Windows

Double-click `start.bat`. It creates an isolated Python environment, installs the required packages, and starts the application.

Then open `http://127.0.0.1:5000`. Stop the application by pressing `Ctrl+C` in its terminal window.

## Manual installation

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

## Initial configuration

Open the **Configuration** tab and import:

1. VULA coverage polygons in KML or KMZ format.
2. PCO points in KML or KMZ format.
3. PCO occupation data in Excel or CSV format.
4. The customer database in Excel or CSV format.

The browser keeps these files in IndexedDB, with local storage as a fallback. Clearing browser data or using another browser profile requires importing them again.

### PCO occupation columns

```text
PCO, NBRE_OCCUPE, NBRE_PORT
```

See `examples/occupation_template.csv`.

### Customer database columns

```text
ODF, Login, Série ONT, Nom Client, Adresse Client, NE, PCO, OLT
```

See `examples/clients_template.csv`.

## Optional environment configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WIMTECH_URL` | Current internal URL | Overrides the WimTech study URL. |
| `SELENIUM_WAIT_TIMEOUT` | `25` | Maximum Selenium wait in seconds. |
| `SELENIUM_SESSION_TTL_SECONDS` | `900` | Closes abandoned Chrome sessions after this period. |
| `APP_LOG_LEVEL` | `INFO` | Application logging level. |

Use `.env.example` as a reference. The application reads operating-system environment variables; it does not automatically load the `.env` file.

## Clone for windows

Le dépôt GitHub du projet est :
`https://github.com/SamirEzzahir/Project-IAM-FO-VULA.git`.

### Première installation

```bash
git clone https://github.com/SamirEzzahir/Project-IAM-FO-VULA.git
cd Project-IAM-FO-VULA

```

## Daily GitHub workflow

```bash
git pull origin main
git status
git add . 
git commit -m "Describe your changes"
git push origin main
```

## Troubleshooting

- **Chrome does not open:** update Chrome and Selenium, then restart the application.
- **WimTech cannot be reached:** verify the corporate network/VPN and configured URL.
- **Imported files disappear:** use the same browser profile and do not clear its site data.
- **Excel import fails:** confirm that the required column names are present.
- **A session expires:** search for the CMD again to open a new WimTech session.

## Security and data handling

- Run the server only on `127.0.0.1`; do not expose it publicly.
- Never commit real customer, PCO, KML, KMZ, or occupation files.
- Imported operational files remain in the local browser, but anyone using that browser profile may be able to access them.
- Treat the WimTech URL and all exported results as internal information.

## Project structure

```text
app.py                                  Flask API and Selenium automation
index.html                             Application interface
static/css/app.css                      Interface styling
static/js/app.js                        Browser-side processing
static/vendor/                          Local third-party browser libraries
examples/                               Safe input templates
requirements.txt                        Python dependencies
start.bat                               Windows launcher
```

Developed by ELMASSAOUDI Mohamed.

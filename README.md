# AETHER 1.5 — Adaptive Ecosystem for Human Exploration and Resilience

**NASA Space Apps Challenge 2026 | Astronaut health and mission decision-support research prototype**

AETHER is an integrated, offline-capable application for exploring crew well-being, physiological signals, spacecraft conditions, and mission decisions. It combines a React/TypeScript interface and 3D visualizations with a Python backend, local SQLite storage, research-data tools, and simulated mission scenarios.

> **Research prototype only.** AETHER is not a medical device, is not flight-certified, and is not affiliated with or endorsed by NASA. Its simulated crew and spacecraft measurements must not be presented as real astronaut telemetry. Its alerts and estimates are not medical diagnoses.

## What AETHER does

| Feature | Functionality |
| --- | --- |
| **Mission Control** | Mission overview, crew and spacecraft status, and navigation between the integrated modules. Mission values are synthetic unless explicitly identified otherwise. |
| **BIOSIGNALS** | Import physiological recordings (including MMASH research data), record clearly labeled demonstration signals, and attempt live heart-rate acquisition from compatible Bluetooth Low Energy (BLE) Heart Rate Service devices. Tracks acquisition state, recording history, missing data, and source information. |
| **BODY** | Interactive 3D human digital twin for exploring selected physiological measurements and simulated crew conditions. Includes local GLB assets and visualization fallbacks. |
| **PHANTOM** | Exploratory physiological trend, anomaly, and personal-baseline analysis, with data-quality and uncertainty context. Includes simulated mission analysis and adapters for supported real recordings. |
| **SYMBIOSIS** | Explore relationships between crew well-being and spacecraft environmental conditions in simulated mission scenarios. |
| **CO-ORBIT** | Crew workload, scheduling, and task-planning support, including mission-system optimization experiments. |
| **RECOVERY** | Recovery activity suggestions, sessions, and feedback within the prototype's decision-support workflow. |
| **MISSION LAB** | Run, compare, save, and revisit synthetic mission scenarios and experiments; inspect mission-system simulations and evaluation outputs. |
| **SCIENCE** | Scientific background, human-spaceflight hazards, and references to NASA human research and standards. |
| **NASA DATA LAB** | Search NASA Open Science Data Repository (OSDR) study metadata, inspect research-file catalogs, and analyze supported research CSV/TSV files with provenance and data-quality information. |
| **Local persistence** | Store supported sessions, scenarios, recordings, and application data using SQLite. |
| **Demo mode** | Explore the interface and mission workflow without physical sensors or a network connection using explicitly synthetic data. |

### Data sources and scientific boundaries

AETHER distinguishes **real terrestrial sensor/research recordings**, **NASA research metadata or imported datasets**, **synthetic mission data**, and **model-derived estimates**. NASA OSDR catalog entries are not live astronaut vital signs. Uploaded files must retain their original source and units; an arbitrary uploaded CSV is not automatically verified as NASA data. BLE measurements are only real when a compatible device is connected and actively transmitting.

**Wearable compatibility:** The implemented desktop BLE path targets the standard Bluetooth SIG Heart Rate Service (`0x180D`) and Heart Rate Measurement characteristic (`0x2A37`). It does **not** provide universal smartwatch pairing or native Apple Health/HealthKit and Android Health Connect integration. Apple Watch, Samsung, Xiaomi, Huawei, and other watches are not guaranteed to work; some devices may support heart-rate broadcast. SpO₂, temperature, and sleep are not available through this heart-rate-only path. Physical-device compatibility remains unverified in the included release reports.

## Technology

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, WebGL/GLB 3D assets.
- **Backend:** Python, FastAPI, Pydantic, NumPy/SciPy, SQLite; optional BLE support via Bleak.
- **Desktop packaging:** Windows launcher and Tauri/WebView2 packaging tools; PyInstaller for backend distribution.
- **Mobile prototype shell:** Capacitor projects can be generated for Android and iOS. The mobile build uses **demo data**; it is not equivalent to the live desktop/backend integration.

## Quick start — run from source (recommended)

### Requirements

- Windows 10/11, macOS, or Linux for source development (Windows is the primary desktop target).
- **Python 3.11–3.13** and `pip` (Python 3.13 is used in the Windows launcher workflow).
- **Node.js 20+ and npm** to build the current frontend on the first run.
- Internet access for initial dependency installation and online NASA catalog searches; most demo functionality can work locally after setup.
- A modern browser; for the Windows desktop shell, Microsoft Edge WebView2 Runtime.

### Option A: one-file Python launcher

1. Clone or download this repository and extract it, preserving the directory structure.
2. Open a terminal in the **repository root** (the directory containing `RUN_AETHER.py`).
3. Run:

   ```bash
   python RUN_AETHER.py
   ```

   On Windows, you can also open `RUN_AETHER.py` in PyCharm and press **Run**, or use the supplied `START_AETHER.bat` launcher.
4. On the first run, the launcher attempts to install missing backend dependencies and compile the current React interface using npm. Wait for setup to complete.
5. Open **http://127.0.0.1:8000** if the browser does not open automatically.
6. Select **Demo Mode** to explore AETHER without a wearable or external research data.

**Note:** The launcher may fall back to a prebuilt frontend if the current React build fails. In that case, some newer UI features or 3D assets may not be reflected until the frontend is successfully rebuilt. Review the terminal output rather than assuming the latest UI was loaded.

### Option B: manual development setup

From the repository root:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install backend dependencies:

```bash
python -m pip install -r web/backend/requirements.txt
```

Install and build the frontend:

```bash
cd web/frontend
npm ci
npm run build:offline
cd ../..
```

Start the application using the root launcher:

```bash
python RUN_AETHER.py
```

For frontend development, `cd web/frontend && npm run dev` starts Vite separately. Backend API and static-serving development entry points are in `web/backend/app/`; the root launcher is the simplest way to start the combined application.

## Windows desktop builds

This repository contains Windows batch build scripts, including `BUILD_WINDOWS_1_5.bat`, as well as desktop/Tauri packaging resources. Run Windows packaging **on a Windows machine** with the required Python, Node.js, Rust/Tauri, WebView2 and packaging dependencies. Follow the console output and inspect generated artifacts before distribution.

**Important release status:** The included 1.5 reports state that the repackaged executable was **not verified running on a physical Windows machine**, and physical BLE hardware testing was **not completed**. Do not advertise the packaged application or smartwatch support as hardware-verified without performing those tests. The source launcher is the recommended evaluation route.

## Android and iOS (experimental demo shell)

The repository includes a Capacitor-based mobile shell and `BUILD_MOBILE.py`:

```bash
python BUILD_MOBILE.py
cd mobile
npx cap add android   # first time only
npx cap open android
```

Build and run Android from **Android Studio**. For iOS, use **macOS with Xcode**:

```bash
cd mobile
npx cap add ios       # first time only
npx cap open ios
```

After changing frontend code, rerun `python BUILD_MOBILE.py` to rebuild/sync web assets. This script prepares native projects; it does **not** independently produce signed APK or IPA packages. The mobile shell is configured with `VITE_MOBILE_APP=1` and `VITE_DATA_MODE=demo`; do not claim that it streams live sensor or NASA data from the Python server.

## Using the application

1. Start in **Demo Mode** for a complete simulated mission overview.
2. Open **BODY** to inspect the 3D representation and **PHANTOM** to review trends and uncertainty.
3. Explore **SYMBIOSIS**, **CO-ORBIT**, and **RECOVERY** for environmental, workload, and recovery decision-support workflows.
4. Use **MISSION LAB** to run or compare synthetic scenarios.
5. Open **BIOSIGNALS** to import supported research recordings, create demo recordings, or attempt BLE acquisition with a compatible heart-rate broadcaster.
6. Use **NASA DATA LAB** to search public study metadata and analyze appropriately sourced research tables. NASA network features require connectivity.
7. Check **SCIENCE** for background references and the limitations of the models.

## Repository structure

```text
AETHER/
├── README.md                  # This consolidated guide
├── RUN_AETHER.py              # Recommended source launcher
├── START_AETHER.bat           # Windows startup helper
├── BUILD_WINDOWS_1_5.bat      # Windows build workflow
├── BUILD_MOBILE.py            # Prepare Capacitor mobile shell
├── web/
│   ├── backend/               # Python API, models, mission systems, tests
│   └── frontend/              # React/TypeScript UI, 3D, assets, tests
├── desktop/                   # Tauri desktop shell and build resources
├── mobile/                    # Capacitor Android/iOS shell
├── website/                   # Separate static project website
├── tools/                     # Build, validation, and test utilities
├── docs/                      # Supporting engineering and research documents
└── legacy/                    # Earlier prototypes, not the primary entry point
```

## Testing and troubleshooting

- **Node/npm missing:** Install Node.js 20+ and rerun `python RUN_AETHER.py`.
- **Frontend build fails:** Check the npm/TypeScript output. The launcher may load a previously built UI; rebuild before evaluating the newest functionality.
- **Python dependencies missing:** Run `python -m pip install -r web/backend/requirements.txt` in the active environment.
- **Port 8000 already in use:** Stop the other local server before launching AETHER.
- **No Bluetooth device detected:** Check adapter permissions, ensure the device actually broadcasts standard BLE Heart Rate Service, and install any optional BLE dependencies required by the source build. Visibility in a scan does not prove compatibility.
- **NASA data search unavailable:** Confirm internet access; use local/demo workflows while offline.
- **Desktop window does not launch:** Check WebView2 installation and Windows build logs; use the source/browser launcher for diagnosis.

The repository also includes automated backend/frontend tests and release validation scripts. Passing mocked BLE tests or Linux smoke tests is **not** a substitute for physical Windows/sensor validation.

## Safety, privacy, and limitations

AETHER is a **prototype for exploration, education, and research**, not a clinical monitoring or emergency-response system. PHANTOM outputs are exploratory and must not be used to diagnose illness or make autonomous safety-critical decisions. Demo crew and spacecraft scenarios are synthetic. Sensor acquisition depends on actual hardware and permissions. NASA research catalogs and downloaded datasets have their own provenance, access, and interpretation constraints. Protect any real participant measurements and do not commit personal health databases or secrets to GitHub.

## Scientific resources

- [NASA Space Apps Challenge 2026 — Health Monitoring Software](https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/)
- [NASA Open Science Data Repository](https://osdr.nasa.gov/)
- [NASA Human Research Program](https://www.nasa.gov/hrp/)
- [NASA-STD-3001, Volume 1](https://www.nasa.gov/reference/nasa-std-3001v1/)
- [NASA-STD-3001, Volume 2](https://www.nasa.gov/reference/nasa-std-3001v2/)
- [MMASH research dataset (PhysioNet)](https://physionet.org/content/mmash/1.0.0/)

---

**AETHER — Adaptive Ecosystem for Human Exploration and Resilience.** Developed as a NASA Space Apps Challenge 2026 research prototype. NASA references and public datasets do not imply NASA endorsement.

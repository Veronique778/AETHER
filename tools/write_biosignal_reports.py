from pathlib import Path
import json
r=Path('.')
j=json.loads((r/'validation_1_1/mmash-evaluation.json').read_text(encoding='utf-8'))
rows='\n'.join('| '+x['participant']+' | '+str(x['measurements'])+' | '+f"{x['import_seconds']:.2f}"+' | '+f"{x['analysis_seconds']:.2f}"+' | '+f"{100*x['rr_rejection_rate']:.2f}%"+' | '+f"{100*x['analysis_coverage']:.2f}%"+' | '+f"{100*x['flag_rate']:.2f}%"+' |' for x in j['results'])
docs={
'BIOSIGNAL_IMPLEMENTATION_REPORT.md':'''# AETHER 1.1 — implementation report

Implemented from the supplied AETHER_1_0_DESKTOP_NO_NODE.zip, in an isolated extracted copy. Release date: 2026-11-14.

## Architecture and compatibility

The original React interface, custom WebGL/Canvas renderer, BODY models, spacecraft assets, Python WebView2 launcher and simulation algorithms remain. Both FastAPI and the stdlib desktop server expose additive `/api/biosignals/*` routes through `app/bio_api.py`. Existing API contract/version remains 1.0; health advertises release 1.1 separately. There is no remote service in biosignal acquisition, storage, analysis or export.

New modules: `biosignals.py` (normalized SQLite storage and partial analysis), `mmash.py` (streaming published-schema CSV importer), `ble_sensor.py` (Bleak transport and SIG decoder), `bio_api.py` (shared endpoints). React `BiosignalPage.tsx` provides source selection, import, sensor controls, sessions, charts and exports. `ResearchComparison.tsx` compares an existing synthetic engine run with a separate recording. BODY and PHANTOM explicitly route recording selections to actual persisted records. The original simulation pages remain accessible by selecting Simulation.

## Canonical data contract and safe migration

Migration is additive and idempotent: `bio_sessions`, `bio_measurements`, `bio_analysis`, plus a session/signal/time index. Existing astronaut, measurement, experiment, mission-engine and RECOVERY tables are not altered by biosignal operations. Tables initialize lazily before use. No previous data is dropped; back up the existing SQLite database before applying any release.

`bio_sessions`: UUID, participant ID, source_type (`research`/`live_sensor`), source/device/dataset attribution, UTC creation time, import/recording status, JSON metadata. Research participant IDs are prefixed MMASH and never inserted into astronaut identities.

`bio_measurements`: ID, parent session, numeric analysis time, nullable UTC timestamp, original source timestamp, nullable source timezone, signal, nullable value, explicit unit, nullable sampling_hz, quality, validity, missing status, sensor connection, JSON provenance, processing version. Participant/source are inherited through session ID. File and row identify original input; hashes cover imported source files. Validity is screening, not clinical quality. Unsupported values stay absent. Missing values are NULL, never zero-filled.

MMASH publishes relative day/time without a calendar date or timezone. Its numeric clock is seconds from the start of relative day 1; original days/times are retained, UTC/timezone/sampling frequency remain NULL. No guessed absolute date is introduced. BLE UTC is host notification receipt, not a device clock; RR beat offsets reconstructed backwards from receipt are explicitly estimates. No sensor clock synchronization accuracy is claimed.

## Implemented operations

- MMASH folder and ZIP discovery, participant selection, explicit import confirmation, actual schema validation, streaming parsing and batched inserts. RR seconds convert to milliseconds; HR is derived from supported RR only. ActiGraph HR remains a separate stream; axes retain ActiGraph counts and steps retain counts. TST, efficiency, WASO and dataset sleep fragmentation definitions are preserved.
- Original questionnaires, saliva, identity information and self-report activity code tables are deliberately not ingested. They are not invented physiological channels.
- Imported records include missing/rejected/corrupt statuses. Invalid numeric rows are counted and stored as unavailable corrupt-row records. Out-of-order timestamps are flagged/rejected, not silently repaired. Repeated second-resolution RR timestamps are retained in source-row order.
- No ZIP extraction. Traversal/absolute/drive paths, symbolic links, duplicate members, >10,000 members, >128 MiB per file, >768 MiB total or >2 million session measurements are rejected. Failed imports remove their partial records. An interrupted process can leave an `importing` session; delete it and reimport.
- Bounded min/max chart buckets, historical time cursor, per-channel quality/count/duration, original model selection/X-ray view, PHANTOM window explanations, CSV and JSON summaries, source comparison export, real deletion of session/measurement/analysis rows.
- Live HRS discovery, user-selected connection, actual notifications, quality/contact handling, immediate local persistence, manual reconnect creating a separate session, disconnection clearing current HR, stale-notification status, saved history and reanalysis.

## PHANTOM scientific boundary

Existing multivariate synthetic algorithms are unchanged. Real RR/HR is not mapped to synthetic fatigue, cognition, sleep or workload. The adapter runs an explicitly exploratory univariate HR deviation rule, with fixed first-hour personalized baseline, 5-minute windows, threshold 3.5 robust scale units, median/MAD and a 3 bpm noise floor. At least ten eligible first-hour windows are required; each needs >=20 valid samples, >=240-second span and >=80% valid numeric records. Later windows alone are scored. No adaptation, training or threshold optimization on evaluation participants occurs. The requested multivariate pathway is insufficient_data when real channels do not support its inputs.

RR screening uses 300–2000 ms and >20% local interval-jump checks. Exploratory SDNN/RMSSD need >=100 usable intervals, >=240s span and <=20% rejection; RMSSD needs >=80 adjacent usable pairs. Rejected intervals and gaps are not bridged. HR pulse samples never generate HRV. These rules do not establish normal sinus beats or validated NN intervals.

BODY highlights cardiovascular anatomy only when an actual returned HR analysis window is flagged at the cursor time. It infers no organ damage or health. Cabin exposures are never assigned to Earth research recordings, and recordings never modify crew schedules. Existing CO-ORBIT human approval/validation stays intact.

## Desktop and distribution

Prebuilt `web/frontend/dist-offline` is supplied. End-user startup requires no Node/npm. Python launch: `START_AETHER.bat` (standard Python 3.13 plus WebView2; wheels installed if needed). Free-threaded Python 3.13t is rejected. A copied/broken free-threaded private environment is recreated safely. If packages are installed in a private environment, the GUI relaunches under that interpreter. The only source-wheel exception is proxy_tools, a pure Python pywebview dependency; no Rust/C++ build is needed.

Portable alternative: `dist/AETHER_1_1_PORTABLE/AETHER_1_1.exe`, bundled Python and backend, requires Windows Edge WebView2. Build uses `BUILD_PORTABLE_1_1.bat` and the supplied PyInstaller spec, with prebuilt frontend. No compiler or Node needed for the end user. The legacy Tauri build sources are preserved; new biosignal same-origin UI is verified in the Python/portable WebView2 shells, not in a rebuilt Tauri shell.

## Remaining limitations

WESAD ingestion is explicitly deferred, rather than executing untrusted pickle files or claiming untested synchronization. ECG/BVP/EDA/temperature and chest modalities are not supplied. No physical BLE monitor was tested. Automated fake transport is confined to tests/validation harness. No clinical, astronaut-flight, NASA operational or diagnostic validation is claimed. Import progress is indeterminate while local work runs (no invented completion percentage). Chart buckets show bounds, not every raw point; use CSV for raw samples. Browser CSV construction may consume substantial memory for maximum-size sessions. SQLite deletion removes application records but is not forensic secure erasure. Local storage is not encrypted; the OS account controls filesystem access. These APIs bind locally and reject cross-origin biosignal access; no remote multiuser authentication is provided.
''',
'DATASET_VALIDATION_REPORT.md':'''# AETHER 1.1 — dataset validation

Actual original MMASH 1.0.0 was downloaded from [PhysioNet](https://physionet.org/content/mmash/1.0.0/), DOI [10.13026/cerq-fc86](https://doi.org/10.13026/cerq-fc86). Original MMASH.zip SHA256:

`ef91ee1b36b5849a6366b1918de82686ab278915d33c7f62133f07f741f70726`

This matches PhysioNet's published SHA256SUMS. Recordings are excluded from release archives. Retain Rossi et al. (2020) attribution and MMASH ODC Attribution 1.0 terms. Also cite Rossi et al., A Public Dataset of 24-h Multi-Levels Psycho-Physiological Responses in Young Healthy Adults, Data 5(4), 91, doi:10.3390/data5040091, and the PhysioNet citation listed on the source page.

## Reproduction and original-file results

`python web/backend/validation/evaluate_biosignals.py PATH_TO_MMASH.zip`

Optional plotting dependency: `python -m pip install --only-binary=:all: -r web/backend/requirements-validation.txt`.

The evaluation protocol predeclares user_1, user_10, user_20. There is no fitted model or threshold selection. Each participant's first hour is the personal baseline; only later windows are evaluated. Windows are never randomly split between training and test. This is descriptive evaluation of an exploratory adapter, not validation of synthetic PHANTOM calibration on real humans. No raw recording is bundled.

| Participant | Stored measurements | Import s | Analysis s | RR rejected | Eligible HR windows | Flag rate among scored windows |
|---|---:|---:|---:|---:|---:|---:|
'''+rows+'''

Total original-file measurements imported: 1,420,846 across three participants (includes RR-derived HR, ActiGraph channels and sleep summaries; this is not a count of independent beats or subjects). Runs used temporary SQLite databases and removed records afterwards. Runtime is machine-specific, not an optimization claim.

JSON results record per-channel counts/durations, corrupt and out-of-order rows, source-file hashes, baseline values, analysis coverage, scored-window counts, median adjacent-window HR change, runtime and missing/artifact sensitivity. `mmash-hr-trends.png` is generated by matplotlib from actual executed windows; invalid windows remain gaps. Individual analysis JSONs preserve all evaluated windows and limitations.

The fixed first-hour rule flags about 57.59% of later scored windows for user_20, compared with about 8.8–9.0% for the other two participants. This large interparticipant variation shows why these flags cannot be interpreted as validated risk predictions. Real activity/circadian change, baseline selection and artifacts can contribute.

The executed intervention sets every fifth HR record missing, then adds rejected artifacts every seventeenth record. Under these interventions all three sessions abstained for lack of a sufficient first-hour baseline. This demonstrates conservative missing-data behavior, not resilience or accuracy. These interventions are on the same sessions, not additional independent people. Wilson/binomial confidence intervals are omitted because adjacent within-person windows are dependent and only three people were examined.

## Synthetic comparison

`validation_1_1/synthetic-evaluation.json` was executed separately through the unchanged Mission Systems engine for normal, sleep_loss and noise, seed 42. For sleep_loss the existing engine detector returned TP 29, FP 2, TN 111, FN 5 (precision 0.9355, recall 0.8529, F1 0.8923). Normal yielded 2 flags in 147 negative synthetic samples; noise yielded 3 in 147. These are single seeded synthetic scenarios with injected event labels, not held-out clinical results. The real adapter has a different input contract and cannot be ranked against these metrics without common valid ground truth.

MMASH supplies no event ground truth for the anomaly task. Its reported quantity is flag rate, never false-positive rate. Precision/recall/F1/delay/diagnostic accuracy are therefore not reported for MMASH. No astronaut identity, flight exposure or astronaut validation is inferred.

## WESAD status

[UCI WESAD](https://archive.ics.uci.edu/dataset/465/wesad) documents wrist BVP 64 Hz, EDA/temperature 4 Hz, acceleration 32 Hz and chest signals 700 Hz. No WESAD files were downloaded or tested. Ingestion, synchronization, stress-label evaluation and multimodal analysis are deferred. No unsafe pickle loading, labels-as-features or astronaut-risk claim is implemented.
''',
'BLE_INTEGRATION_REPORT.md':'''# AETHER 1.1 — BLE integration

Supported interface: Bluetooth SIG Heart Rate Service UUID `0000180d-0000-1000-8000-00805f9b34fb`, characteristic `00002a37-0000-1000-8000-00805f9b34fb`. Based on the [SIG HRS specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/HRS_v1.0/out/en/index-en.html) and [BleakClient documentation](https://bleak.readthedocs.io/en/latest/api/client.html).

Optional Python runtime: bleak >=1.1,<3; development tested import with bleak 2.1.1 on standard CPython 3.13.15, Windows x64. `ENABLE_BLE.bat` installs binary wheels in standard Python. Portable build includes BLE dependencies. If the Python launcher uses its private environment, install there with `.aether-venv\\Scripts\\python.exe -m pip install --only-binary=:all: -r web\\backend\\requirements-biosignals.txt`.

A dedicated asyncio thread retains WinRT/Bleak connections between HTTP requests. Discovery returns only advertisements containing HRS. Devices exposing HRS without advertising its UUID are not discovered by this filter. User selection is required. No universal watch/brand support is claimed.

Packets support unsigned 8/16-bit HR, optional energy field (parsed, not interpreted as battery), supported contact flags, multiple RR intervals and exact conversion of 1/1024 seconds to milliseconds. Unsupported contact is null. Truncated, odd-length and extra-field packets fail explicitly. Notifications are stored immediately with host UTC receipt time and provenance. Physiologically implausible numbers or no-contact packets are not shown as valid current HR. No battery value is fabricated.

Disconnect clears current HR and saves the session. Old callbacks are rejected by connection-generation tokens. Manual reconnect creates a new session; it does not bridge disconnected gaps. After 15 seconds with no notification, the displayed measurement becomes unavailable/stale even if the connection remains established. Duration stops on disconnect. Stop/save/disconnect and recorded-session replay/export are implemented. Restart closes live connection state; previously persisted sessions remain.

Automated tests execute decoding, fake scanner/client -> real acquisition adapter -> SQLite -> graph response -> supported analysis, absent radio errors, no-contact handling, physical-disconnect callback, stale callback rejection and manual reconnect. Browser integration also runs the fake transport through actual UI/HTTP/SQLite/charts. Fake transport is confined to test code and `validation/biosignal_test_server.py`; production runtime never selects it or substitutes simulated sensor measurements.

**Physical sensor status: NOT TESTED.** No compatible monitor was available. No real BLE connection, stream, RF reconnection behavior, permissions flow, packet timing accuracy or device interoperability is claimed. These remain release verification items on actual Windows Bluetooth hardware. Helpful errors cover missing library, missing radio, permissions, connection failure and unsupported profile/subscription. No scan was used as evidence of a real physiological measurement.
''',
'BACKEND_TEST_REPORT.md':'''# AETHER 1.1 — executed tests

Windows x64, standard CPython 3.13.15. Source baseline was established before changes. An initial root pytest invocation without PYTHONPATH had 17 import-collection errors; correcting the execution context resolved them without changing scientific code.

## Baseline

`$env:PYTHONPATH=(Resolve-Path web/backend).Path; python -m pytest web/backend/tests desktop/tests/test_sidecar.py -q`

**187 passed, 4 skipped, 3 subtests passed**, 152.29s. The four frontend parity tests were skipped before frontend development dependencies were installed.

## Upgraded suite

Same suite, with frontend dependencies present and UTF-8 subprocess decoding fixed in `test_parity.py`:

**219 passed, 0 failed, 0 skipped, 3 subtests passed**, 217.77s. Includes all original simulation, API, CO-ORBIT validation, environment separation and RECOVERY tests, plus 28 new biosignal tests. See `validation_1_1/full-backend-tests.txt`.

The first upgraded run exposed Windows default-encoding corruption in the newly enabled parity tests (3 failed, 216 passed). Explicit UTF-8 decoding fixed that test-harness issue; no algorithm or expected scientific value was changed.

Final focused rerun after biosignal invalid-ZIP and health metadata changes: `python -m pytest web/backend/tests/test_biosignals.py web/backend/tests/test_api.py -q` — **31 passed**, 13.47s. Known RR sequences test exact RMSSD and sample SDNN; pulse-only samples never produce HRV. Tests cover missing/corrupt/out-of-order values, day boundaries, units, provenance, consent, safe ZIPs, schema failures/rollback, SQLite reopen/delete, insufficient baselines, fixed-baseline flags, SIG packets, fake transport, disconnect/reconnect, no radio, same-origin privacy and FastAPI/stdlib parity.

## Frontend and end-to-end

Developer-only commands: `npm ci`, `npm run typecheck`, `npm test`, `node scripts/build-offline.mjs --mode live`. Typecheck and build pass; **18 frontend unit tests pass**. No Node/npm is used at end-user startup.

`node web/frontend/tests/biosignals-e2e.cjs` uses an actual local server and Edge headless only as a development test runner. End-user application is native WebView2. Set AETHER_TEST_NODE_MODULES only if Playwright is installed outside normal node_modules. Original MMASH.zip must be at the documented private validation path, or adjust the test path to your local file.

The E2E run verifies real MMASH import -> actual SQLite -> feature extraction -> PHANTOM -> recorded BODY 3D; full backend restart and reopening; real JSON download; actual deletion; no live HR when disconnected; test-only fake BLE -> real adapter/SQLite/graph/insufficient analysis; stop/save/disconnect; existing Mission Lab reachability. Machine-readable checks and zero runtime JS errors are in `frontend-e2e.json`. Earlier test failures were corrected locator/environment issues (application role on the 3D viewport; locally installed Edge used when bundled Chromium was unavailable).

Existing backend tests execute actual seeded synthetic scenarios and CO-ORBIT proposal validation/apply/reject, independently of frontend reachability. A separate synthetic engine experiment (normal, sleep_loss, noise; seed42) is saved in `synthetic-evaluation.json`.

## Desktop, executable and performance

`python desktop_launch.py --smoke-test` passes: real backend, precompiled interface and original spacecraft GLB served without a Node build. The native AETHER 1.1 WebView2 window and its actual Windows file picker were observed using computer-use. A standalone Windows x64 PyInstaller portable EXE is built; its smoke check is launched with PATH restricted to Windows System32 and no PYTHONPATH. See portable-smoke.json for frozen=true and actual backend/frontend/GLB verification. This is not a clean-Windows-VM certification; WebView2 is installed on this machine.

Actual MMASH import and analysis times, quality/coverage and perturbation results are recorded in `mmash-evaluation.json`; no metrics are fabricated. WESAD and physical BLE are not validated. Original input GLBs are checked byte-for-byte during release packaging.
''',
'AETHER_1_1_DEMO.md':'''# AETHER 1.1 — NASA Space Apps demonstration

## Start

Extract the entire ZIP. Portable option: run `dist/AETHER_1_1_PORTABLE/AETHER_1_1.exe`. Python option: run `START_AETHER.bat` with standard Python 3.13 and Edge WebView2. No Node, Rust or Visual Studio Build Tools is required on the end-user computer. This is a research prototype, not NASA operational or clinical software.

## 1. Synthetic mission

Select **Data origin -> Simulation**. Open MISSION LAB -> Mission Systems engine, select a scenario and reproducible seed and run it. Explore BODY, PHANTOM, SYMBIOSIS, CO-ORBIT and the original spacecraft twin. Say explicitly: these are simulated crew and synthetic mission conditions. Human approval and validation control CO-ORBIT proposals.

## 2. Authentic human recording

Download [MMASH 1.0.0](https://physionet.org/content/mmash/1.0.0/) yourself and retain its attribution. The demo release does not bundle people's recordings. Open BIOSIGNALS (or Research Data from Data origin). Choose ZIP/folder, or enter its local path; inspect participants; select a participant; confirm local import/terms; import. Wait for local processing. The completed session must list real measurement counts and provenance hashes.

Select heart_rate, rr_interval, separate ActiGraph HR/axes/steps or sleep summaries. Inspect units and valid/rejected/missing counts. MMASH time is relative recording day: no absolute UTC date is invented. The participant is an Earth research participant, not an astronaut.

## 3. PHANTOM and BODY

Run supported PHANTOM analysis. Explain the fixed first-hour personal baseline and five-minute windows. If the baseline is too short/noisy, the correct output is insufficient_data. Available HR is analyzed by an exploratory univariate adapter; no fatigue/cognition/workload channels are fabricated. HRV is only attempted from screened RR, with limitations and rejected counts.

Open in BODY. Rotate and zoom the original 3D model, optionally switch models/X-ray, move the historical cursor and inspect actual recorded chart bounds. Run analysis in this view to show time-traceable cardiovascular flags. They do not imply organ damage. Unknown channels stay unavailable.

Export the research JSON summary and CSV. Restart the application and reopen the session from Local session history. To remove it, disconnect any active recording, then Delete session -> Confirm deletion. This removes actual records and stored analysis, not merely a visual item.

## 4. Research comparison

With a synthetic engine run and a real recording selected, open MISSION LAB and use Compare selected sources. Compare source descriptions, sampling policies, HR characteristics, synthetic event evaluation and real flag rate. Export the comparison. Never assign synthetic cabin CO₂/radiation to the Earth participant, and never call a real flag rate a false-positive rate.

## 5. Optional physical BLE

Use a monitor that actually advertises standard BLE Heart Rate Service. Python users may run ENABLE_BLE.bat first; portable already bundles Bleak. Open Live Sensors -> Scan -> select Connect. Only after real notifications arrive should HR and sample time appear. Record, stop/save/disconnect, reopen the saved session, and run analysis when enough history exists. On disconnect current HR becomes unavailable; no simulation appears automatically. Real hardware interoperability still needs testing. Automated demo fixtures are not a real sensor demonstration.

## Scientific close

MMASH original-file evaluation used three participants. Interparticipant flag rates differ strongly, so the detector remains uncalibrated. Synthetic event performance is not transferable to astronaut/clinical accuracy. WESAD ingestion and physical BLE validation are deferred. All physiological data stays on the local machine by default.
''',
'RELEASE_CHECKLIST.md':'''# AETHER 1.1 — release checklist

- [x] Source archive audited; existing baseline recorded before edits.
- [x] Original simulation algorithms/routes retained; 219 backend tests pass.
- [x] Prebuilt React UI and original GLBs retained; Node-free startup smoke passes.
- [x] Standard Python 3.13, not 3.13t; private-runtime GUI relaunch fixed.
- [x] Canonical normalized local data contract; additive SQLite schema; RECOVERY preserved.
- [x] Original MMASH archive SHA256 matches official PhysioNet checksum.
- [x] Real import of user_1, user_10, user_20: 1,420,846 canonical records.
- [x] Correct seconds->ms conversion, relative recording days, explicit missing/corrupt quality.
- [x] Research session isolation, source attribution, local confirmation, safe ZIP limits.
- [x] Actual SQLite/chart/PHANTOM/BODY pipeline; no fabricated unavailable channels.
- [x] HRV from RR only, sufficient-window checks, explicit uncalibrated partial detector.
- [x] BLE SIG decoder and real Bleak adapter; test-only fake transport E2E.
- [x] Disconnect/reconnect/no-radio tests; no synthetic substitution in sensor mode.
- [x] Actual process restart, reopening, deletion, CSV API and JSON UI export.
- [x] Independent original-MMASH evaluation, perturbations, runtime and plotted results.
- [x] Synthetic evaluation retained and separately executed; no real FPR claim.
- [x] Comparison UI keeps mission conditions separate; no automatic schedule changes.
- [x] Frontend typecheck, 18 unit tests and backend-connected browser E2E pass.
- [x] Native WebView2 application and native MMASH file picker observed on Windows.
- [x] Windows x64 portable executable built; frozen backend/UI/GLB smoke passed with no Python/Node PATH.
- [ ] Clean Windows machine test with WebView2 prerequisites and unsigned executable policies.
- [ ] Physical HRS monitor acquisition, contact quality, permissions, disconnect and reconnect.
- [ ] Longer/more diverse real recordings and scientifically justified calibration/holdout evaluation.
- [ ] WESAD ingestion and synchronization (explicitly deferred).
- [ ] Clinical, astronaut-flight or NASA operational validation (not claimed).

Full ZIP includes sources and precompiled runtime; patch includes changed/new distributable files relative to the original ZIP. Broken machine-specific virtual environments, generated caches/build tooling and validation raw recordings are excluded. See RELEASE_MANIFEST.json for exact hashes and exclusions. Apply a patch to an extracted copy; retain your existing database and remove a copied `.aether-venv` if its interpreter is free-threaded or machine-specific. The launcher checks this too.
''',
'README_AETHER_1_1.md':'''# AETHER 1.1 — Real Biosignal Intelligence

**Portable Windows:** extract everything, then run `dist/AETHER_1_1_PORTABLE/AETHER_1_1.exe` (Edge WebView2 required). No Python or Node installation needed for the portable build.

**Python Windows:** run `START_AETHER.bat` with standard Python 3.13. Prebuilt frontend and 3D assets are included. No Node.js required. Optional sensor library: `ENABLE_BLE.bat`.

Open BIOSIGNALS to import a local MMASH ZIP/folder or connect a compatible standard BLE HR monitor. Real sessions are stored locally, independent of the simulated astronaut database. BODY and PHANTOM support selected recordings; Simulation restores original mission workflows.

Original MMASH files were tested for three participants. Physical BLE hardware is unverified and WESAD ingestion is deferred. Real-signal PHANTOM analysis is an exploratory HR deviation adapter, not clinical or astronaut-risk validation. See the implementation, dataset, BLE and test reports, demo and release checklist.
'''
}
for name,content in docs.items():(r/name).write_text(content,encoding='utf-8')
print('Wrote',len(docs),'release documents')

"""NASA OSDR public research data: discovery, verified import, provenance (AETHER 1.4).

Research datasets are NOT astronaut telemetry. They are never written into the
synthetic mission tables and never used to fit or calibrate PHANTOM thresholds.

Evidence classes (``classify``):
  human_in_vivo     - samples/measurements from human subjects (e.g. Inspiration4 crew)
  human_cell_culture- human-derived cells/tissue grown in vitro
  animal            - rodent and other model organisms
  plant / microbial - non-animal organisms
  unclassified      - metadata insufficient; treated as not human

Data layers: ``clinical_physiological`` (clinical chemistry, immunoassay,
physiology) vs ``molecular`` (sequencing, omics). Only human_in_vivo +
clinical_physiological imports from a verified NASA download are offered to
PHANTOM, and only as read-only reference context.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import math
import os
import re
import statistics
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from . import db

VERSION = 'aether-nasa-osdr-1.4'
NASA_DATA_DIR = Path(os.environ.get('AETHER_NASA_DATA_DIR', str(db.DB_PATH.parent / 'nasa_osdr')))
CACHE = NASA_DATA_DIR / 'catalog_cache.json'
IMPORT_HISTORY = NASA_DATA_DIR / 'verified_imports.json'
OFFICIAL_HOST = 'osdr.nasa.gov'
BASE = 'https://' + OFFICIAL_HOST
# Test-only mirror (local fixture server). When set, every record is labelled
# as NOT NASA so a fixture can never be presented as an official download.
TEST_MIRROR = os.environ.get('AETHER_OSDR_TEST_MIRROR', '').rstrip('/')
MAX_VERIFIED_CSV = 3_000_000
MAX_HISTORY = 60
SUPPORTED_FORMATS = {'.csv': ',', '.tsv': '\t'}
MISSING_TOKENS = {'', 'na', 'n/a', 'nan', 'null', 'none', '-', '--', 'nd', 'n.d.', '.', 'missing'}
_history_lock = threading.RLock()

HUMAN = {'homo sapiens', 'human'}
ANIMAL_HINTS = ('mus musculus', 'rattus', 'drosophila', 'caenorhabditis', 'danio', 'xenopus', 'macaca',
                'oryzias', 'sus scrofa', 'gallus', 'mouse', 'rat', 'rodent')
PLANT_HINTS = ('arabidopsis', 'oryza', 'brassica', 'zea mays', 'triticum', 'solanum', 'plant')
MICROBE_HINTS = ('microbiota', 'escherichia', 'bacillus', 'staphylococcus', 'saccharomyces', 'pseudomonas',
                 'bacteria', 'fungi', 'virus', 'microb', 'candida', 'streptococcus')
CELL_HINTS = ('cell line', 'cell culture', 'cultured', 'in vitro', 'organoid', 'ipsc', 'induced pluripotent',
              'huvec', 'fibroblast culture')
MOLECULAR_HINTS = ('sequencing', 'transcription profiling', 'rna-seq', 'proteom', 'metabolom', 'metagenom',
                   'methylation', 'genome', 'chromatin', 'atac', 'epigen', 'microarray', 'single-cell',
                   'protein-dna', 'lipidom', 'mass spectrometry')
CLINICAL_HINTS = ('metabolic panel', 'blood count', 'immunoassay', 'cytokine', 'clinical chemistry', 'serum',
                  'plasma', 'urine', 'physiolog', 'heart rate', 'blood pressure', 'ultrasound', 'cognit',
                  'vital', 'cmp', 'cbc', 'biochem', 'hematolog')


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _base() -> str:
    return TEST_MIRROR or BASE


def source_label() -> str:
    return 'TEST FIXTURE MIRROR — NOT NASA DATA' if TEST_MIRROR else 'NASA Open Science Data Repository (osdr.nasa.gov)'


def _get_json(path: str) -> dict:
    req = urllib.request.Request(_base() + path, headers={'User-Agent': 'AETHER-Research-Prototype/1.4',
                                                           'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError('OSDR metadata response exceeds 8 MB safety limit')
    return json.loads(raw)


def _text(value) -> str:
    """Flatten OSDR metadata values (str / list / dict) into one readable string."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_text(v) for v in value]
        return '; '.join(dict.fromkeys(p for p in parts if p))
    if isinstance(value, dict):
        for key in ('Name', 'name', 'value', 'Value', 'term', 'annotationValue'):
            if key in value:
                return _text(value[key])
        return '; '.join(_text(v) for v in value.values() if _text(v))
    return str(value)


def classify(meta: dict) -> dict:
    """Classify an OSDR study from its metadata. Never guesses 'human' by default."""
    organism = _text(meta.get('organism'))
    # Accepts raw OSDR search keys and AETHER's own summarised keys.
    material = _text(meta.get('Material Type') or meta.get('material_type'))
    measurement = _text(meta.get('Study Assay Measurement Type') or meta.get('measurement_types'))
    technology = _text(meta.get('Study Assay Technology Type') or meta.get('technology_types'))
    if organism.startswith('not stated'):
        organism = ''
    org_l, mat_l = organism.lower(), material.lower()
    assay_l = (measurement + ' ' + technology).lower()
    org_parts = {p.strip() for p in org_l.split(';') if p.strip()}
    if org_parts and org_parts <= HUMAN:
        evidence = 'human_cell_culture' if any(h in mat_l or h in assay_l for h in CELL_HINTS) else 'human_in_vivo'
    elif any(h in org_l for h in ANIMAL_HINTS):
        evidence = 'animal'
    elif any(h in org_l for h in PLANT_HINTS):
        evidence = 'plant'
    elif any(h in org_l for h in MICROBE_HINTS):
        evidence = 'microbial'
    elif org_parts & HUMAN:
        evidence = 'mixed_including_human'
    else:
        evidence = 'unclassified'
    if any(h in assay_l for h in MOLECULAR_HINTS):
        layer = 'molecular'
    elif any(h in assay_l or h in mat_l for h in CLINICAL_HINTS):
        layer = 'clinical_physiological'
    else:
        layer = 'unclassified'
    labels = {
        'human_in_vivo': 'Human research subjects (in vivo samples) — not live crew telemetry',
        'human_cell_culture': 'Human-derived cells in vitro — not whole-body human measurements',
        'animal': 'Animal model — never presented as human astronaut data',
        'plant': 'Plant study — not human data', 'microbial': 'Microbial study — not human data',
        'mixed_including_human': 'Mixed organisms — human rows must be separated before any human use',
        'unclassified': 'Organism not identified in metadata — treated as not human',
    }
    return {'organism': organism or 'not stated in OSDR metadata', 'material_type': material or None,
            'measurement_types': measurement or None, 'technology_types': technology or None,
            'evidence_class': evidence, 'evidence_label': labels[evidence], 'data_layer': layer}


def phantom_eligibility(entry: dict) -> dict:
    """Whether an import may appear as read-only PHANTOM reference context."""
    reasons = []
    if entry.get('source_type') != 'verified_public_nasa_osdr_csv':
        reasons.append('source is not a verified download from osdr.nasa.gov')
    if entry.get('evidence_class') != 'human_in_vivo':
        reasons.append(f"evidence class is {entry.get('evidence_class', 'unknown')}, not human in vivo")
    if entry.get('data_layer') != 'clinical_physiological':
        reasons.append(f"data layer is {entry.get('data_layer', 'unknown')}, not clinical/physiological")
    eligible = not reasons
    return {'eligible': eligible,
            'use': 'read-only reference context (no threshold calibration, no crew scoring)' if eligible else 'NASA Data Lab only',
            'reasons': reasons or ['human in vivo clinical/physiological data from a verified NASA download']}


def study_url(accession: str) -> str:
    return f'https://osdr.nasa.gov/bio/repo/data/studies/{accession}' if re.fullmatch(r'OSD-\d{1,6}', accession or '') else BASE


def _summarize(payload: dict) -> list:
    """Understand both older and nested NASA OSDR search result shapes.

    Never fill a missing accession/title with invented study metadata.
    """
    if not isinstance(payload, dict):
        return []
    hits = payload.get('hits', [])
    if isinstance(hits, dict):
        hits = hits.get('hits', [])
    if not isinstance(hits, list):
        return []
    out, seen = [], set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        data = hit.get('_source', hit)
        if not isinstance(data, dict):
            continue
        accession = str(data.get('Accession') or data.get('accession') or data.get('id') or '').strip()
        title = str(data.get('Study Title') or data.get('title') or data.get('Study Title.raw') or '').strip()[:250]
        if not accession and not title:
            continue
        if accession and accession in seen:
            continue
        if accession:
            seen.add(accession)
        record = {'accession': accession, 'title': title}
        extra = classify(data)
        if any(data.get(k) for k in ('organism', 'Material Type', 'Study Assay Measurement Type')):
            record.update(extra)
            record.update({'mission': _text(data.get('Mission')) or None,
                           'project': _text(data.get('Project Title') or data.get('Project Identifier')) or None,
                           'release_date': _text(data.get('Study Public Release Date')) or None,
                           'official_url': study_url(accession)})
        out.append(record)
        if len(out) == 12:
            break
    return out


def _read_cache() -> dict:
    try:
        data = json.loads(CACHE.read_text(encoding='utf-8'))
        if isinstance(data, dict) and 'query' in data and 'by_query' not in data:  # 1.3 single-entry format
            data = {'by_query': {data['query']: data}}
        return data if isinstance(data, dict) and isinstance(data.get('by_query'), dict) else {'by_query': {}}
    except (OSError, ValueError):
        return {'by_query': {}}


def catalog(term: str = 'human physiology', refresh: bool = False) -> dict:
    term = (term or '').strip()[:90] or 'human physiology'
    cache = _read_cache()
    cached = cache['by_query'].get(term)
    if not refresh and cached:
        return {**cached, 'cached': True}
    path = '/osdr/data/search?' + urllib.parse.urlencode({'term': term, 'from': 0, 'size': 12, 'type': 'cgene'})
    try:
        response = _get_json(path)
    except Exception as exc:  # network, TLS, proxy refusal, malformed JSON
        reason = f'{type(exc).__name__}: {exc}'[:200]
        if cached:
            return {**cached, 'cached': True, 'warning': f'NASA OSDR unreachable ({reason}); showing metadata cached at {cached.get("retrieved_at_utc")}.'}
        return {'query': term, 'source': _base() + path, 'available': False, 'cached': False, 'error': reason,
                'warning': 'NASA OSDR is unreachable. Connect to the internet and refresh. No studies are invented offline.',
                'studies': []}
    result = {'query': term, 'source': _base() + path, 'source_label': source_label(), 'available': True,
              'cached': False, 'retrieved_at_utc': _now(), 'studies': _summarize(response),
              'note': 'Real NASA research metadata, NOT live measurements. Organism and data layer come from OSDR metadata.'}
    cache['by_query'][term] = result
    cache['by_query'] = dict(list(cache['by_query'].items())[-20:])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix('.tmp')
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(CACHE)
    return result


def study_metadata(study_id: int) -> dict:
    """Study-level metadata (organism, assays, mission) via the OSDR search API.

    Returns a record with ``available: False`` instead of inventing fields.
    """
    accession = f'OSD-{study_id}'
    try:
        payload = _get_json('/osdr/data/search?' + urllib.parse.urlencode(
            {'term': accession, 'from': 0, 'size': 25, 'type': 'cgene'}))
    except Exception as exc:
        return {'accession': accession, 'available': False, 'error': f'{type(exc).__name__}'}
    for study in _summarize(payload):
        if study.get('accession') == accession:
            return {**study, 'available': True}
    return {'accession': accession, 'available': False, 'error': 'study not returned by OSDR search'}


def _nasa_file_url(path) -> str | None:
    """Only link to official OSDR HTTPS downloads, never untrusted hosts."""
    if not isinstance(path, str) or not path or '\\' in path:
        return None
    base = _base()
    if path.startswith('/') and not path.startswith('//'):
        target = base + path
    elif path.startswith(base + '/'):
        target = path
    else:
        return None
    parsed = urllib.parse.urlsplit(target)
    expected = urllib.parse.urlsplit(base)
    if parsed.scheme != expected.scheme or parsed.hostname != expected.hostname or parsed.port != expected.port \
            or parsed.username or parsed.password:
        return None
    if not TEST_MIRROR and (parsed.scheme != 'https' or parsed.hostname != OFFICIAL_HOST):
        return None
    return target


def file_format(name: str) -> dict:
    ext = Path(name or '').suffix.lower()
    if ext in SUPPORTED_FORMATS:
        return {'format': ext[1:].upper(), 'supported': True, 'parser': 'UTF-8 delimited text, header row required'}
    reasons = {'.xlsx': 'Excel workbook: not parsed (no spreadsheet engine is bundled); export the sheet to CSV.',
               '.xls': 'Legacy Excel: not parsed; export to CSV.',
               '.zip': 'Archive (often ISA-Tab metadata): not extracted by AETHER.',
               '.txt': 'Free-form text: delimiter and header not guaranteed; not parsed.',
               '.h5': 'HDF5 omics matrix: not parsed.', '.fastq': 'Raw sequence reads: out of scope.',
               '.gz': 'Compressed file: not decompressed by AETHER.', '.bam': 'Alignment file: out of scope.'}
    return {'format': ext[1:].upper() or 'unknown', 'supported': False,
            'parser': reasons.get(ext, 'Format not implemented or tested in AETHER 1.4.')}


def files(study_id: int) -> dict:
    if not isinstance(study_id, int) or not 1 <= study_id <= 100000:
        raise ValueError('Invalid OSDR study ID')
    result = _get_json(f'/osdr/data/osd/files/{study_id}')
    entries = result.get('studies', {}).get(f'OSD-{study_id}', {}).get('study_files', [])
    listed = []
    for x in entries:
        if not isinstance(x, dict):
            continue
        name = str(x.get('file_name') or '')
        listed.append({'name': name, 'category': x.get('category'), 'size_bytes': x.get('file_size'),
                       'download_url': _nasa_file_url(x.get('remote_url')),
                       'restricted': bool(x.get('restricted')), **file_format(name)})
    return {'study': f'OSD-{study_id}', 'files': listed, 'source': f'{_base()}/osdr/data/osd/files/{study_id}',
            'source_label': source_label(), 'official_url': study_url(f'OSD-{study_id}'),
            'note': 'File catalog only. CSV/TSV can be imported; other formats are listed with the reason they are not parsed.'}


# ---------------------------------------------------------------- numeric parsing
_UNIT_RX = re.compile(r'[\(\[]\s*([^()\[\]]{1,24})\s*[\)\]]\s*$')
_TIMEPOINT_RX = re.compile(r'(?<![A-Za-z0-9])(L|R|FD)\s*([-+]?)\s*(\d{1,4})(?![0-9])')
_SUBJECT_RX = re.compile(r'(?<![A-Za-z0-9])(C\d{3})(?![0-9])')


def unit_from_header(column: str) -> str | None:
    m = _UNIT_RX.search(column or '')
    return m.group(1).strip() if m else None


def timepoint(label: str) -> dict | None:
    """Parse mission timepoints such as L-92, FD2, R+1 from a sample label.

    L = days before launch, FD = flight day, R = days after return. Labels that
    do not contain such a token return None (never guessed).
    """
    m = _TIMEPOINT_RX.search(label or '')
    if not m:
        return None
    kind, sign, number = m.group(1), m.group(2), int(m.group(3))
    phase = {'L': 'pre-flight', 'FD': 'in-flight', 'R': 'post-flight'}[kind]
    offset = -number if kind == 'L' else number
    token = f'L-{number}' if kind == 'L' else (f'FD{number}' if kind == 'FD' else f'R+{number}')
    return {'token': token, 'phase': phase, 'day_offset': offset, 'reference': 'launch' if kind == 'L' else ('flight' if kind == 'FD' else 'return')}


def _describe(values: list[float]) -> dict:
    return {'count': len(values), 'mean': round(statistics.mean(values), 5),
            'median': round(statistics.median(values), 5), 'minimum': min(values), 'maximum': max(values),
            'std_dev': round(statistics.stdev(values), 5) if len(values) > 1 else None}


def summarize_csv(csv_text: str, column: str, label_column: str = '', delimiter: str = ',') -> dict:
    """Descriptive statistics on explicitly imported research CSV values (not diagnoses).

    Missing tokens and non-numeric text (e.g. censored '<0.5') are excluded and
    counted - never imputed. No unit conversion is performed.
    """
    if len(csv_text.encode('utf-8')) > MAX_VERIFIED_CSV:
        raise ValueError('CSV exceeds 3 MB')
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)
    if not reader.fieldnames or column not in reader.fieldnames:
        raise ValueError('Column not present in CSV')
    if label_column and label_column not in reader.fieldnames:
        raise ValueError('Label column not present in CSV')
    values, rows, missing, text, nonfinite = [], 0, 0, 0, 0
    examples: list[str] = []
    groups: dict[str, list[float]] = {}
    group_meta: dict[str, dict] = {}
    subjects: set[str] = set()
    unlabelled = 0
    for row in reader:
        rows += 1
        if rows > 200_000:
            raise ValueError('CSV exceeds 200 000 rows')
        raw = (row.get(column) or '').strip()
        if raw.lower() in MISSING_TOKENS:
            missing += 1
            continue
        try:
            val = float(raw.replace(',', '')) if re.fullmatch(r'[-+]?\d{1,3}(,\d{3})+(\.\d+)?', raw) else float(raw)
        except ValueError:
            text += 1
            if len(examples) < 5 and raw not in examples:
                examples.append(raw[:24])
            continue
        if not math.isfinite(val):
            nonfinite += 1
            continue
        values.append(val)
        if label_column:
            label = row.get(label_column) or ''
            tp = timepoint(label)
            sm = _SUBJECT_RX.search(label)
            if sm:
                subjects.add(sm.group(1))
            if tp:
                groups.setdefault(tp['token'], []).append(val)
                group_meta[tp['token']] = tp
            else:
                unlabelled += 1
    if not values:
        raise ValueError('No valid numeric measurements')
    result = {'column': column, **_describe(values), 'rows_read': rows,
              'missing_values': {'missing_tokens': missing, 'non_numeric_or_censored': text,
                                 'non_finite': nonfinite, 'non_numeric_examples': examples,
                                 'policy': 'excluded and counted; no imputation, no detection-limit substitution'},
              'unit': unit_from_header(column) or 'not stated in file header (not inferred)',
              'origin': 'imported_research_csv', 'note': 'Descriptive statistics only; not astronaut telemetry.'}
    if label_column:
        series = sorted(({**group_meta[k], **_describe(v)} for k, v in groups.items()), key=lambda g: g['day_offset'] + (0 if g['phase'] != 'post-flight' else 100000))
        result['timepoints'] = {'label_column': label_column, 'groups': series, 'unlabelled_values': unlabelled,
                                'subjects_detected': sorted(subjects),
                                'note': 'Timepoints parsed from sample labels (L-n before launch, FDn in flight, R+n after return). '
                                        'Group statistics pool subjects; small n — descriptive only.'}
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('NASA file redirected; re-check its official dataset download link')


def _download_verified_csv(official_url: str) -> bytes:
    """Fetch only a file URL published by NASA OSDR, with strict 3 MB limit.

    Redirects are refused (SSRF defence). Verification means: listed by the
    official file catalog, fetched over HTTPS from osdr.nasa.gov, hashed.
    """
    valid = _nasa_file_url(official_url)
    if not valid or valid != official_url:
        raise ValueError('Only NASA OSDR HTTPS downloads are supported')
    req = urllib.request.Request(valid, headers={'User-Agent': 'AETHER-Research-Prototype/1.4',
                                                  'Accept': 'text/csv,text/plain,*/*'})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(req, timeout=20) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname != urllib.parse.urlsplit(_base()).hostname:
            raise ValueError('NASA source verification failed')
        raw_len = response.headers.get('Content-Length')
        if raw_len and raw_len.isdigit() and int(raw_len) > MAX_VERIFIED_CSV:
            raise ValueError('NASA CSV exceeds 3 MB safety limit')
        payload = response.read(MAX_VERIFIED_CSV + 1)
    if len(payload) > MAX_VERIFIED_CSV:
        raise ValueError('NASA CSV exceeds 3 MB safety limit')
    return payload


def _verified_history() -> list:
    try:
        data = json.loads(IMPORT_HISTORY.read_text(encoding='utf-8'))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _with_eligibility(entry: dict) -> dict:
    entry = dict(entry)
    entry.setdefault('import_id', hashlib.sha256(f"{entry.get('sha256')}|{entry.get('column')}|{entry.get('label_column', '')}".encode()).hexdigest()[:16])
    entry['phantom_reference'] = phantom_eligibility(entry)
    return entry


def imports() -> dict:
    """Local log of NASA research imports (provenance + descriptive statistics only)."""
    with _history_lock:
        return {'imports': [_with_eligibility(e) for e in _verified_history()[-MAX_HISTORY:]], 'stored_locally': True,
                'storage': str(IMPORT_HISTORY.name), 'source_label': source_label()}


def reference_context() -> dict:
    """Imports PHANTOM may show as read-only context. Never used to fit thresholds."""
    eligible = [e for e in imports()['imports'] if e['phantom_reference']['eligible']]
    return {'references': eligible, 'count': len(eligible),
            'policy': 'Only verified NASA OSDR downloads of human in vivo clinical/physiological data are listed. '
                      'They are shown beside PHANTOM output for context and are not used to calibrate thresholds, '
                      'baselines or crew scores. Animal, cell-culture and molecular studies stay in NASA Data Lab.'}


def _decode(payload: bytes) -> str:
    try:
        return payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('File is not UTF-8 text; download and inspect it manually') from exc


def _header(content: str, delimiter: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    columns = reader.fieldnames or []
    if not columns or len(columns) > 400 or len(set(columns)) != len(columns):
        raise ValueError('CSV lacks a usable unique-column header')
    preview = []
    for row in reader:
        preview.append({k: (v or '')[:60] for k, v in row.items() if k is not None})
        if len(preview) == 3:
            break
    return columns, preview


def _numeric_columns(content: str, delimiter: str, columns: list[str]) -> list[str]:
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    counts = {c: 0 for c in columns}
    for i, row in enumerate(reader):
        for c in columns:
            try:
                if math.isfinite(float((row.get(c) or '').strip())):
                    counts[c] += 1
            except ValueError:
                pass
        if i >= 200:
            break
    return [c for c in columns if counts[c] > 0]


def _save(record: dict) -> None:
    with _history_lock:
        IMPORT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        entries = _verified_history()
        key = (record['sha256'], record['study'], record['column'], record.get('label_column', ''))
        entries = [e for e in entries if (e.get('sha256'), e.get('study'), e.get('column'), e.get('label_column', '')) != key]
        entries = (entries + [record])[-MAX_HISTORY:]
        staging = IMPORT_HISTORY.with_suffix('.tmp')
        staging.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        staging.replace(IMPORT_HISTORY)


def _analyse(content: str, delimiter: str, provenance: dict, column: str, label_column: str) -> dict:
    columns, preview = _header(content, delimiter)
    result = {'columns': columns, 'numeric_columns': _numeric_columns(content, delimiter, columns),
              'preview': preview, 'provenance': provenance, 'phantom_reference': phantom_eligibility(provenance)}
    if column:
        summary = summarize_csv(content, column, label_column, delimiter)
        steps = list(provenance.get('preprocessing', [])) + [
            f'select numeric column "{column}"',
            'exclude missing tokens ' + '/'.join(sorted(t for t in MISSING_TOKENS if t)) + ' and non-numeric/censored text (counted, not imputed)',
            'exclude non-finite values', 'no unit conversion, no outlier removal, no smoothing',
            'compute count, mean, median, min, max, sample SD (Python statistics module)']
        if label_column:
            steps.append(f'parse L-/FD/R+ timepoint tokens from "{label_column}"; pool subjects per timepoint')
        record = {**provenance, 'column': column, 'label_column': label_column, 'summary': summary,
                  'unit': summary['unit'], 'preprocessing': steps, 'processing_version': VERSION}
        record = _with_eligibility(record)
        _save(record)
        result.update(summary=summary, preprocessing=steps, import_id=record['import_id'],
                      phantom_reference=record['phantom_reference'], saved_to_local_history=True)
    return result


def verified_csv(study_id: int, filename: str, column: str = '', label_column: str = '') -> dict:
    """Read an OSDR-listed public CSV/TSV, compute stats and record provenance.

    The filename is checked against an independently retrieved NASA file
    catalog; user-supplied URLs are never accepted. First call with column=''
    to inspect the header.
    """
    if not isinstance(study_id, int) or isinstance(study_id, bool) or not 1 <= study_id <= 100000:
        raise ValueError('Invalid NASA OSDR study ID')
    if not isinstance(filename, str) or not filename or len(filename) > 300 or '/' in filename or '\\' in filename:
        raise ValueError('Choose a file from the official NASA study file list')
    fmt = file_format(filename)
    if not fmt['supported']:
        raise ValueError(f"Only CSV/TSV files can be analysed directly. {fmt['parser']}")
    listing = files(study_id)
    matches = [entry for entry in listing['files'] if entry.get('name') == filename]
    if len(matches) != 1:
        raise ValueError('File not uniquely listed in the current NASA OSDR catalog')
    record = matches[0]
    if record.get('restricted') or not record.get('download_url'):
        raise ValueError('NASA marks this file restricted or lacks a safe public URL')
    payload = _download_verified_csv(record['download_url'])
    content = _decode(payload)
    meta = study_metadata(study_id)
    cls = classify(meta) if meta.get('available') else classify({})
    declared = record.get('size_bytes')
    provenance = {
        'source_type': 'test_fixture_mirror_not_nasa' if TEST_MIRROR else 'verified_public_nasa_osdr_csv',
        'source_label': source_label(),
        'study': f'OSD-{study_id}', 'study_title': meta.get('title') or None, 'official_url': listing.get('official_url') or study_url(f'OSD-{study_id}'),
        'filename': filename, 'file_category': record.get('category'), 'original_format': fmt['format'],
        'source_api': listing.get('source'), 'download_url': record['download_url'],
        'sha256': hashlib.sha256(payload).hexdigest(), 'file_size_bytes': len(payload),
        'declared_size_bytes': declared,
        'size_matches_catalog': (declared == len(payload)) if isinstance(declared, int) else None,
        'retrieved_at_utc': _now(), 'study_release_date': meta.get('release_date'),
        'mission': meta.get('mission'), 'metadata_available': bool(meta.get('available')),
        'organism': cls['organism'], 'evidence_class': cls['evidence_class'], 'evidence_label': cls['evidence_label'],
        'data_layer': cls['data_layer'], 'material_type': cls['material_type'],
        'measurement_types': cls['measurement_types'],
        'sampling': 'Not stated in the file. If sample labels carry L-/FD/R+ tokens, timepoints are parsed from them.',
        'preprocessing': ['download over HTTPS from the catalog URL (redirects refused, 3 MB limit)',
                          'SHA-256 over the exact downloaded bytes', 'decode UTF-8 (BOM removed)'],
        'scope': 'Public NASA OSDR research file; astronaut identity, clinical meaning and units are not inferred.',
    }
    if not meta.get('available'):
        provenance['evidence_label'] = 'Study metadata unavailable — organism not confirmed; treated as not human'
    return _analyse(content, SUPPORTED_FORMATS[Path(filename).suffix.lower()], provenance, column, label_column)


def local_csv(study_id: int, filename: str, content: str, column: str = '', label_column: str = '') -> dict:
    """Offline import of a file the user downloaded from OSDR themselves.

    Origin cannot be verified: the record is labelled user-supplied. If its
    SHA-256 equals an earlier verified download it is marked as matching, but it
    keeps the user-supplied label.
    """
    if not isinstance(study_id, int) or isinstance(study_id, bool) or not 1 <= study_id <= 100000:
        raise ValueError('Invalid NASA OSDR study ID')
    name = Path(str(filename or '')).name[:200]
    fmt = file_format(name)
    if not name or not fmt['supported']:
        raise ValueError('Only .csv or .tsv files can be imported')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('File is empty')
    raw = content.encode('utf-8')
    if len(raw) > MAX_VERIFIED_CSV:
        raise ValueError('File exceeds 3 MB')
    digest = hashlib.sha256(raw).hexdigest()
    matched = next((e for e in _verified_history() if e.get('sha256') == digest
                    and e.get('source_type') == 'verified_public_nasa_osdr_csv'), None)
    provenance = {
        'source_type': 'user_supplied_file_unverified', 'source_label': 'User-supplied file (claimed OSDR origin, not verified)',
        'study': f'OSD-{study_id}', 'official_url': study_url(f'OSD-{study_id}'), 'filename': name,
        'original_format': fmt['format'], 'sha256': digest, 'file_size_bytes': len(raw),
        'sha256_note': 'Computed over the UTF-8 text received by AETHER; may differ from the original bytes if the file was re-encoded.',
        'matches_previous_verified_download': bool(matched), 'retrieved_at_utc': _now(),
        'organism': matched.get('organism') if matched else 'not verified', 'evidence_class': matched.get('evidence_class', 'unclassified') if matched else 'unclassified',
        'evidence_label': 'Origin unverified — not offered to PHANTOM', 'data_layer': matched.get('data_layer', 'unclassified') if matched else 'unclassified',
        'sampling': 'Not stated in the file.', 'preprocessing': ['file read locally by the user interface', 'SHA-256 over received text'],
        'scope': 'User-supplied research file; treated as unverified.',
    }
    return _analyse(content.lstrip('﻿'), SUPPORTED_FORMATS[Path(name).suffix.lower()], provenance, column, label_column)

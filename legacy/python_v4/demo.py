"""Offline reproducible demonstration: python demo.py"""
from pathlib import Path
from modules.biometric.ingestion import connect,import_file,history
from modules.phantom_engine.explanations import report,export_json
ROOT=Path(__file__).resolve().parent
with connect(ROOT/'demo_aether.db') as db:
 db.execute('DELETE FROM biometric_records');db.commit()
 records=import_file(db,ROOT/'examples'/'synthetic_mission.csv')
 result=report(history(db,'DEMO-01'),'DEMO-01')
 export_json(result,ROOT/'examples'/'phantom_report.json')
 print('Imported',len(records),'synthetic measurements; alerts:',len(result['alerts']))
 print('Report: examples/phantom_report.json')

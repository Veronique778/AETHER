"""Optional FastAPI adapter; core logic does not depend on FastAPI."""
try:from fastapi import FastAPI
except ImportError:FastAPI=None
from modules.phantom_engine.explanations import report
app=FastAPI(title='AETHER Research API') if FastAPI else None
if app:
 @app.post('/phantom/analyze')
 def analyze(payload:dict):return report(payload.get('records',[]),payload.get('crew_id','demo'))

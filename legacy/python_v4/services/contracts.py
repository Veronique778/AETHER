"""UI-independent service contracts; do not pass private records to unrelated modules."""
from modules.phantom_engine.explanations import report
def analyze_for_body(records,crew_id):
 r=report(records,crew_id)
 return {'crew_id':crew_id,'status':r['status'],'alerts':r['alerts'],'uncertainty':r['uncertainty'],'visualization_only':True}
def analyze_for_coorbit(records,crew_id,consent=False):
 if not consent:return {'crew_id':crew_id,'shared':False}
 r=report(records,crew_id)
 return {'crew_id':crew_id,'shared':True,'review_requested':bool(r['alerts']),'no_raw_health_data':True}

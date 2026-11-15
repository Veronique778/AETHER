from modules.biometric.preprocessing import coverage
def data_uncertainty(records,required):
 c=coverage(records,required)
 return {'data_coverage':c['fraction'],'missing_metrics':c['missing'],'model_uncertainty':'not_calibrated','confidence_probability':None,'status':'limited' if c['missing'] else 'coverage_complete'}

"""Frontend contract for the single BE3 handler surface; no route registration here."""

def paths():
    string={'type':'string'};nullable={'type':['string','null']}
    error={'type':'object','required':['error'],'properties':{'error':{'type':'object','required':['code','detail'],'properties':{'code':string,'detail':string}}}}
    analysis={'type':'object','required':['analysis_id','astronaut_id','processing_version','outcome','diagnosis','input','storage'],
      'properties':{'analysis_id':string,'astronaut_id':{'type':'string','format':'uuid'},'mission_id':nullable,
                    'processing_version':string,'outcome':{'enum':['flag','no_flag','insufficient_data']},'diagnosis':{'type':'null'},
                    'input':{'type':'object'},'storage':{'type':'object','properties':{'input_count':{'type':'integer','minimum':0},'input_digest':string}}}}
    run={'type':'object','required':['astronaut_id'],'properties':{'astronaut_id':{'type':'string','format':'uuid'},'mission_id':nullable,
        'session_id':nullable,'from':{'type':'string','format':'date-time'},'to':{'type':'string','format':'date-time'},
        'signals':{'type':'array','items':{'enum':['heart_rate','rr_interval']}},'method':{'enum':['phantom_hr_univariate_1_4']},
        'data_classes':{'type':'array','items':string},'baseline_from':{'type':'string','format':'date-time'},'baseline_to':{'type':'string','format':'date-time'}}}
    listing={'type':'object','required':['items','next_cursor'],'properties':{'items':{'type':'array','items':analysis},'next_cursor':nullable}}
    feature={'type':'object','required':['implementation_available','automated_tested','available','integration_pending','hardware_verified'],'properties':{k:{'type':'boolean'} for k in ('implementation_available','automated_tested','available','integration_pending','hardware_verified')}}
    health={'type':'object','required':['status','feature_status'],'properties':{'status':string,'feature_status':{'type':'object','required':['auth','personal_measurements','scientific_signals','phantom','ble','nasa'],'properties':{k:feature for k in ('auth','personal_measurements','scientific_signals','phantom','ble','nasa')}}}}
    definitions=[('get','/api/health',health,None),('get','/api/signals',{'type':'object','required':['signals']},None),
      ('post','/api/phantom-analyses',analysis,run),('get','/api/phantom-analyses',listing,None),
      ('get','/api/phantom-analyses/{analysis_id}',analysis,None),
      ('get','/api/devices/adapters',{'type':'object'},None),('post','/api/devices/scan',{'type':'object'},{'type':'object'}),
      ('post','/api/devices/{device_id}/connect',{'type':'object'},{'type':'object','required':['astronaut_id'],'properties':{'astronaut_id':{'type':'string','format':'uuid'},'mission_id':nullable}}),
      ('post','/api/devices/{device_id}/disconnect',{'type':'object'},{'type':'object','maxProperties':0}),
      ('get','/api/devices/{device_id}/status',{'type':'object'},None)]
    result={}
    for method,path,response,body in definitions:
        op={'security':[{'personalBearer':[]}],'responses':{'200':{'description':'Success or replay','content':{'application/json':{'schema':response}}}}}
        if method=='post' and path=='/api/phantom-analyses':op['responses']['201']={'description':'Stored analysis, including insufficient_data','content':{'application/json':{'schema':analysis}}}
        for status in (400,401,403,404,405,409,413,415,422,500,503):op['responses'][str(status)]={'description':'Error','content':{'application/json':{'schema':error}}}
        if path=='/api/health':op['security']=[]
        if body is not None:op['requestBody']={'required':True,'content':{'application/json':{'schema':body}}}
        import re
        params=[{'name':k,'in':'path','required':True,'schema':string} for k in re.findall(r'\{(\w+)\}',path)]
        if method=='get' and path=='/api/phantom-analyses':params += [{'name':k,'in':'query','schema':string} for k in ('astronaut_id','mission_id','outcome','limit','cursor')]
        if params:op['parameters']=params
        result.setdefault(path,{})[method]=op
    return result

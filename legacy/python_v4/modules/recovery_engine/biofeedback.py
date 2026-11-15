def scene_parameters(signal,origin='synthetic'):
 if origin not in {'real','manual','estimated','synthetic'}:raise ValueError('Invalid origin')
 if signal is None:return {'animation_speed':1.0,'source':'synthetic','signal_available':False}
 hr=float(signal)
 if not 20<=hr<=250:raise ValueError('Invalid heart rate')
 return {'animation_speed':round(max(.5,min(2.0,hr/75)),2),'source':origin,'signal_available':True}

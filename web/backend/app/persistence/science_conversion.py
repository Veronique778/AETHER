"""Explicit BE2↔BE3 transformations. Does not edit BE3 validators or algorithms."""
import json
import math
import uuid
from app.persistence.common import APIError, utc

CLASS_TO_ORIGIN={'real_wearable':'real','manual':'manual','synthetic':'simulated'}
ORIGIN_TO_CLASS={v:k for k,v in CLASS_TO_ORIGIN.items()}
SIGNAL_TO_RAW={'heart_rate':('heart_rate','bpm',1), 'rr_interval':('rr_interval','ms',1),
 'sleep_duration':('sleep_duration','s',3600), 'fatigue':('fatigue_1_10','score',1),
 'reaction_time':('reaction_ms','ms',1), 'activity_duration':('activity_minutes','min',1)}
RAW_TO_SIGNAL={v[0]:(k,v[2]) for k,v in SIGNAL_TO_RAW.items()}
RAW_TO_SIGNAL.update(heart_rate_bpm=('heart_rate',1),sleep_hours=('sleep_duration',1))
QUALITY_TO_RAW={'good':'screened','screened':'screened','degraded':'unverified','no_contact':'no_contact',
 'corrupt':'corrupt','out_of_range':'rejected','rejected':'rejected','missing':'unverified'}


def uuid_identity(value):
    try:
        parsed=uuid.UUID(value)
        if str(parsed)!=value: raise ValueError
    except (ValueError,TypeError,AttributeError):
        raise APIError(422,'personal_uuid_required','Personal astronaut IDs use canonical UUID strings') from None
    return value


def normalize(item,index=0):
    """Use BE3's public signal/time/quality/contact rules with BE2's UUID rule.

    BE3 validate_item() has a hard-coded Axx gate. Until 03A it cannot be called
    on personal UUIDs. Its reusable validators are called directly instead;
    this difference is explicit and covered by equivalence tests on signals.
    No fake A01 identity or monkey-patch of BE3 is used.
    """
    from app import signals as reg
    if not isinstance(item,dict): raise APIError(422,'validation_error','Measurement must be an object')
    allowed={'client_measurement_id','astronaut_id','mission_id','session_id','device_id','signal','value','unit',
             'recorded_at','quality','data_class','source','provenance','original_timestamp','timezone','mission_day','sampling_hz'}
    if set(item)-allowed: raise APIError(422,'validation_error','Unknown scientific measurement field')
    d=dict(item); uuid_identity(d.get('astronaut_id'))
    key=d.get('client_measurement_id')
    if not isinstance(key,str) or not 1<=len(key)<=128: raise APIError(422,'validation_error','Stable client_measurement_id is required')
    if d.get('data_class') not in CLASS_TO_ORIGIN:
        raise APIError(422,'research_separate','Only real_wearable, manual and synthetic belong in the personal raw store')
    info=reg.signal_info(d.get('signal'))
    if d.get('unit')!=info['unit']:
        from app.science_errors import InvalidUnits
        raise InvalidUnits('Incorrect unit for scientific signal',field='unit')
    rec=reg.parse_utc(d.get('recorded_at'))
    if rec is None: raise APIError(422,'utc_required','Personal measurements require actual UTC time; relative research time stays separate')
    if not isinstance(d.get('source'),str) or not 1<=len(d['source'])<=120: raise APIError(422,'validation_error','Invalid source')
    prov=d.get('provenance') or {}
    if not isinstance(prov,dict) or len(json.dumps(prov,allow_nan=False).encode())>8192: raise APIError(422,'validation_error','Invalid provenance')
    q,valid,missing=reg.check_quality(d.get('value'),d.get('quality','good' if d['data_class']=='manual' else ''),info,d['data_class']=='manual')
    q,valid=reg.contact_quality(d['signal'],d['data_class'],q,valid,prov)
    sampling=d.get('sampling_hz')
    if sampling is not None and (isinstance(sampling,bool) or not isinstance(sampling,(int,float)) or not math.isfinite(sampling) or sampling<=0):
        raise APIError(422,'validation_error','sampling_hz must be a finite positive number')
    for k in ('original_timestamp','timezone'):
        if d.get(k) is not None and (not isinstance(d[k],str) or len(d[k])>120): raise APIError(422,'validation_error','Invalid temporal metadata')
    if d.get('mission_day') is not None and (type(d['mission_day']) is not int or d['mission_day']<0): raise APIError(422,'validation_error','Invalid mission day')
    d.update(recorded_at=reg.iso_utc(rec),value=None if d.get('value') is None else float(d['value']),quality=q,valid=valid,missing=missing,provenance=prov)
    return d


def to_raw(d):
    signal,unit,factor=SIGNAL_TO_RAW[d['signal']]
    metadata={'provenance':d['provenance'],'science_conversion':{'signal':d['signal'],'unit':d['unit'],'factor_to_raw':factor}}
    return {'id':uuid.uuid4().hex,'astronaut_id':d['astronaut_id'],'mission_id':d.get('mission_id'),
      'device_id':d.get('device_id'),'session_id':d.get('session_id'),'source':d['source'],'signal':signal,
      'value':None if d['value'] is None else d['value']*factor,'unit':unit,'measured_at':utc(d['recorded_at']),
      'origin':CLASS_TO_ORIGIN[d['data_class']],'quality':QUALITY_TO_RAW[d['quality']],'confidence':None,
      'processing_version':'be2-science-adapter-1.5.1','metadata':metadata,
      'idempotency_key':d['client_measurement_id'],'supersedes_id':None}


def project(row,attrs=None,invalidation=None):
    from app import signals as reg
    raw=dict(row)
    if raw['signal'] not in RAW_TO_SIGNAL: return None
    signal,factor=RAW_TO_SIGNAL[raw['signal']]
    value=None if raw['value'] is None else raw['value']/factor
    meta=json.loads(raw['metadata']);attr=json.loads(attrs['attributes']) if attrs else {}
    quality=attrs['quality'] if attrs else {'screened':'screened','validated':'screened','no_contact':'no_contact',
                   'corrupt':'corrupt','rejected':'rejected'}.get(raw['quality'],'rejected')
    valid=bool(attrs['valid']) if attrs else quality=='screened'
    if value is None: quality='missing';valid=False
    dc=ORIGIN_TO_CLASS.get(raw['origin'])
    if dc is None: return None
    prov=meta.get('provenance') if isinstance(meta.get('provenance'),dict) else {}
    quality,contact_valid=reg.contact_quality(signal,dc,quality,valid,prov)
    info=reg.signal_info(signal)
    if value is not None and not info['plausible_min']<=value<=info['plausible_max']:
        quality='out_of_range';contact_valid=False
    return {'measurement_id':raw['id'],'client_measurement_id':raw['idempotency_key'],'astronaut_id':raw['astronaut_id'],
      'mission_id':raw['mission_id'],'session_id':raw['session_id'],'device_id':raw['device_id'],
      'signal':signal,'value':value,'unit':info['unit'],'recorded_at':reg.iso_utc(reg.parse_utc(raw['measured_at'])) if raw['measured_at'] else None,
      'received_at':raw['received_at'],'quality':quality,'valid':bool(valid and contact_valid),'missing':value is None,
      'data_class':dc,'source':raw['source'],'provenance':prov,'processing_version':raw['processing_version'],
      'created_by':attrs['created_by'] if attrs else None,'status':'invalidated' if invalidation else 'active',
      'invalidated_reason':invalidation['reason'] if invalidation else None,
      **{k:attr.get(k) for k in ('original_timestamp','timezone','mission_day','sampling_hz')}}

"""Streaming importer for the published MMASH 1.0.0 CSV schema.
No extraction, no pickle execution, no time zone inference, no personal details.
"""
import csv
import hashlib
import io
import math
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from . import biosignals as bio

MAX_FILE=128*1024*1024
MAX_TOTAL=768*1024*1024
SOURCE='MMASH 1.0.0; Rossi et al. 2020; doi:10.13026/cerq-fc86; https://physionet.org/content/mmash/1.0.0/'

class Dataset:
    def __init__(self,path):
        self.path=Path(path).expanduser().resolve()
        self.z=None
        if self.path.is_file() and self.path.suffix.lower()=='.zip':
            if self.path.stat().st_size>MAX_TOTAL: raise ValueError('ZIP exceeds 768 MiB limit')
            try: self.z=zipfile.ZipFile(self.path)
            except zipfile.BadZipFile as exc: raise ValueError('Invalid or corrupted ZIP file') from exc
            infos=self.z.infolist()
            if len(infos)>10000 or sum(i.file_size for i in infos)>MAX_TOTAL: raise ValueError('Archive exceeds import limits')
            self.files={}
            for i in infos:
                n=i.filename.replace('\\','/')
                p=PurePosixPath(n)
                if p.is_absolute() or '..' in p.parts or ':' in n or (i.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('Unsafe ZIP member')
                if i.file_size>MAX_FILE: raise ValueError('Archive member exceeds 128 MiB')
                if not i.is_dir():
                    if n in self.files: raise ValueError('Duplicate ZIP member')
                    self.files[n]=i
        elif self.path.is_dir():
            self.files={}
            for p in self.path.rglob('*.csv'):
                if len(self.files)>10000: raise ValueError('Too many files')
                if not p.resolve().is_relative_to(self.path) or p.is_symlink(): raise ValueError('Unsafe linked dataset file')
                if p.stat().st_size>MAX_FILE: raise ValueError('CSV exceeds 128 MiB')
                self.files[p.relative_to(self.path).as_posix()]=p
            if sum(p.stat().st_size for p in self.files.values())>MAX_TOTAL: raise ValueError('Folder exceeds 768 MiB')
        else: raise ValueError('Select an existing MMASH folder or ZIP')
    def close(self):
        if self.z: self.z.close()
    @contextmanager
    def rows(self,n,required):
        raw=self.z.open(self.files[n]) if self.z else self.files[n].open('rb')
        with raw, io.TextIOWrapper(raw,encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not set(required)<=set(reader.fieldnames or []): raise ValueError(f'{n}: expected columns {required}')
            yield reader
    def digest(self,n):
        h=hashlib.sha256()
        with (self.z.open(self.files[n]) if self.z else self.files[n].open('rb')) as f:
            for block in iter(lambda:f.read(65536),b''): h.update(block)
        return h.hexdigest()
    def subjects(self):
        return sorted({PurePosixPath(n).parent.name for n in self.files if PurePosixPath(n).name=='RR.csv' and re.fullmatch(r'user_\d+',PurePosixPath(n).parent.name)})

def inspect(path):
    d=Dataset(path)
    try:
        return {'dataset':SOURCE,'participants':d.subjects(),'files':len(d.files),
                'limits':'768 MiB total, 128 MiB/file, 2 million measurements/session',
                'timestamp_note':'MMASH publishes relative day and time; calendar date and timezone are unavailable. UTC remains null.'}
    finally: d.close()

def clock(day, time):
    if not re.fullmatch(r'\d+',str(day).strip()): raise ValueError('Invalid recording day')
    day=int(day)
    parts=str(time).split(':')
    if len(parts) not in (2,3) or not 0<=day<=366: raise ValueError('Invalid day/time')
    h,m=int(parts[0]),int(parts[1]); s=float(parts[2]) if len(parts)==3 else 0
    if not (0<=h<24 and 0<=m<60 and 0<=s<60): raise ValueError('Invalid clock')
    return (day-1)*86400+h*3600+m*60+s

def num(raw):
    if raw is None or str(raw).strip().lower() in ('','nan','na','null'): return None
    value=float(raw)
    return value if math.isfinite(value) else None

def import_mmash(path, participant, confirmed=False):
    if confirmed is not True: raise ValueError('Confirm local import and dataset usage terms first')
    d=Dataset(path); sid=None
    try:
        if participant not in d.subjects(): raise ValueError('Participant not found')
        names={PurePosixPath(n).name:n for n in d.files if PurePosixPath(n).parent.name==participant}
        meta={'dataset':SOURCE,'time_basis':'relative recording day; UTC unknown','source_timezone':None,
              'files':{},'corrupt_rows':0,'out_of_order_rows':0,'processing_version':bio.VERSION,
              'ignored_files':['Activity.csv/Acivity.csv (self-report codes)','questionnaire.csv','user_info.csv','saliva.csv'],
              'license':'PhysioNet Open Data Commons Attribution License v1.0; retain attribution; recordings not bundled.'}
        sid=bio.create('MMASH:'+participant,'research',SOURCE,meta)
        batch=[]; count=0
        def emit(row):
            nonlocal count,batch
            count+=1
            if count>bio.LIMIT: raise ValueError('Session exceeds 2 million measurement limit')
            batch.append(row)
            if len(batch)>=2000: bio.append(sid,batch); batch=[]
        for filename in ('RR.csv','Actigraph.csv','sleep.csv'):
            if filename not in names: continue
            name=names[filename]; meta['files'][filename]={'sha256':d.digest(name)}; previous=None
            required={'RR.csv':['ibi_s','day','time'],'Actigraph.csv':['HR','Axis1','Axis2','Axis3','day','time'],
                      'sleep.csv':['In Bed Date','In Bed Time','Out Bed Date','Out Bed Time','Total Sleep Time (TST)','Efficiency','Wake After Sleep Onset (WASO)','Sleep Fragmentation Index']}[filename]
            with d.rows(name,required) as rows:
                for index,r in enumerate(rows,2):
                    provenance={'file':filename,'row':index,'dataset':'MMASH 1.0.0'}
                    try:
                        t=clock(r['Out Bed Date'],r['Out Bed Time']) if filename=='sleep.csv' else clock(r['day'],r['time'])
                        out_of_order=previous is not None and t<previous
                        if out_of_order: meta['out_of_order_rows']+=1
                        previous=t
                        original=f"day {r.get('day',r.get('Out Bed Date'))} {r.get('time',r.get('Out Bed Time'))}"
                        if filename=='RR.csv':
                            v=num(r['ibi_s']); ms=v*1000 if v is not None else None
                            quality='rejected' if ms is not None and not 300<=ms<=2000 else 'screened'
                            if out_of_order: quality='rejected'
                            emit(bio.measurement(t,'rr_interval',ms,'ms',original,quality=quality,provenance=provenance))
                            # Derived instantaneous HR only for plausible RR. No interpolation.
                            emit(bio.measurement(t,'heart_rate',60000/ms if ms and quality=='screened' else None,'bpm',original,quality=quality,provenance={**provenance,'derived_from':'ibi_s; 60/ibi_s'}))
                        elif filename=='Actigraph.csv':
                            # RR-derived HR is primary to avoid mixing two devices' HR streams.
                            for col,sig,unit in [('HR','actigraph_heart_rate','bpm'),('Axis1','acc_axis1','ActiGraph counts'),('Axis2','acc_axis2','ActiGraph counts'),('Axis3','acc_axis3','ActiGraph counts'),('Steps','steps','count')]:
                                if col not in r: continue
                                v=num(r[col]); quality='rejected' if out_of_order or (v is not None and (v<0 or (col=='HR' and not 30<=v<=220))) else 'screened'
                                emit(bio.measurement(t,sig,v,unit,original,quality=quality,provenance=provenance))
                        else:
                            start=clock(r['In Bed Date'],r['In Bed Time'])
                            if t<start: raise ValueError('Sleep ends before it starts')
                            for col,sig,unit in [('Total Sleep Time (TST)','sleep_duration','min'),('Efficiency','sleep_efficiency','%'),('Wake After Sleep Onset (WASO)','waso','min'),('Sleep Fragmentation Index','sleep_fragmentation','dataset index')]:
                                v=num(r[col]); quality='rejected' if v is not None and (v<0 or (col=='Efficiency' and v>100) or (col in ('Total Sleep Time (TST)','Wake After Sleep Onset (WASO)') and v>(t-start)/60)) else 'screened'
                                emit(bio.measurement(t,sig,v,unit,original,quality=quality,provenance={**provenance,'definition':col,'sleep_start_seconds':start}))
                    except (ValueError,TypeError,KeyError,OverflowError) as exc:
                        if count>bio.LIMIT: raise
                        meta['corrupt_rows']+=1
                        emit(bio.measurement(None,'corrupt_row',None,'unavailable',quality='corrupt',provenance={**provenance,'error':str(exc)}))
        if batch: bio.append(sid,batch)
        meta['measurements']=count
        bio.finish(sid,'ready',meta)
        return bio.session(sid)
    except Exception:
        if sid:
            # Failed imports leave neither partial sensitive records nor sessions.
            with bio.db.connect() as c:
                c.execute('DELETE FROM bio_measurements WHERE session_id=?',(sid,))
                c.execute('DELETE FROM bio_sessions WHERE id=?',(sid,))
        raise
    finally: d.close()

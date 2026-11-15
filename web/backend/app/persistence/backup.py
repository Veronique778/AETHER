"""Consistent SQLite backups and offline, verified atomic restore.
Run with both HTTP servers and sync workers stopped before restore.
"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path
from app import db
from .common import digest, utcnow


def verify(path):
    con=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Backup integrity check failed')
        if con.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Backup has broken foreign keys')
    finally: con.close()


def backup(destination):
    target=Path(destination).resolve()
    if not Path(db.DB_PATH).is_file(): raise ValueError('Source database does not exist')
    if target==Path(db.DB_PATH).resolve() or target.exists(): raise ValueError('Choose a new backup filename')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    try:
        with db.connect() as source:
            dest=sqlite3.connect(target)
            try:
                dest.execute('PRAGMA foreign_keys=ON'); source.backup(dest)
            finally: dest.close()
        verify(target)
        manifest={'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'created_at':utcnow(),'format':'sqlite-backup-1.5'}
        mp=target.with_suffix(target.suffix+'.json')
        fd=os.open(mp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: json.dump(manifest,f)
        return manifest
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def restore(source,destination):
    source=Path(source).resolve(); target=Path(destination).resolve()
    if source==target or target.exists(): raise ValueError('Restore to a new path, then select it with AETHER_DB_PATH')
    manifest=json.loads(source.with_suffix(source.suffix+'.json').read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest()!=manifest['sha256']: raise ValueError('Backup checksum mismatch')
    verify(source)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.restore-'+secrets.token_hex(8))
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as out: out.write(source.read_bytes()); out.flush(); os.fsync(out.fileno())
        c=sqlite3.connect(temp)
        try:
            c.execute('PRAGMA foreign_keys=ON')
            names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'auth_sessions' in names:
                c.execute('UPDATE auth_sessions SET revoked_at=?',(utcnow(),))
                # Prevent replay of single-use recovery codes resurrected from an old snapshot.
                for row in c.execute('SELECT id FROM users').fetchall():
                    c.execute('UPDATE users SET recovery_hash=? WHERE id=?',(digest(secrets.token_urlsafe(32)),row[0]))
            if 'sync_events' in names:
                c.execute("UPDATE sync_events SET status='pending',claim_token=NULL,lease_until=0 WHERE status='sending'")
            c.commit()
        finally: c.close()
        verify(temp); os.replace(temp,target)
    finally: temp.unlink(missing_ok=True)
    return {'restored':True,'sessions_revoked':True,'recovery_codes_invalidated':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('backup'); b.add_argument('destination')
    r=sub.add_parser('restore'); r.add_argument('source'); r.add_argument('destination')
    args=p.parse_args()
    if args.action=='backup': backup(args.destination); print('Backup verified.')
    else: restore(args.source,args.destination); print('Restore verified. Set AETHER_DB_PATH to the new file. Sign in and change your password to issue a new recovery code.')

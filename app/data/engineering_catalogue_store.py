"""Portable SQLite index built from the reviewed, versioned catalogue.

Never used as a second editable source of truth. Rebuilding requires explicit
replacement; a failed export cannot overwrite a previous database.
"""
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from app.data.engineering_catalogue import get_engineering_catalogue, plain, SCHEMA_VERSION


def export_sqlite(path, *, replace=False, catalogue=None):
    c = catalogue or get_engineering_catalogue()
    path = Path(path)
    if path.exists() and not replace:
        raise FileExistsError(f'{path}: для пересборки требуется --replace')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.engineering-',suffix='.sqlite',dir=path.parent)
    os.close(fd)
    dump = lambda value: json.dumps(plain(value),ensure_ascii=False,sort_keys=True,allow_nan=False)
    try:
        with sqlite3.connect(tmp) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript('''
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE items (
                    id TEXT PRIMARY KEY, family_id TEXT NOT NULL, kind TEXT NOT NULL,
                    material TEXT NOT NULL, manufacturing TEXT NOT NULL, status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE item_sources (
                    item_id TEXT REFERENCES items(id), source_id TEXT REFERENCES sources(id),
                    PRIMARY KEY(item_id,source_id));
                CREATE TABLE ports (
                    item_id TEXT REFERENCES items(id), port_index INTEGER NOT NULL,
                    dn INTEGER, outer_diameter_mm REAL, connection TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(item_id,port_index));
                CREATE INDEX item_filter ON items(kind,material,status);
                CREATE INDEX port_dn ON ports(dn,connection);
                CREATE INDEX port_outer ON ports(outer_diameter_mm,connection);
            ''')
            db.executemany('INSERT INTO metadata VALUES (?,?)',[
                ('schema_version',str(SCHEMA_VERSION)),('catalogue_revision',c.revision),
                ('authority','JSON and existing catalogue adapters; read-only compiled index'),
                ('units',dump({'dimensions':'mm','pressure':'bar','temperature':'degC'}))])
            db.executemany('INSERT INTO sources VALUES (?,?)',[(k,dump(v)) for k,v in c.sources.items()])
            for p in c.items.values():
                db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?)',
                    (p.id,p.family_id,p.kind,p.material,p.manufacturing,p.status,c.fingerprint(p.id),dump(c.card(p.id))))
                db.executemany('INSERT INTO item_sources VALUES (?,?)',[(p.id,s) for s in p.source_ids])
                db.executemany('INSERT INTO ports VALUES (?,?,?,?,?,?)',
                    [(p.id,i,q.dn,q.outer_diameter_mm,q.connection,dump(q)) for i,q in enumerate(p.ports)])
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Нарушена целостность ссылок базы')
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Ошибка целостности SQLite')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        # Do not overwrite a file another process created during this build.
        if replace:
            os.replace(tmp,path)
        else:
            os.link(tmp,path)
            os.unlink(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return c.summary()

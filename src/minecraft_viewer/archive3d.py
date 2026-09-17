"""Version 1 portable visual snapshots: SQLite + PNG/JSON/NumPy NPZ (no pickle)."""
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

ARRAYS=('vertices','normals','colors','uvs')


class SceneArchive:
    def __init__(self,db):self.db=Path(db)

    def connect(self):
        connection=sqlite3.connect(self.db,timeout=30)
        connection.execute('PRAGMA foreign_keys=ON')
        return connection

    @staticmethod
    def asset(connection,export_id,role,name,format,payload,metadata=None):
        digest=hashlib.sha256(payload).hexdigest()
        connection.execute('INSERT OR IGNORE INTO mc_3d_asset VALUES (?,?,?)',(digest,format,payload))
        connection.execute('INSERT INTO mc_3d_export_asset VALUES (?,?,?,?,?)',
                           (export_id,role,name,digest,json.dumps(metadata or {})))

    def begin(self,world_id,manifest,atlas):
        with closing(self.connect()) as c,c:
            export_id=c.execute("INSERT INTO mc_3d_export(world_id,format_version,status,manifest_json) VALUES (?,1,'building',?)",
                                (world_id,json.dumps(manifest))).lastrowid
            if atlas:
                self.asset(c,export_id,'atlas','terrain','image/png',atlas.png)
                for name,data in atlas.assets.items():
                    self.asset(c,export_id,'source_asset',name,'image/png' if name.endswith('.png') else 'application/json',data)
            return export_id

    def put_mesh(self,export_id,key,coords,data):
        stream=io.BytesIO()
        np.savez_compressed(stream,**{k:np.asarray(data[k],dtype='<f4') for k in ARRAYS})
        with closing(self.connect()) as c,c:
            self.asset(c,export_id,'mesh',json.dumps(key),'application/x-numpy-npz',stream.getvalue(),
                       {'key':key,'chunks':coords,'origin':[key[1]*16,0,key[2]*16]})

    def finish(self,export_id,errors):
        with closing(self.connect()) as c,c:
            c.execute("UPDATE mc_3d_export SET status=?,error_count=?,completed_at=datetime('now') WHERE export_id=?",
                      ('partial' if errors else 'complete',errors,export_id))

    def copy_mesh(self,previous,export_id,key):
        with closing(self.connect()) as c,c:
            count=c.execute("INSERT INTO mc_3d_export_asset SELECT ?,role,name,sha256,metadata_json FROM mc_3d_export_asset WHERE export_id=? AND role='mesh' AND name=?",
                            (export_id,previous,json.dumps(key))).rowcount
            return count==1

    def read(self,export_id,world_id):
        with closing(sqlite3.connect(self.db.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            row=c.execute('SELECT format_version,status,manifest_json FROM mc_3d_export WHERE export_id=? AND world_id=?',
                          (export_id,world_id)).fetchone()
            if not row or row[0]!=1 or row[1] not in ('complete','partial'):raise ValueError('Export missing, unfinished, or unsupported')
            manifest=json.loads(row[2]);manifest['export_status']=row[1]
            records=c.execute('SELECT role,name,sha256,metadata_json FROM mc_3d_export_asset WHERE export_id=? AND role IN (\'mesh\',\'atlas\')',
                              (export_id,)).fetchall()
            return manifest,records

    def payload(self,digest):
        with closing(sqlite3.connect(self.db.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            row=c.execute('SELECT payload FROM mc_3d_asset WHERE sha256=?',(digest,)).fetchone()
        if row is None or hashlib.sha256(row[0]).hexdigest()!=digest:raise ValueError('Missing or corrupt archived asset')
        return row[0]

    def mesh(self,digest):
        with np.load(io.BytesIO(self.payload(digest)),allow_pickle=False) as archive:
            result={k:archive[k] for k in ARRAYS}
        size=len(result['vertices'])
        for key,width in zip(ARRAYS,(3,3,4,2)):
            if result[key].shape!=(size,width) or not np.isfinite(result[key]).all():raise ValueError('Invalid archived geometry')
        if size%3:raise ValueError('Invalid triangle count')
        return result

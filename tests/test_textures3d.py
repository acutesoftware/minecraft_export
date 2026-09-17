import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing

import numpy as np
from PIL import Image

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from minecraft_viewer.textures3d import TextureAtlas,read_assets,find_client,validate_source
from minecraft_viewer.mesh3d import MeshWorld,mesh_volume
from minecraft_viewer.archive3d import SceneArchive
from minecraft_viewer.db import ArchiveDB


def fixture_assets():
    assets={}
    for name,colour in [('stone',(190,180,170,255)),('top',(200,70,40,255)),('short_grass',(120,190,80,0))]:
        picture=Image.new('RGBA',(16,16),colour)
        for y in range(16):
            for x in range(16):
                if (x//4+y//4)%2:picture.putpixel((x,y),(40,80,150,255))
        stream=io.BytesIO();picture.save(stream,format='PNG')
        assets[f'assets/minecraft/textures/block/{name}.png']=stream.getvalue()
    assets['assets/minecraft/models/block/base.json']=json.dumps({'textures':{'all':'minecraft:block/stone'},'elements':[{'faces':{name:{'texture':'#top' if name=='up' else '#all'} for name in ('up','down','east','west','south','north')}}]}).encode()
    assets['assets/minecraft/models/block/stone.json']=json.dumps({'parent':'minecraft:block/base','textures':{'top':'minecraft:block/top'}}).encode()
    assets['assets/minecraft/models/block/cross.json']=json.dumps({'textures':{'particle':'#cross'},'elements':[{'faces':{'north':{'texture':'#cross'},'south':{'texture':'#cross'}}}]}).encode()
    assets['assets/minecraft/models/block/sugar_cane.json']=json.dumps({'parent':'minecraft:block/cross','textures':{'cross':'minecraft:block/short_grass'}}).encode()
    assets['assets/minecraft/blockstates/sugar_cane.json']=b'{"variants":{"":{"model":"minecraft:block/sugar_cane"}}}'
    return assets


def fixture_scene(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=ArchiveDB(root/'archive.db')
    with db.connect() as c:
        c.execute("INSERT INTO mc_world(world_id,world_uuid,world_name,spawn_x,spawn_y,spawn_z,first_imported_at,last_imported_at) VALUES (1,'fixture','Texture archive fixture',0,0,0,'now','now')")
    atlas=TextureAtlas(fixture_assets())
    reader=MeshWorld(root/'missing-world',root/'cache','fixture',atlas)
    blocks=np.zeros((3,18,18),dtype=np.uint32);blocks[1,1:6,1:6]=reader.block_id('minecraft:stone')
    mesh=mesh_volume(blocks,0,np.zeros((16,16)),reader.colors,materials=reader.materials,atlas=atlas,block_names=reader.block_names)
    world=dict(db.row('SELECT * FROM mc_world WHERE world_id=1'))
    manifest={'world':world,'dimension':{'source_path':str(root/'missing-world')},'detailed_radius':16,'distant_radius':32,'requested_chunks':1,
              'camera_position':[10,8,10],'camera_rotation':[30,225,0],'texture_fingerprint':atlas.fingerprint}
    archive=SceneArchive(db.path);export_id=archive.begin(1,manifest,atlas)
    archive.put_mesh(export_id,('near',0,0),[(0,0)],mesh);archive.finish(export_id,0)
    return db,archive,export_id,atlas,mesh


class TextureTests(unittest.TestCase):
    def test_assets_jar_folder_and_no_game_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);jar=root/'client.jar'
            with zipfile.ZipFile(jar,'w') as z:
                for name,data in fixture_assets().items():z.writestr(name,data)
                z.writestr('account.json','secret');z.writestr('classes/World.class','code')
                z.writestr('../../escape.png','unsafe')
            assets=read_assets(jar)
            self.assertEqual(assets,fixture_assets())
            self.assertEqual(find_client(jar),jar)
            with self.assertRaises(FileNotFoundError):find_client(root/'absent')

    def test_parent_texture_resolution_distinct_faces_and_fallback(self):
        atlas=TextureAtlas(fixture_assets())
        top,found,tinted=atlas.face('minecraft:stone','up')
        side,found_side,_=atlas.face('minecraft:stone','east')
        self.assertTrue(found and found_side);self.assertFalse(tinted)
        self.assertFalse(np.array_equal(top,side))
        self.assertGreater(side[2,1],side[0,1])  # Side corner 1 is above corner 0.
        self.assertFalse(atlas.face('mod:missing','up')[1])
        self.assertTrue(atlas.face('minecraft:grass','north')[1])
        image=Image.open(io.BytesIO(atlas.png))
        uv=atlas.face('mod:missing','up')[0][0]
        self.assertEqual(image.getpixel((int(uv[0]*image.width),int((1-uv[1])*image.height))),(255,255,255,255))

    def test_fingerprint_tracks_content_and_cache_separation(self):
        assets=fixture_assets();first=TextureAtlas(assets)
        assets={**assets,'assets/minecraft/models/block/new.json':b'{}'}
        second=TextureAtlas(assets)
        self.assertNotEqual(first.fingerprint,second.fingerprint)
        with tempfile.TemporaryDirectory() as root:
            self.assertNotEqual(MeshWorld(root,root,'w',first).cache,MeshWorld(root,root,'w',second).cache)

    def test_model_and_alpha_drive_render_shape(self):
        atlas=TextureAtlas(fixture_assets())
        self.assertEqual(atlas.render_shape('minecraft:sugar_cane'),'cross')
        self.assertEqual(atlas.render_shape('minecraft:short_grass'),'cutout_cube')
        self.assertTrue(atlas.face('minecraft:sugar_cane','north')[2])

    def test_cycles_terminate(self):
        assets=fixture_assets()
        assets['assets/minecraft/models/block/stone.json']=b'{"parent":"minecraft:block/stone","textures":{"all":"#all"}}'
        self.assertFalse(TextureAtlas(assets).face('minecraft:stone','up')[1])

    def test_server_jar_rejected_with_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'server.jar'
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('server.class',b'code')
            with self.assertRaisesRegex(ValueError,'CLIENT JAR'):validate_source(path)

    def test_version_selection_is_explicit_when_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for version in ('1.20','1.21'):
                folder=root/'versions'/version;folder.mkdir(parents=True);(folder/f'{version}.jar').touch()
            with self.assertRaisesRegex(ValueError,'Multiple'):find_client(root)
            self.assertEqual(find_client(root,'1.20').stem,'1.20')


class ArchiveTests(unittest.TestCase):
    def test_standalone_replay_and_content_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,archive,export_id,atlas,mesh=fixture_scene(tmp)
            manifest,records=archive.read(export_id,1)
            self.assertFalse(Path(manifest['dimension']['source_path']).exists())
            record=next(r for r in records if r[0]=='mesh')
            restored=archive.mesh(record[2])
            for key in mesh:np.testing.assert_array_equal(mesh[key],restored[key])
            self.assertTrue((mesh['colors'][:,:3]==1).all())
            self.assertTrue((mesh['uvs']>=0).all() and (mesh['uvs']<=1).all())
            count=db.row('SELECT COUNT(*) FROM mc_3d_asset')[0]
            second=archive.begin(1,manifest,atlas)
            self.assertTrue(archive.copy_mesh(export_id,second,('near',0,0)))
            archive.finish(second,0)
            self.assertEqual(count,db.row('SELECT COUNT(*) FROM mc_3d_asset')[0])
            # A SQLite backup alone retains every required visual asset.
            backup=Path(tmp)/'portable.db'
            with db.connect() as source,closing(sqlite3.connect(backup)) as target:source.backup(target)
            portable=SceneArchive(backup)
            portable.read(export_id,1)
            np.testing.assert_array_equal(portable.mesh(record[2])['uvs'],mesh['uvs'])

    def test_integrity_and_unfinished_export_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,archive,export_id,atlas,mesh=fixture_scene(tmp)
            building=archive.begin(1,{},None)
            with self.assertRaises(ValueError):archive.read(building,1)
            with self.assertRaises(ValueError):archive.read(export_id,999)
            _,records=archive.read(export_id,1);digest=next(r[2] for r in records if r[0]=='mesh')
            with db.connect() as c:c.execute('UPDATE mc_3d_asset SET payload=? WHERE sha256=?',(b'corrupt',digest))
            with self.assertRaises(ValueError):archive.mesh(digest)


if __name__=='__main__':unittest.main()

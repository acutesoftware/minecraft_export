import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from minecraft_viewer.legacy_blocks import DYES, legacy_name, legacy_names, LEGACY_NAMES
from minecraft_viewer.java_reader import surface_arrays, _surface_samples
from minecraft_viewer.mesh3d import MeshWorld, decode_volume, mesh_volume, material, legacy_properties
from minecraft_viewer.textures3d import TextureAtlas


class LegacyTests(unittest.TestCase):
    def test_all_dye_metadata_survives_every_decode_path(self):
        for block_id, family in ((35,'wool'),(95,'stained_glass'),(159,'terracotta'),
                                 (160,'stained_glass_pane'),(171,'carpet'),(251,'concrete'),(252,'concrete_powder')):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as tmp:
                blocks=np.zeros(4096,dtype=np.int8)
                blocks[:16]=block_id if block_id<128 else block_id-256
                data=np.zeros(2048,dtype=np.int8)
                data[:8]=np.arange(0,16,2,dtype=np.uint8) | (np.arange(1,16,2,dtype=np.uint8)<<4)
                section={'Y':0,'Blocks':blocks,'Data':data}
                chunk={'Level':{'Sections':[section]}}
                expected=['minecraft:'+dye+'_'+family for dye in DYES]
                self.assertEqual(decode_volume(chunk)[1][0,0].tolist(),expected)
                reader=MeshWorld(tmp,tmp,'test')
                with patch.object(reader,'chunk',return_value=chunk):
                    actual=reader.section(0,0,0)[0,0]
                self.assertEqual([reader.block_names[i] for i in actual],expected)
                for fast in (False,True):
                    if fast:chunk['Level']['HeightMap']=[1]*256
                    metrics=dict.fromkeys(('heightmaps','surface','fast','fallback'),0)
                    self.assertEqual(surface_arrays(chunk,metrics)[0][0].tolist(),expected)
                self.assertEqual([s['block'] for s in _surface_samples(chunk,0,0,(0,0,16,1))],expected)

    def test_extended_ids_do_not_alias_vanilla_and_registry_is_complete(self):
        section={'Blocks':np.zeros(4096,dtype=np.int8),'Add':np.zeros(2048,dtype=np.int8)}
        section['Blocks'][0]=35;section['Add'][0]=1
        self.assertEqual(legacy_names(section)[0],'minecraft:legacy_unknown_291')
        self.assertEqual(set(LEGACY_NAMES),set(range(253))|{255})
        self.assertEqual(legacy_name(5,5),'minecraft:dark_oak_planks')
        self.assertEqual(legacy_name(1,6),'minecraft:polished_andesite')
        self.assertEqual(legacy_name(188),'minecraft:spruce_fence')

    def test_112_model_names_and_renamed_assets(self):
        stream=io.BytesIO();Image.new('RGBA',(16,16),(40,20,10,255)).save(stream,format='PNG')
        assets={'assets/minecraft/textures/blocks/stone.png':stream.getvalue()}
        for name in ('black_wool','silver_concrete','red_stained_hardened_clay','stonebrick','fence'):
            assets[f'assets/minecraft/blockstates/{name}.json']=json.dumps({'variants':{'normal':{'model':name}}}).encode()
            assets[f'assets/minecraft/models/block/{name}.json']=json.dumps({'parent':'block/cube_all','textures':{'all':f'blocks/{name}'}}).encode()
            assets[f'assets/minecraft/textures/blocks/{name}.png']=stream.getvalue()
        assets['assets/minecraft/models/block/cube_all.json']=b'{"textures":{"particle":"#all"},"elements":[{"faces":{"up":{"texture":"#all"}}}]}'
        atlas=TextureAtlas(assets)
        for modern,old in (('black_wool','black_wool'),('light_gray_concrete','silver_concrete'),
                           ('red_terracotta','red_stained_hardened_clay'),('stone_bricks','stonebrick'),('oak_fence','fence')):
            self.assertEqual(atlas.resolve_texture('minecraft:'+modern,'up'),f'assets/minecraft/textures/blocks/{old}.png')
        self.assertEqual(atlas.render_shape('minecraft:oak_fence'),'fence')

    def test_fence_is_a_post_and_connects_across_chunk_boundary(self):
        padded=np.full((3,18,18),'minecraft:air',dtype=object)
        padded[1,2,16]='minecraft:oak_fence'
        def mesh():return mesh_volume(padded,0,np.zeros((16,16)),{})
        post=mesh()
        self.assertEqual(len(post['vertices']),36)
        np.testing.assert_allclose(post['vertices'].min(axis=0),(15.375,0,1.375))
        np.testing.assert_allclose(post['vertices'].max(axis=0),(15.625,1,1.625))
        padded[1,2,17]='minecraft:oak_fence'
        connected=mesh()
        self.assertEqual(len(connected['vertices']),108)
        self.assertEqual(connected['vertices'][:,0].max(),16)
        triangles=connected['vertices'].reshape(-1,3,3)
        cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        self.assertTrue((np.sum(cross*connected['normals'][::3],axis=1)<0).all())

    def test_fence_does_not_occlude_adjacent_cube(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader=MeshWorld(tmp,tmp,'test')
            padded=np.zeros((3,18,18),dtype=np.uint32)
            padded[1,2,2]=reader.block_id('minecraft:oak_fence')
            padded[1,2,3]=reader.block_id('minecraft:stone')
            result=mesh_volume(padded,0,np.zeros((16,16)),{},materials=reader.materials,
                               block_names=reader.block_names,block_shapes=reader.block_shapes)
            self.assertEqual(len(result['vertices']),144) # Full stone cube + post + two rails.
            red=material('minecraft:red_stained_glass',{})
            blue=material('minecraft:blue_stained_glass',{})
            self.assertNotEqual(red[:3],blue[:3]);self.assertEqual(red[3],.4)

    def test_gate_metadata_opens_and_rotates_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader=MeshWorld(tmp,tmp,'test')
            def mesh(data):
                padded=np.zeros((3,18,18),dtype=np.uint32)
                padded[1,1,1]=reader.block_id('minecraft:oak_fence_gate',legacy_properties(107,data))
                return mesh_volume(padded,0,np.zeros((16,16)),{},materials=reader.materials,
                                   block_names=reader.block_names,block_shapes=reader.block_shapes,
                                   block_properties=reader.block_properties)['vertices']
            closed=mesh(0);opened=mesh(4);rotated=mesh(1)
            self.assertLess(np.ptp(closed[:,2]),.2)
            self.assertGreater(np.ptp(opened[:,2]),.5)
            self.assertLess(np.ptp(rotated[:,0]),.2)


if __name__=='__main__':unittest.main()

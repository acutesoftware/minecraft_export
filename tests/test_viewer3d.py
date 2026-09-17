import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from minecraft_viewer.mesh3d import mesh_volume, distant_mesh, decode_volume, MeshWorld, minecraft_to_renderer, renderer_to_minecraft, mesh_to_renderer, terrain_jobs, render_shape, legacy_properties
from minecraft_viewer.viewer3d import read_archive


class MeshTests(unittest.TestCase):
    def mesh(self,blocks):
        padded=np.full((3,18,18),'minecraft:air',dtype=object)
        for x,z,name in blocks:padded[1,z+1,x+1]=name
        return mesh_volume(padded,0,np.zeros((16,16)),{'fallback':'#808080'})

    def test_internal_faces_removed(self):
        result=self.mesh([(1,1,'minecraft:stone'),(2,1,'minecraft:stone')])
        self.assertEqual(len(result['vertices']),10*6)

    def test_faces_wound_for_ursina_with_outward_normals(self):
        result=self.mesh([(1,1,'mod:unknown')])
        self.assertEqual(len(result['vertices']),36)
        triangles=result['vertices'].reshape(-1,3,3)
        cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        self.assertTrue((np.sum(cross*result['normals'][::3],axis=1)<0).all())

    def test_adjacent_water_has_no_internal_faces(self):
        result=self.mesh([(1,1,'minecraft:water'),(2,1,'minecraft:water')])
        self.assertEqual(len(result['vertices']),60)
        self.assertTrue((result['colors'][:,3]<1).all())

    def test_chunk_edge_neighbor_culls_face(self):
        padded=np.full((3,18,18),'minecraft:air',dtype=object)
        padded[1,1,16:18]='minecraft:stone'
        result=mesh_volume(padded,0,np.zeros((16,16)),{})
        self.assertEqual(len(result['vertices']),30)

    def test_deep_blocks_not_meshed(self):
        padded=np.full((40,18,18),'minecraft:air',dtype=object)
        padded[1,1,1]='minecraft:stone'
        result=mesh_volume(padded,0,np.full((16,16),35),{})
        self.assertEqual(len(result['vertices']),0)

    def test_cutout_plant_does_not_cull_supporting_or_adjacent_blocks(self):
        padded=np.full((4,18,18),'minecraft:air',dtype=object)
        padded[1,2,2]='minecraft:stone';padded[2,2,2]='minecraft:grass'
        padded[2,2,3]='minecraft:stone'
        result=mesh_volume(padded,0,np.zeros((16,16)),{})
        # Both stone cubes retain every face behind the non-occluding plant;
        # crossed plant adds 24 double-sided vertices.
        self.assertEqual(len(result['vertices']),96)
        plant=result['vertices'][72:]
        self.assertTrue(((plant[:,1]>=1)&(plant[:,1]<=2)).all())
        self.assertEqual(render_shape('minecraft:short_grass'),'cross')

    def test_alpha_cube_renders_but_does_not_occlude_neighbor(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            stone=reader.block_id('minecraft:stone');leaves=reader.block_id('minecraft:oak_leaves')
            reader.block_shapes[leaves]='cutout_cube'
            padded=np.zeros((3,18,18),dtype=np.uint32);padded[1,2,2]=stone;padded[1,2,3]=leaves
            result=mesh_volume(padded,0,np.zeros((16,16)),reader.colors,materials=reader.materials,
                               block_names=reader.block_names,block_properties=reader.block_properties,block_shapes=reader.block_shapes)
            # Stone retains its face behind the leaves; the reverse hidden leaf
            # face is still culled because stone is fully opaque.
            self.assertEqual(len(result['vertices']),66)

    def test_rail_is_thin_top_and_does_not_hide_support_block(self):
        padded=np.full((4,18,18),'minecraft:air',dtype=object)
        padded[1,2,2]='minecraft:stone';padded[2,2,2]='minecraft:rail'
        result=mesh_volume(padded,0,np.zeros((16,16)),{})
        self.assertEqual(len(result['vertices']),42) # complete support cube + rail plane
        rail=result['vertices'][-6:]
        np.testing.assert_allclose(rail[:,1],1.0625)
        self.assertEqual(render_shape('minecraft:powered_rail'),'rail')

    def test_wall_torch_preserves_facing_and_is_not_a_cube(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            east=reader.block_id('minecraft:wall_torch',{'facing':'east'})
            north=reader.block_id('minecraft:wall_torch',{'facing':'north'})
            self.assertNotEqual(east,north)
            padded=np.zeros((3,18,18),dtype=np.uint32);padded[1,2,2]=east
            result=mesh_volume(padded,0,np.zeros((16,16)),reader.colors,materials=reader.materials,
                               block_names=reader.block_names,block_properties=reader.block_properties)
            self.assertEqual(len(result['vertices']),12)
            self.assertGreater(result['vertices'][:,0].mean(),.5)
            self.assertEqual(render_shape('minecraft:redstone_wall_torch'),'torch')

    def test_legacy_nibble_data_preserves_torch_facing(self):
        blocks=np.zeros(4096,dtype=np.uint8);blocks[0]=50;blocks[1]=50
        metadata=np.zeros(2048,dtype=np.uint8);metadata[0]=1|(4<<4)
        chunk={'Level':{'Sections':[{'Y':0,'Blocks':blocks,'Data':metadata}]}}
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            with patch.object(reader,'chunk',return_value=chunk):section=reader.section(0,0,0)
            east,north=int(section.reshape(-1)[0]),int(section.reshape(-1)[1])
            self.assertEqual(reader.block_properties[east],{'facing':'east'})
            self.assertEqual(reader.block_properties[north],{'facing':'north'})
            self.assertEqual(legacy_properties(50,5),{'facing':'up'})

    def test_negative_y_decode_and_coordinate_identity(self):
        chunk={'DataVersion':3105,'sections':[{'Y':-4,'block_states':{'palette':[{'Name':'minecraft:stone'}]}}]}
        low,blocks=decode_volume(chunk)
        self.assertEqual(low,-64);self.assertEqual(blocks.shape,(16,16,16))
        self.assertEqual(minecraft_to_renderer(100,75,-200),(100,75,200))
        self.assertEqual(renderer_to_minecraft(*minecraft_to_renderer(100,75,-200)),(100,75,-200))

    def test_renderer_reflection_preserves_front_faces(self):
        source=self.mesh([(1,1,'minecraft:stone')])
        result=mesh_to_renderer(source)
        triangles=result['vertices'].reshape(-1,3,3)
        cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        self.assertTrue((np.sum(cross*result['normals'][::3],axis=1)<0).all())

    def test_distant_mesh_and_missing_cells(self):
        names=np.full((16,16),'minecraft:grass_block',dtype=object)
        result=distant_mesh(names,np.full((16,16),64),np.ones((16,16),dtype=bool),{})
        self.assertEqual(len(result['vertices']),96)
        self.assertTrue((result['normals'][:,1]>0).all())
        self.assertEqual(len(distant_mesh(names,np.zeros((16,16)),np.zeros((16,16),dtype=bool),{})['vertices']),0)

    def test_npz_cache_reused_without_chunk_decode(self):
        chunk={'Level':{'Sections':[{'Y':0,'Blocks':np.full(4096,1)}],'HeightMap':[16]*256}}
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source';source.mkdir()
            reader=MeshWorld(source,Path(temp)/'cache','world-test')
            with patch.object(reader,'chunk',return_value=chunk):first=reader.mesh(-1,0,False)
            with patch.object(reader,'chunk',side_effect=AssertionError('cache missed')):second=reader.mesh(-1,0,False)
            np.testing.assert_array_equal(first['vertices'],second['vertices'])

    def test_other_dimensions_rejected(self):
        with self.assertRaises(ValueError):read_archive('absent.db',1,'minecraft:the_nether')

    def test_numeric_mesh_matches_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            names=np.full((20,18,18),'minecraft:air',dtype=object)
            rng=np.random.default_rng(42)
            palette=np.array(['minecraft:air','minecraft:stone','minecraft:glass','minecraft:water'])
            names[:]=palette[rng.integers(0,4,names.shape)]
            ids=np.zeros(names.shape,dtype=np.uint32)
            for name in palette:ids[names==name]=reader.block_id(str(name))
            heights=np.full((16,16),10)
            reference=mesh_volume(names,-5,heights,reader.colors)
            numeric=mesh_volume(ids,-5,heights,reader.colors,materials=reader.materials)
            for key in reference:np.testing.assert_array_equal(reference[key],numeric[key])

    def test_section_band_reuses_decode_and_handles_negative_y(self):
        chunk={'DataVersion':3105,'sections':[{'Y':-1,'block_states':{'palette':[{'Name':'minecraft:stone'}]}}]}
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            with patch.object(reader,'chunk',return_value=chunk) as read:
                band=reader.band(0,0,-4,4)
                edge=reader.band(0,0,-4,4,('x',15))
                self.assertEqual(read.call_count,2)
            np.testing.assert_array_equal(band[:,:,15],edge)
            self.assertTrue((band[:4]!=0).all())
            self.assertTrue((band[4:]==0).all())
            reader.begin_reload()
            self.assertFalse(reader.sections)

    def test_jobs_cover_known_chunks_once_and_batch_negative_coords(self):
        known={(x,z) for x in range(-16,17) for z in range(-16,17)}
        jobs=terrain_jobs(known,0,0,16,128)
        members=[coord for key,coords in jobs for coord in coords]
        self.assertEqual(len(members),17*17)
        self.assertEqual(len(members),len(set(members)))
        self.assertLess(len(jobs),len(members))
        for key,coords in jobs:
            if key[0]=='far':
                self.assertTrue(all(0<=x-key[1]<8 and 0<=z-key[2]<8 for x,z in coords))
            else:self.assertEqual(len(coords),1)

    def test_batch_offsets_cache_and_membership_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            key=('far',-8,0);coords=((-8,0),(-7,0))
            signature=reader.job_signature(key,coords)
            self.assertNotEqual(signature,reader.job_signature(key,coords[:1]))
            sample=distant_mesh(np.full((16,16),'minecraft:stone'),np.zeros((16,16)),np.ones((16,16),bool),{})
            with patch.object(reader,'mesh',side_effect=lambda *args,**kwargs:{k:v.copy() for k,v in sample.items()}):
                result=reader.job_mesh(key,coords,signature)
            np.testing.assert_array_equal(result['vertices'][96:],sample['vertices']+[16,0,0])
            with patch.object(reader,'mesh',side_effect=AssertionError('cache missed')):
                cached=reader.job_mesh(key,coords,signature)
            np.testing.assert_array_equal(cached['vertices'],result['vertices'])

    def test_signatures_refresh_on_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            before=reader.signature(0,0,True)
            path=reader.region(0,0);path.parent.mkdir();path.write_bytes(b'changed')
            self.assertEqual(before,reader.signature(0,0,True))
            reader.begin_reload()
            self.assertNotEqual(before,reader.signature(0,0,True))

    def test_damaged_chunk_does_not_hide_or_cache_entire_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            reader=MeshWorld(temp,temp,'test')
            key=('far',0,0);coords=((0,0),(1,0))
            signature=reader.job_signature(key,coords)
            sample=distant_mesh(np.full((16,16),'minecraft:stone'),np.zeros((16,16)),np.ones((16,16),bool),{})
            with self.assertLogs(level='ERROR'),patch.object(reader,'mesh',side_effect=[OSError('damaged'),sample]):
                result=reader.job_mesh(key,coords,signature)
            self.assertEqual(result['failed_chunks'],1)
            self.assertEqual(len(result['vertices']),96)
            self.assertFalse((reader.cache/'batches'/f'{signature}.npz').exists())


if __name__=='__main__':unittest.main()

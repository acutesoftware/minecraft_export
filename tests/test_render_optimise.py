import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import unittest
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from minecraft_viewer.java_reader import surface_arrays, unpack_values
from minecraft_viewer.tile_cache import TileCache, render_tile
from minecraft_viewer.db import ArchiveDB
import tempfile
import numpy as np


def pack(values,bits,padded=True):
    size = (len(values)+(64//bits)-1)//(64//bits) if padded else (len(values)*bits+63)//64
    words = [0]*size
    for i,value in enumerate(values):
        bit = (i//(64//bits))*64+i%(64//bits)*bits if padded else i*bits
        word,offset = divmod(bit,64)
        words[word] |= int(value)<<offset & ((1<<64)-1)
        if offset+bits>64: words[word+1] |= int(value)>>(64-offset)
    return np.array(words,dtype=np.uint64)


class OptimiseTests(unittest.TestCase):
    def test_packing_formats(self):
        for padded in (False,True):
            values = np.arange(256)%31
            np.testing.assert_array_equal(unpack_values(pack(values,5,padded),np.arange(256),5,padded),values)

    def test_world_surface_offset_negative_y(self):
        # Heightmap is relative to minimum Y and points one ABOVE the block.
        chunk = {'DataVersion':3105,'yPos':-4,'Heightmaps':{'WORLD_SURFACE':pack([17]*256,9)},
                 'sections':[{'Y':-3,'block_states':{'palette':[{'Name':'minecraft:bricks'}]}}]}
        metrics = defaultdict(float)
        names,ys,biomes,visible = surface_arrays(chunk,metrics)
        self.assertTrue((ys==-48).all())
        self.assertTrue((names=='minecraft:bricks').all())
        self.assertTrue(visible.all())
        self.assertEqual(metrics['fast'],1)
        self.assertEqual(metrics['fallback'],0)

    def test_legacy_heightmap_and_fallback_agree(self):
        blocks=np.zeros(4096,dtype=np.int8);blocks[5*256:6*256]=45
        chunk={'Level':{'HeightMap':[6]*256,'Sections':[{'Y':0,'Blocks':blocks}]}}
        a=surface_arrays(chunk,defaultdict(float))
        del chunk['Level']['HeightMap']
        b=surface_arrays(chunk,defaultdict(float))
        for left,right in zip(a,b): np.testing.assert_array_equal(left,right)

    def test_process_skips_caching_unsaved_regions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'world';source.mkdir()
            db=ArchiveDB(root/'a.db')
            cache=TileCache(db,root/'maps',1,1,'minecraft:overworld',source)
            with ProcessPoolExecutor(max_workers=1) as pool:
                image=pool.submit(render_tile,cache,'surface',-1,0).result(timeout=20)
            self.assertEqual(image.size,(512,512))
            newer=TileCache(db,root/'maps',1,2,'minecraft:overworld',source)
            self.assertIsNone(newer.cached('surface',-1,0))


if __name__=='__main__': unittest.main()

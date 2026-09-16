import sys
import tempfile
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from minecraft_viewer.map_view import Camera, MapView
from minecraft_viewer.tile_cache import TileCache, BACKGROUND
from minecraft_viewer.java_reader import _surface_samples


class NavigationTests(unittest.TestCase):
    def test_empty_regions_are_not_render_progress(self):
        from PIL import Image
        view = Mock()
        a,b = (1,'surface',0,0),(1,'surface',1,0)
        empty = Image.new('RGB',(512,512)); empty.info['empty_region']=True
        view.visible_keys={a,b}; view.images={b:empty}; view.failed=set()
        view.active_job=None; view.last_status=None
        MapView._report_status(view)
        text,done,total=view.on_status.call_args.args
        self.assertEqual((done,total),(0,1))
        self.assertIn('1 empty areas skipped',text)

    def test_status_counts_only_current_view_and_finishes_with_errors(self):
        view = Mock()
        a,b,c = (1,'surface',0,0),(1,'surface',1,0),(0,'surface',9,9)
        view.visible_keys = {a,b}
        view.images = {a:None,c:None}
        view.failed = set()
        view.active_job = None
        view.last_status = None
        MapView._report_status(view)
        text,done,total = view.on_status.call_args.args
        self.assertEqual((done,total),(1,2))
        self.assertIn('Loading map',text)
        view.failed = {b}
        MapView._report_status(view)
        text,done,total = view.on_status.call_args.args
        self.assertEqual((done,total),(2,2))
        self.assertIn('Finished',text)
        self.assertIn('1 failed',text)

    def test_cursor_zoom_keeps_world_point(self):
        camera = Camera(-521, 247)
        before = camera.world(120, 190, 800, 600)
        camera.zoom_at(2,120,190,800,600)
        self.assertEqual(before,camera.world(120,190,800,600))

    def test_negative_region_edges(self):
        camera = Camera(-256,256)
        self.assertEqual(camera.regions(512,512),[(-1,0)])
        self.assertEqual(camera.screen(-512,0,512,512),(0,0))
        self.assertEqual(camera.screen(0,512,512,512),(512,512))

    def test_adjacent_tiles_share_edge_at_every_zoom(self):
        for zoom in (.125,.25,.5,1,2,4,8):
            camera = Camera(-1.37,76.1,zoom)
            xs = [round(camera.screen(x,0,813,607)[0]) for x in (-512,0,512)]
            self.assertEqual(xs[1]-xs[0],round(512*zoom))
            self.assertEqual(xs[2]-xs[1],round(512*zoom))


class TileTests(unittest.TestCase):
    def test_cache_reuse_staleness_and_offline_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'world'; (source/'region').mkdir(parents=True)
            region = source/'region/r.-1.0.mca'; region.touch()
            cache = TileCache(Mock(),root/'maps',1,2,'minecraft:overworld',source)
            sample = {'x':-1,'z':0,'height':100,'block':'minecraft:stone','biome':'minecraft:plains'}
            names = np.full((16,16),'minecraft:stone',dtype=object)
            visible = np.zeros((16,16),dtype=bool); visible[0,15] = True
            surfaces = [(31,0,(names,np.full((16,16),100),np.full((16,16),'minecraft:plains',dtype=object),visible))]
            with patch('minecraft_viewer.tile_cache.JavaWorldReader.iter_region_surfaces',return_value=surfaces) as read:
                tile = cache.load('surface',-1,0)
                self.assertNotEqual(tile.getpixel((511,0)),BACKGROUND)
                self.assertEqual(tile.getpixel((0,0)),BACKGROUND)
                self.assertEqual(tile.size,(512,512))
                cache.load('surface',-1,0)
                self.assertEqual(read.call_count,1)
            region.write_bytes(b'changed')
            with patch('minecraft_viewer.tile_cache.JavaWorldReader.iter_region_surfaces',return_value=surfaces) as read:
                cache.load('surface',-1,0)
                self.assertEqual(read.call_count,1)
            region.unlink()
            with patch('minecraft_viewer.tile_cache.JavaWorldReader.iter_region_surfaces',side_effect=AssertionError('source read')):
                self.assertNotEqual(cache.load('surface',-1,0).getpixel((511,0)),BACKGROUND)

    def test_player_roof_covers_terrain(self):
        ground = [2]*4096
        roof = [0]*4096; roof[0] = 45
        chunk = {'Level': {'Sections': [{'Y':0,'Blocks':ground},{'Y':5,'Blocks':roof}]}}
        samples = list(_surface_samples(chunk,0,0,(0,0,1,1)))
        self.assertEqual(samples[0]['block'],'minecraft:bricks')
        self.assertEqual(samples[0]['height'],80)


if __name__ == '__main__':
    unittest.main()

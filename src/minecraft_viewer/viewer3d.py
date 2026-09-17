"""Experimental standalone Ursina viewer. Run with python -m minecraft_viewer.viewer3d."""
import argparse
import json
import logging
import math
import queue
import re
import sqlite3
import threading
from contextlib import closing
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from time import perf_counter

from .mesh3d import MeshWorld, minecraft_to_renderer, terrain_jobs
from .java_reader import surface_arrays
from .shader3d import terrain_shader
from .textures3d import TextureAtlas,find_client,read_assets
from .archive3d import SceneArchive
from .db import ArchiveDB


def read_archive(db,world_id,dimension):
    if dimension!='minecraft:overworld':raise ValueError('Experimental 3D currently supports the Overworld only')
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        connection.row_factory=sqlite3.Row
        world=connection.execute('SELECT * FROM mc_world WHERE world_id=?',(world_id,)).fetchone()
        dim=connection.execute("SELECT * FROM mc_dimension WHERE world_id=? AND dimension_key=? ORDER BY import_id DESC LIMIT 1",(world_id,dimension)).fetchone()
        if world is None or dim is None:raise ValueError('Import this world and its Overworld before opening 3D')
        coords=connection.execute('SELECT chunk_x,chunk_z FROM mc_chunk WHERE import_id=? AND dimension_key=?',(dim['import_id'],dimension)).fetchall()
        return dict(world),dict(dim),{tuple(r) for r in coords}


def run(args):
    # Import only in the child; a graphics failure cannot break the Tk archive.
    from ursina import Ursina, Entity, Mesh, Vec3, Vec4, Text, Button, Slider, DirectionalLight, AmbientLight
    from ursina import camera, mouse, held_keys, window, scene, application, time, color, destroy, invoke
    from ursina.shaders import lit_with_shadows_shader
    from panda3d.core import Filename, TransparencyAttrib, loadPrcFileData
    import numpy as np

    archive=SceneArchive(args.db);atlas=None;atlas_png=None;replay_records=[];replay_manifest=None
    texture_notice='Flat colours (no texture source selected)'
    if args.export_id:
        replay_manifest,replay_records=archive.read(args.export_id,args.world_id)
        world=replay_manifest['world'];dimension=replay_manifest['dimension'];known=set()
        args.detailed_radius=replay_manifest['detailed_radius'];args.distant_radius=replay_manifest['distant_radius']
        atlas_record=next((r for r in replay_records if r[0]=='atlas'),None)
        if atlas_record:atlas_png=archive.payload(atlas_record[2])
        texture_notice=f'Database export #{args.export_id} ({replay_manifest["export_status"]}) — archived area only'
    else:
        world,dimension,known=read_archive(args.db,args.world_id,args.dimension)
        ArchiveDB(args.db)  # Additive schema migration; game files remain read-only.
        try:
            texture_source=find_client(args.textures,world.get('minecraft_version'))
            atlas=TextureAtlas(read_assets(texture_source));atlas_png=atlas.png
            texture_notice=f'Textures: {texture_source.name}'
        except (FileNotFoundError,ValueError) as exc:
            if args.textures:raise
            texture_notice=str(exc)
    output=Path(args.output).resolve()
    source=Path(dimension['source_path']).resolve()
    if not args.export_id and not source.is_dir():
        raise FileNotFoundError('Source world is unavailable. Open a saved scene from the 3D Exports tab instead.')
    if output==source or source in output.parents:
        raise ValueError('3D cache/screenshots must be outside the Minecraft source world')
    output.mkdir(parents=True,exist_ok=True)
    logging.info('3D viewer world=%s detail=%s distant=%s',world['world_name'],args.detailed_radius,args.distant_radius)
    reader=None if args.export_id else MeshWorld(source,output/'cache',world['world_uuid'],atlas)
    sx,sz=world['spawn_x'] or 0,world['spawn_z'] or 0
    sy=world['spawn_y'] or 64
    try:
        chunk=reader.chunk(sx//16,sz//16) if reader else None
        if chunk:
            _,heights,_,visible=surface_arrays(chunk,defaultdict(float))
            if visible[sz%16,sx%16]:sy=int(heights[sz%16,sx%16])+1
    except Exception:logging.exception('Could not determine surface at spawn')
    initial_y=sy+25
    try:
        chunk=reader.chunk((sx+30)//16,(sz+30)//16) if reader else None
        if chunk:
            _,heights,_,visible=surface_arrays(chunk,defaultdict(float))
            if visible[(sz+30)%16,(sx+30)%16]:
                initial_y=max(initial_y,int(heights[(sz+30)%16,(sx+30)%16])+12)
    except Exception:logging.exception('Could not determine camera clearance')
    if args.smoke_test:loadPrcFileData('', 'window-type offscreen\naudio-library-name null')
    app=Ursina(title=f"Experimental 3D — {world['world_name']}",borderless=False,development_mode=False,
               window_type='offscreen' if args.smoke_test else 'onscreen',size=(1280,720))
    window.exit_button.enabled=False
    window.fps_counter.enabled=False
    camera.clip_plane_far=max(2048,args.distant_radius*3)
    camera.fov=65
    camera.position=minecraft_to_renderer(sx+30,initial_y,sz+30)
    def aim_at_spawn():
        dx,dy,dz=sx-camera.x,sy-camera.y,sz-camera.z
        camera.rotation=(math.degrees(math.atan2(-dy,math.hypot(dx,dz))),math.degrees(math.atan2(dx,dz)),0)
    aim_at_spawn()
    if replay_manifest:
        camera.position=tuple(replay_manifest['camera_position']);camera.rotation=tuple(replay_manifest['camera_rotation'])
    from ursina import Texture
    from PIL import Image
    import io
    terrain_texture=Texture(Image.open(io.BytesIO(atlas_png)).convert('RGBA') if atlas_png else Image.new('RGBA',(1,1),'white'))
    terrain_texture.filtering=None
    from panda3d.core import SamplerState
    terrain_texture._texture.setWrapU(SamplerState.WM_clamp)
    terrain_texture._texture.setWrapV(SamplerState.WM_clamp)
    sun=DirectionalLight(shadows=False)
    ambient=AmbientLight(color=Vec4(.25,.25,.3,1))
    # Atlas UVs share one texture across all terrain batches.
    shader=lit_with_shadows_shader if args.shadows else terrain_shader()
    try:
        if args.shadows:
            sun.shadows=True
            bounds=Entity(model='cube',position=(sx,sy,sz),scale=(args.detailed_radius*2,256,args.detailed_radius*2),visible=False)
            sun.update_bounds(bounds)
    except Exception:
        logging.exception('Shadows unavailable; continuing without them');sun.shadows=False;shader=terrain_shader()

    class Controller(Entity):
        def __init__(self):
            super().__init__()
            self.photo=False;self.speed=32;self.hidden=False;self.loading=False
            self.messages=queue.Queue(maxsize=8);self.stop=threading.Event();self.generation=0
            self.terrain={};self.loaded=0;self.requested=0;self.errors=0;self.started=perf_counter()
            self.export_id=None;self.notice=texture_notice
            self.hud=Entity(parent=camera.ui)
            self.info=Text(parent=self.hud,position=(-.86,.46),scale=.8)
            self.panel=Entity(parent=self.hud,enabled=False)
            self.sliders={}
            specs=[('Time of day',0,24,15),('Sun azimuth',0,360,225),('FOV',30,100,65),('Atmosphere',0,1,.3),('Speed',2,256,32),
                   ('Detailed radius',16,256,args.detailed_radius),('Distant radius',32,1024,args.distant_radius)]
            for index,(name,low,high,default) in enumerate(specs):
                self.sliders[name]=Slider(parent=self.panel,text=name,min=low,max=high,default=default,
                    position=(-.48,.22-index*.075),scale=.7,dynamic=True)
                self.sliders[name].on_value_changed=self.environment
            presets={'Clear Day':(12,.1),'Golden Hour':(17,.35),'Sunset':(18,.45),'Misty Morning':(7,.75),'Night':(0,.25)}
            for index,(name,values) in enumerate(presets.items()):
                Button(parent=self.panel,text=name,position=(.55,.22-index*.07),scale=(.23,.05),
                       on_click=lambda v=values:self.preset(*v))
            Button(parent=self.panel,text='Save Screenshot (F2)',position=(.48,-.2),scale=(.35,.06),on_click=self.screenshot)
            Button(parent=self.panel,text='Reload Around Camera',position=(.48,-.28),scale=(.35,.06),on_click=self.reload)
            Button(parent=self.panel,text='Explore (P)',position=(.48,-.36),scale=(.35,.06),on_click=self.toggle_photo)
            if replay_manifest:
                for name,value in replay_manifest.get('settings',{}).items():
                    if name in self.sliders:self.sliders[name].value=value
            self.environment();self.reload()
            if not args.smoke_test:mouse.locked=True

        def environment(self):
            if len(self.sliders)<7:return
            hour=self.sliders['Time of day'].value
            altitude=math.sin((hour-6)/24*math.tau)
            warmth=max(0,1-abs(altitude)*2)
            daylight=max(.04,min(1.15,altitude*1.4+.55))
            night=np.array([.025,.035,.08]);day=np.array([.4,.66,.9]);warm=np.array([.78,.38,.22])
            sky=night+(day-night)*max(0,min(1,altitude*1.2+.2))
            if altitude>-.2:sky=sky*(1-warmth*.65)+warm*warmth*.65
            window.color=Vec4(*sky,1);scene.fog_color=window.color
            haze=self.sliders['Atmosphere'].value
            far=self.sliders['Distant radius'].value
            scene.fog_density=(max(10,far*(.75-.65*haze)),max(100,far*(1.4-.65*haze)))
            sun.rotation=(altitude*75,self.sliders['Sun azimuth'].value,0)
            sun.color=Vec4(daylight,daylight*(1-warmth*.3),daylight*(1-warmth*.55),1)
            ambient.color=Vec4(.10+daylight*.32,.11+daylight*.32,.15+daylight*.30,1)
            azimuth=math.radians(self.sliders['Sun azimuth'].value)
            direction=Vec3(math.cos(azimuth),altitude,math.sin(azimuth)).normalized()
            scene.setShaderInput('sunlight_direction',direction)
            scene.setShaderInput('sunlight_color',Vec3(sun.color.x,sun.color.y,sun.color.z))
            scene.setShaderInput('ambient_color',Vec3(ambient.color.x,ambient.color.y,ambient.color.z))
            scene.setShaderInput('horizon_color',Vec3(*sky))
            from ursina import Vec2
            scene.setShaderInput('fog_range',Vec2(*scene.fog_density))
            camera.fov=self.sliders['FOV'].value;self.speed=self.sliders['Speed'].value

        def preset(self,hour,haze):
            self.sliders['Time of day'].value=hour;self.sliders['Atmosphere'].value=haze;self.environment()

        def toggle_photo(self):
            self.photo=not self.photo;self.panel.enabled=self.photo
            if not args.smoke_test:mouse.locked=not self.photo

        def reload(self):
            if self.loading:return
            self.loaded=0;self.errors=0;self.loading=True;self.started=perf_counter()
            cx,cz=int(math.floor(camera.x/16)),int(math.floor(camera.z/16))
            near=int(self.sliders['Detailed radius'].value);far=max(near,int(self.sliders['Distant radius'].value))
            camera.clip_plane_far=max(2048,far*3)
            work=terrain_jobs(known,cx,cz,near,far)
            replay_meshes={}
            if args.export_id:
                work=[]
                for role,name,digest,metadata in replay_records:
                    if role!='mesh':continue
                    entry=json.loads(metadata);key=tuple(entry['key'])
                    work.append((key,entry['chunks']));replay_meshes[key]=digest
            wanted={key for key,coords in work}
            for key in list(self.terrain):
                if key not in wanted:
                    for entity in self.terrain.pop(key)[1]:destroy(entity)
            existing={key:value[0] for key,value in self.terrain.items()}
            self.requested=sum(len(coords) for key,coords in work)
            manifest={'world':world,'dimension':dimension,'detailed_radius':near,'distant_radius':far,
                      'camera_position':list(camera.position),'camera_rotation':list(camera.rotation),
                      'settings':{name:slider.value for name,slider in self.sliders.items()},
                      'requested_chunks':self.requested,'centre_chunk':[cx,cz],
                      'scope':'Bounded visual scene: surface band, detailed near cubes, simplified distant shell; not gameplay or a full-world backup.',
                      'texture_fingerprint':atlas.fingerprint if atlas else None,
                      'coordinates':'Minecraft X/Y/Z, Y up; local vertices + mesh origin; clockwise triangles',
                      'mesh_format':'NPZ arrays: vertices float32 Nx3, normals Nx3, colors Nx4, uvs Nx2; no pickle',
                      'texture_format':'PNG RGBA atlas; nearest sampling; UV origin bottom left; first animation frame',
                      'renderer_version':'textured-cubes-1'}
            previous_export=self.export_id
            def send(value):
                while not self.stop.is_set():
                    try:self.messages.put(value,timeout=.2);return
                    except queue.Full:pass
            def build():
                # A reload must see source edits even if this process decoded the
                # same chunk previously; persistent meshes validate timestamps.
                if reader:reader.begin_reload()
                logging.info('3D requested chunks=%s jobs=%s retained_candidates=%s',self.requested,len(work),len(existing))
                export_id=None;export_errors=0
                if not args.export_id:
                    try:export_id=archive.begin(args.world_id,manifest,atlas)
                    except Exception:
                        logging.exception('Could not start database export');export_errors+=1
                for key,coords in work:
                    if self.stop.is_set():return
                    try:
                        signature=replay_meshes[key] if args.export_id else reader.job_signature(key,coords)
                        retained=existing.get(key)==signature
                        data=None if retained else archive.mesh(signature) if args.export_id else reader.job_mesh(key,coords,signature)
                        if export_id:
                            try:
                                if not (retained and previous_export and archive.copy_mesh(previous_export,export_id,key)):
                                    saved=data if data is not None else reader.job_mesh(key,coords,signature)
                                    archive.put_mesh(export_id,key,coords,saved)
                                    export_errors+=saved.get('failed_chunks',0)
                            except Exception:
                                logging.exception('Could not archive 3D mesh %s',key);export_errors+=len(coords)
                        send((key,signature,len(coords),data,None))
                    except Exception as exc:
                        export_errors+=len(coords)
                        logging.exception('Skipping unreadable 3D batch %s',key);send((key,None,len(coords),None,str(exc)))
                notice=texture_notice
                if export_id:
                    try:
                        archive.finish(export_id,export_errors)
                        self.export_id=export_id
                        notice=f'{texture_notice} | Database export #{export_id}: '+('PARTIAL — see log' if export_errors else 'saved')
                    except Exception:
                        logging.exception('Could not finish database export');notice='Database export FAILED — see log'
                elif not args.export_id:notice='Database export FAILED — see log'
                send((None,None,0,None,notice))
            self.thread=threading.Thread(target=build,daemon=True);self.thread.start()

        def screenshot(self):
            folder=output/'worlds'/world['world_uuid']/'renders';folder.mkdir(parents=True,exist_ok=True)
            safe=re.sub(r'[^\w.-]+','_',world['world_name'])[:80]
            path=folder/f'3d_{safe}_{datetime.now():%Y%m%d_%H%M%S_%f}.png'
            previous=self.hud.enabled;self.hud.enabled=False
            def save():
                try:
                    app.graphicsEngine.renderFrame();app.graphicsEngine.renderFrame()
                    if not app.win.saveScreenshot(Filename.fromOsSpecific(str(path))):raise OSError('Screenshot capture failed')
                    metadata={'render_type':'GENERATED_3D','world_uuid':world['world_uuid'],'dimension':args.dimension,
                              'camera':list(camera.position),'time_of_day':self.sliders['Time of day'].value,'fov':camera.fov}
                    path.with_suffix('.json').write_text(json.dumps(metadata,indent=2))
                    logging.info('Screenshot saved %s',path)
                    self.notice=f'Saved {path.name}'
                except Exception as exc:logging.exception('Screenshot failed');self.notice=str(exc)
                finally:self.hud.enabled=previous
            invoke(save,delay=.05)

        def input(self,key):
            if key=='p':self.toggle_photo()
            elif key=='h':self.hidden=not self.hidden;self.hud.enabled=not self.hidden
            elif key=='g':
                camera.position=(sx+30,initial_y,sz+30);aim_at_spawn()
            elif key=='f2':self.screenshot()
            elif key=='r':self.reload()
            elif key=='escape':
                if mouse.locked:mouse.locked=False
                elif self.photo:self.toggle_photo()
                else:self.stop.set();application.quit()
            elif key=='left mouse down' and not self.photo:mouse.locked=True
            elif key=='right mouse down' and self.photo:mouse.locked=True
            elif key=='right mouse up' and self.photo:mouse.locked=False
            elif key in ('scroll up','scroll down') and not self.photo:
                self.speed=max(2,min(256,self.speed*(1.25 if key=='scroll up' else .8)))
                self.sliders['Speed'].value=self.speed

        def update(self):
            scene.setShaderInput('eye_position',camera.world_position)
            if mouse.locked:
                camera.rotation_y+=mouse.velocity[0]*100
                camera.rotation_x=max(-89,min(89,camera.rotation_x-mouse.velocity[1]*100))
            if not self.photo or mouse.right:
                movement=camera.forward*(held_keys['w']-held_keys['s'])+camera.right*(held_keys['d']-held_keys['a'])+Vec3(0,held_keys['space']-held_keys['control'],0)
                camera.position+=movement*self.speed*(4 if held_keys['shift'] else 1)*min(time.dt,.1)
            upload_deadline=perf_counter()+.006
            while perf_counter()<upload_deadline:
                try:key,signature,count,data,error=self.messages.get_nowait()
                except queue.Empty:break
                if key is None:
                    self.loading=False;self.notice=error;logging.info('3D load finished total=%.3fs %s',perf_counter()-self.started,self.notice);continue
                self.loaded+=count
                if error:self.errors+=count;continue
                if data is None:continue  # Unchanged meshes stay on the GPU.
                failed=data.get('failed_chunks',0)
                self.errors+=failed
                for entity in self.terrain.pop(key,(None,[]))[1]:destroy(entity)
                entities=[]
                self.terrain[key]=(None if failed else signature,entities)
                start=perf_counter()
                # Separate translucent faces to keep opaque geometry depth writing.
                for translucent in (False,True):
                    select=(data['colors'][:,3]<1)==translucent
                    if not select.any():continue
                    buffer=np.ascontiguousarray(np.concatenate((data['vertices'][select],data['normals'][select],data['colors'][select],data['uvs'][select]),axis=1),dtype=np.float32)
                    mesh=Mesh(vertex_buffer=buffer.tobytes(),vertex_buffer_length=len(buffer),vertex_buffer_format='p3f,n3f,c4f,t2f',
                              triangles=list(range(len(buffer))),mode='triangle',static=True)
                    entity=Entity(model=mesh,position=minecraft_to_renderer(key[1]*16,0,key[2]*16),shader=shader,texture=terrain_texture)
                    if translucent:
                        entity.setTransparency(TransparencyAttrib.MAlpha);entity.setDepthWrite(False)
                    entities.append(entity)
                logging.info('3D GPU upload batch=%s chunks=%s %.3fs',key,count,perf_counter()-start)
            status=f'Loading {self.loaded}/{self.requested}' if self.loading else f'Finished ({self.errors} skipped)'
            self.info.text=f"{'PHOTO' if self.photo else 'EXPLORE'} | X {camera.x:.0f} Y {camera.y:.0f} Z {camera.z:.0f} | Speed {self.speed:.0f}\n{status}\nWASD / Space / Ctrl: fly | Shift: fast | G: spawn | P: photo | R: reload | H: HUD | F2: screenshot\n{getattr(self,'notice','')}"

    controller=Controller()
    if args.smoke_test:
        # Bounded graphics diagnostic: exercise lighting, upload and PNG capture.
        def smoke_end():
            if controller.loading and perf_counter()-controller.started<120:
                invoke(smoke_end,delay=1)
                return
            if args.smoke_reload and not getattr(controller,'smoke_reloaded',False):
                controller.smoke_reloaded=True
                controller.reload()
                invoke(smoke_end,delay=1)
                return
            controller.toggle_photo()
            controller.preset(17,.35)
            controller.sliders['FOV'].value=65
            controller.environment()
            controller.screenshot()
            invoke(application.quit,delay=.3)
        invoke(smoke_end,delay=8)
    try:app.run()
    finally:
        controller.stop.set()
        if hasattr(controller,'thread'):controller.thread.join(timeout=2)


def main():
    parser=argparse.ArgumentParser(description='Experimental read-only Minecraft 3D viewer')
    parser.add_argument('--world-id',type=int,required=True);parser.add_argument('--db',required=True)
    parser.add_argument('--dimension',default='minecraft:overworld')
    parser.add_argument('--output',default='output/3d')
    parser.add_argument('--detailed-radius',type=int,default=192)
    parser.add_argument('--distant-radius',type=int,default=768)
    parser.add_argument('--shadows',action='store_true')
    parser.add_argument('--textures',help='Minecraft folder, client JAR, resource-pack ZIP, or extracted assets root')
    parser.add_argument('--export-id',type=int,help='Replay a database visual export without the source world or Minecraft installation')
    parser.add_argument('--smoke-test',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--smoke-reload',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not 16<=args.detailed_radius<=256 or not args.detailed_radius<=args.distant_radius<=1024:
        parser.error('Use detailed radius 16–256 and distant radius detailed–1024')
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(filename='logs/viewer3d.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:run(args)
    except Exception:
        logging.exception('3D viewer failed')
        raise


if __name__=='__main__':main()

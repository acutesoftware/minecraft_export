"""Local Java assets -> deterministic atlas. Never downloads or modifies a game install."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image

FACE_NAMES=('east','west','up','down','south','north')


def validate_source(source):
    """Cheap preflight for the picker, without decoding PNGs or copying game code."""
    source=Path(source)
    def texture(name):
        return name.startswith('assets/') and '/textures/' in name and ('/block/' in name or '/blocks/' in name) and name.endswith('.png')
    if source.is_dir():
        found=any(texture(p.relative_to(source).as_posix()) for p in (source/'assets').rglob('*.png'))
    else:
        try:
            with zipfile.ZipFile(source) as archive:found=any(texture(name) for name in archive.namelist())
        except (OSError,zipfile.BadZipFile) as exc:raise ValueError('Choose a Java client JAR or resource-pack ZIP, not a launcher executable.') from exc
    if not found:
        raise ValueError('This source has no Java block textures. Server JARs and world saves are not texture sources. Choose the CLIENT JAR from .minecraft/versions/<version>/<version>.jar, or a Java resource-pack ZIP.')


def find_client(folder=None,version=None):
    root=Path(folder) if folder else Path(os.environ.get('APPDATA',str(Path.home())))/'.minecraft'
    if root.is_file():return root
    if (root/'assets').is_dir():return root
    candidates=list(root.glob('versions/*/*.jar'))
    if version:
        exact=[p for p in candidates if p.stem==version]
        if exact:return exact[0]
    if len(candidates)==1:return candidates[0]
    if candidates:raise ValueError('Multiple Minecraft versions found; select the desired client JAR explicitly.')
    raise FileNotFoundError('No Java client assets found. Choose a client .jar, resource-pack .zip, or extracted assets folder.')


def read_assets(source):
    validate_source(source)
    def wanted(name):
        parts=name.split('/')
        return len(parts)>3 and parts[0]=='assets' and (
            (parts[2]=='textures' and parts[3] in ('block','blocks') and name.endswith(('.png','.mcmeta'))) or
            (parts[2]=='models' and parts[3]=='block' and name.endswith('.json')) or
            (parts[2]=='blockstates' and name.endswith('.json')))
    assets={};total=0
    def add(name,size,read):
        nonlocal total
        if not wanted(name):return
        if size>16*1024*1024 or total+size>256*1024*1024:raise ValueError('Texture pack exceeds asset safety limits')
        assets[name]=read();total+=size
    source=Path(source)
    if source.is_dir():
        for path in sorted((source/'assets').rglob('*')):
            if path.is_file() and not path.is_symlink():
                add(path.relative_to(source).as_posix(),path.stat().st_size,path.read_bytes)
    else:
        with zipfile.ZipFile(source) as archive:
            for item in sorted(archive.infolist(),key=lambda i:i.filename):
                add(item.filename,item.file_size,lambda i=item:archive.read(i))
    if not any(n.endswith('.png') for n in assets):raise ValueError('Selected source has no Java block textures')
    return assets


class TextureAtlas:
    """Cube-face approximation; model parents/texture variables resolved, shapes deferred."""
    def __init__(self,assets):
        self.assets=assets;self.rects={};self.alpha={};self.models={};self.faces={};self.shapes={}
        self.fingerprint=hashlib.sha256(b''.join(n.encode()+hashlib.sha256(v).digest() for n,v in sorted(assets.items()))).hexdigest()
        pictures=[]
        for name,data in sorted(assets.items()):
            if not name.endswith('.png'):continue
            with Image.open(io.BytesIO(data)) as opened:
                if opened.width>1024 or opened.height>32768:raise ValueError('Texture dimensions exceed safety limits')
                # Interim animation support: preserve original bytes, display first square frame.
                picture=opened.convert('RGBA');size=min(picture.size)
                self.alpha[name]=picture.getchannel('A').getextrema()[0]<255
                pictures.append((name,picture.crop((0,0,size,size)).resize((32,32),Image.Resampling.NEAREST)))
        if len(pictures)>12000:raise ValueError('Too many block textures')
        cell=34;side=math.ceil(math.sqrt(len(pictures)+1));width=side*cell
        atlas=Image.new('RGBA',(width,width),(255,255,255,255))
        self.white=((.5/width,1-.5/width),(.5/width,1-.5/width))
        for index,(name,picture) in enumerate(pictures,1):
            x=index%side*cell+1;y=index//side*cell+1
            atlas.paste(picture,(x,y))
            # Duplicate borders to avoid atlas bleeding.
            atlas.paste(picture.crop((0,0,1,32)),(x-1,y));atlas.paste(picture.crop((31,0,32,32)),(x+32,y))
            atlas.paste(picture.crop((0,0,32,1)),(x,y-1));atlas.paste(picture.crop((0,31,32,32)),(x,y+32))
            self.rects[name]=((x/width,1-(y+32)/width),((x+32)/width,1-y/width))
        stream=io.BytesIO();atlas.save(stream,format='PNG');self.png=stream.getvalue()

    def model(self,name,seen=()):
        if name in seen or len(seen)>32:return {}
        if name in self.models:return self.models[name]
        namespace,ident=name.split(':',1) if ':' in name else ('minecraft',name)
        raw=json.loads(self.assets.get(f'assets/{namespace}/models/{ident}.json',b'{}'))
        parent=self.model(raw['parent'],seen+(name,)) if 'parent' in raw else {}
        result={**parent,**raw,'textures':{**parent.get('textures',{}),**raw.get('textures',{})},
                '_parents':parent.get('_parents',())+((raw.get('parent'),) if raw.get('parent') else ())}
        self.models[name]=result
        return result

    def block_model(self,block,properties=None):
        # 1.13 renamed the plant while old saves still decode legacy ID 31 as grass.
        if block=='minecraft:grass' and 'assets/minecraft/blockstates/grass.json' not in self.assets:
            block='minecraft:short_grass'
        namespace,ident=block.split(':',1) if ':' in block else ('minecraft',block)
        state=json.loads(self.assets.get(f'assets/{namespace}/blockstates/{ident}.json',b'{}'))
        variants=state.get('variants',{});properties=properties or {}
        def matches(key):
            return all(properties.get(k)==v for k,v in (part.split('=',1) for part in key.split(',') if '=' in part))
        choice=next((value for key,value in variants.items() if key and matches(key)),variants.get('',next(iter(variants.values()),{})))
        if isinstance(choice,list):choice=choice[0] if choice else {}
        if not choice and state.get('multipart'):
            apply=state['multipart'][0].get('apply',{})
            choice=apply[0] if isinstance(apply,list) and apply else apply
        return self.model(choice.get('model',f'{namespace}:block/{ident}'))

    def resolve_texture(self,block,direction,properties=None):
        if block=='minecraft:grass' and 'assets/minecraft/blockstates/grass.json' not in self.assets:block='minecraft:short_grass'
        namespace,ident=block.split(':',1) if ':' in block else ('minecraft',block)
        model=self.block_model(block,properties)
        refs=model.get('textures',{});ref=None
        for element in model.get('elements',[]):
            face=element.get('faces',{}).get(direction)
            if face:ref=face.get('texture');break
        if ref is None:
            candidates=(direction,'top' if direction=='up' else 'bottom' if direction=='down' else 'side','end' if direction in ('up','down') else 'side','cross','plant','all','texture')
            ref=next((refs[n] for n in candidates if n in refs),f'{namespace}:block/{ident}')
        visited=set()
        while ref.startswith('#') and ref not in visited:
            visited.add(ref);ref=refs.get(ref[1:],'')
        ns,texture=ref.split(':',1) if ':' in ref else ('minecraft',ref)
        paths=[f'assets/{ns}/textures/{texture}.png',f'assets/{ns}/textures/{texture.replace("block/","blocks/")}.png']
        if ident in ('water','lava'):paths.insert(0,f'assets/{namespace}/textures/block/{ident}_still.png')
        return next((p for p in paths if p in self.rects),None)

    def render_shape(self,block,properties=None):
        key=(block,tuple(sorted((properties or {}).items())))
        if key in self.shapes:return self.shapes[key]
        ident=block.split(':')[-1];model=self.block_model(block,properties)
        parents=' '.join(p or '' for p in model.get('_parents',()))
        if 'rail' in ident:shape='rail'
        elif ident in ('torch','wall_torch','redstone_torch','redstone_wall_torch','soul_torch','soul_wall_torch'):shape='torch'
        elif 'cross' in parents or 'flower' in parents:shape='cross'
        else:
            paths=[self.resolve_texture(block,direction,properties) for direction in FACE_NAMES]
            shape='cutout_cube' if any(path and self.alpha.get(path,False) for path in paths) else 'cube'
        self.shapes[key]=shape
        return shape

    def face(self,block,direction,properties=None):
        key=(block,direction,tuple(sorted((properties or {}).items())))
        if key in self.faces:return self.faces[key]
        namespace,ident=block.split(':',1) if ':' in block else ('minecraft',block)
        path=self.resolve_texture(block,direction,properties)
        rect=self.rects[path] if path else self.white
        (u0,v0),(u1,v1)=rect
        uv=np.array([(u0,v0),(u1,v1),(u1,v0),(u0,v0),(u0,v1),(u1,v1)],dtype=np.float32)
        if direction not in ('up','down'):
            # Side-face corners are bottom/top/top/bottom: V must follow Y.
            uv=np.array([(u0,v0),(u1,v1),(u0,v1),(u0,v0),(u1,v0),(u1,v1)],dtype=np.float32)
        model=self.block_model(block,properties)
        model_tinted=any(face.get('tintindex') is not None for element in model.get('elements',[])
                         for face in element.get('faces',{}).values())
        # Model tintindex is authoritative; names cover older/simple resource packs.
        tinted=model_tinted or ('leaves' in ident or ident in ('water','grass','short_grass','fern','vine','sugar_cane') or ident=='grass_block' and direction=='up')
        result=(uv,path is not None,tinted)
        self.faces[key]=result
        return result

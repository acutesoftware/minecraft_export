"""Read-only voxel decoding and chunk meshes; no graphics-engine dependency."""
import hashlib
import json
import logging
from collections import defaultdict, OrderedDict
from pathlib import Path
from time import perf_counter

import numpy as np

from .java_reader import JavaWorldReader, LEGACY_BLOCKS, unpack_values, surface_arrays
from .map_renderer import block_color

VERSION = 'mesh-8'
ARRAYS=('vertices','normals','colors','uvs')
AIR = ('minecraft:air','minecraft:cave_air','minecraft:void_air')
LEGACY_MATERIALS = {**LEGACY_BLOCKS, 6:'minecraft:oak_sapling', 32:'minecraft:dead_bush',
    37:'minecraft:dandelion',38:'minecraft:poppy',50:'minecraft:torch',54:'minecraft:chest',
    58:'minecraft:crafting_table',60:'minecraft:farmland',61:'minecraft:furnace',62:'minecraft:furnace',
    75:'minecraft:redstone_torch',76:'minecraft:redstone_torch',85:'minecraft:oak_fence',95:'minecraft:glass',102:'minecraft:glass_pane',
    125:'minecraft:oak_slab',126:'minecraft:oak_slab',134:'minecraft:spruce_stairs',
    135:'minecraft:birch_stairs',136:'minecraft:jungle_stairs',160:'minecraft:glass_pane',
    161:'minecraft:acacia_leaves',162:'minecraft:acacia_log',163:'minecraft:acacia_stairs',
    164:'minecraft:dark_oak_stairs',175:'minecraft:tall_grass'}


def minecraft_to_renderer(x,y,z):
    # Minecraft +Z is south; reflect it for Ursina's opposite handedness.
    return (x,y,-z)


def renderer_to_minecraft(x,y,z):return (x,y,-z)


def mesh_to_renderer(data):
    """Reflect local Z and restore clockwise winding after reflection."""
    result={key:np.asarray(data[key]).copy() for key in ARRAYS}
    result['vertices'][:,2]*=-1;result['normals'][:,2]*=-1
    for key in ARRAYS:
        values=result[key].reshape(-1,3,result[key].shape[1])
        values[:,[1,2]]=values[:,[2,1]]
    return result


def decode_volume(chunk):
    level=chunk.get('Level',chunk)
    sections=level.get('sections',level.get('Sections',[]))
    sections=[s for s in sections if any(k in s for k in ('block_states','Palette','Blocks'))]
    low=min((int(s['Y']) for s in sections),default=0)*16
    high=max((int(s['Y']) for s in sections),default=0)*16+16
    volume=np.full((high-low,16,16),'minecraft:air',dtype=object)
    for s in sections:
        state=s.get('block_states',{})
        palette=state.get('palette',s.get('Palette',[]))
        if palette:
            names=np.array([str(p.get('Name','minecraft:air')) for p in palette],dtype=object)
            indices=unpack_values(state.get('data',s.get('BlockStates',[])),np.arange(4096),max(4,(len(names)-1).bit_length()),int(chunk.get('DataVersion',0))>=2529)
            blocks=names[indices]
        else:
            ids=np.asarray(s.get('Blocks',np.zeros(4096)),dtype=np.int64)&255
            blocks=np.array([LEGACY_MATERIALS.get(int(i),'minecraft:unknown') for i in ids],dtype=object)
        y=int(s['Y'])*16-low
        volume[y:y+16]=blocks.reshape(16,16,16)
    return low,volume


def material(name,colors):
    if 'water' in name: return (0.16,0.42,0.85,.65)
    if 'glass' in name: return (.65,.85,.95,.4)
    if 'brick' in name: return (.58,.26,.19,1)
    if any(s in name for s in ('planks','stairs','fence','door')) and any(s in name for s in ('oak','birch','spruce','wood')):
        return (.52,.36,.19,1)
    return tuple(c/255 for c in block_color(name,colors))+(1,)


# Counter-clockwise outward faces, Y-up. Vertex data stays local to the chunk.
FACES=[((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]),
       ((-1,0,0),[(0,0,1),(0,1,1),(0,1,0),(0,0,0)]),
       ((0,1,0),[(0,1,1),(1,1,1),(1,1,0),(0,1,0)]),
       ((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
       ((0,0,1),[(1,0,1),(1,1,1),(0,1,1),(0,0,1)]),
       ((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]

CROSS_WORDS=('grass','fern','flower','sapling','mushroom','bush','tulip','orchid','dandelion','poppy',
             'allium','azure_bluet','lily_of_the_valley','cornflower','wheat','carrots','potatoes','beetroots','sugar_cane')


def render_shape(name):
    """Approximate common non-solid Minecraft models without hiding geometry behind them."""
    ident=name.split(':')[-1]
    if 'rail' in ident:return 'rail'
    if ident in ('torch','wall_torch','redstone_torch','redstone_wall_torch','soul_torch','soul_wall_torch'):return 'torch'
    if any(word in ident for word in CROSS_WORDS) and not ident.endswith(('grass_block','moss_block')):return 'cross'
    return 'cube'


def legacy_properties(block_id,data):
    if block_id in (50,75,76):
        return {'facing':{1:'east',2:'west',3:'south',4:'north',5:'up'}.get(data,'up')}
    if block_id==66:
        return {'shape':('north_south','east_west','ascending_east','ascending_west','ascending_north',
                         'ascending_south','south_east','south_west','north_west','north_east')[min(data,9)]}
    return {}


def _special_geometry(blocks,band,low,palette,atlas,block_names,block_properties,block_shapes,numeric):
    vertices=[];normals=[];rgba=[];uvs=[]
    unique=np.unique(blocks[band])
    for block_id in unique:
        name=block_names[int(block_id)] if numeric else str(block_id)
        shape=block_shapes[int(block_id)] if numeric and block_shapes else render_shape(name)
        if shape in ('cube','cutout_cube'):continue
        mask=(blocks==block_id)&band
        yy,zz,xx=np.nonzero(mask)
        if not len(xx):continue
        base=np.column_stack((xx,yy+low,zz)).astype(np.float32)
        if shape=='rail':
            quads=np.array([[(0,.0625,0),(1,.0625,1),(1,.0625,0),(0,.0625,0),(0,.0625,1),(1,.0625,1)]],dtype=np.float32)
            direction='up';normal=(0,1,0)
        elif shape=='cross':
            # Two crossed sheets. Duplicate reversed triangles so cutouts are visible from both sides.
            quads=np.array([[ (0,0,0),(1,1,1),(1,0,1),(0,0,0),(0,1,0),(1,1,1),
                              (0,0,0),(1,0,1),(1,1,1),(0,0,0),(1,1,1),(0,1,0)],
                            [ (1,0,0),(0,1,1),(0,0,1),(1,0,0),(1,1,0),(0,1,1),
                              (1,0,0),(0,0,1),(0,1,1),(1,0,0),(0,1,1),(1,1,0)]],dtype=np.float32)
            direction='north';normal=(0,0,1)
        else:
            properties=block_properties[int(block_id)] if numeric and block_properties else {}
            facing=properties.get('facing','up')
            if facing in ('north','south'):
                z0,z1=(.02,.42) if facing=='north' else (.98,.58)
                quads=np.array([[(.38,.2,z0),(.62,.8,z1),(.38,.8,z1),(.38,.2,z0),(.62,.2,z0),(.62,.8,z1),
                                 (.38,.2,z0),(.38,.8,z1),(.62,.8,z1),(.38,.2,z0),(.62,.8,z1),(.62,.2,z0)]],dtype=np.float32)
                direction=facing;normal=(0,0,1)
            elif facing in ('east','west'):
                x0,x1=(.98,.58) if facing=='east' else (.02,.42)
                quads=np.array([[(x0,.2,.38),(x1,.8,.62),(x1,.8,.38),(x0,.2,.38),(x0,.2,.62),(x1,.8,.62),
                                 (x0,.2,.38),(x1,.8,.38),(x1,.8,.62),(x0,.2,.38),(x1,.8,.62),(x0,.2,.62)]],dtype=np.float32)
                direction=facing;normal=(1,0,0)
            else:
                quads=np.array([[ (.4,0,.5),(.6,.65,.5),(.4,.65,.5),(.4,0,.5),(.6,0,.5),(.6,.65,.5),
                                  (.5,0,.4),(.5,.65,.6),(.5,.65,.4),(.5,0,.4),(.5,0,.6),(.5,.65,.6)]],dtype=np.float32)
                direction='north';normal=(0,0,1)
        geometry=(base[:,None,None,:]+quads[None,:,:,:]).reshape(-1,3)
        vertices.append(geometry)
        normals.append(np.tile(normal,(len(geometry),1)))
        colour=np.asarray(palette[int(block_id)] if numeric else palette[name],dtype=np.float32)
        properties=block_properties[int(block_id)] if numeric and block_properties else {}
        uv,found,tinted=atlas.face(name,direction,properties) if atlas else (np.tile([0,1],(6,1)),False,False)
        if found and not tinted:colour[:3]=1
        if shape in ('cross','torch'):
            u0,u1=float(uv[:,0].min()),float(uv[:,0].max());v0,v1=float(uv[:,1].min()),float(uv[:,1].max())
            front=np.array([(u0,v0),(u1,v1),(u1,v0),(u0,v0),(u0,v1),(u1,v1)],dtype=np.float32)
            back=np.array([(u0,v0),(u1,v0),(u1,v1),(u0,v0),(u1,v1),(u0,v1)],dtype=np.float32)
            sheet=np.concatenate((front,back))
            special_uv=np.tile(sheet,(len(geometry)//len(sheet),1))
        else:special_uv=np.tile(uv,(len(geometry)//len(uv),1))
        uvs.append(special_uv);rgba.append(np.tile(colour,(len(geometry),1)))
    return vertices,normals,rgba,uvs


def mesh_volume(padded, low, heights, colors, depth=16, materials=None, atlas=None, block_names=None, block_properties=None, block_shapes=None):
    """Cull using real neighbours, including chunk edges and underground cutoff."""
    blocks=padded[1:-1,1:-1,1:-1]
    numeric=materials is not None
    occupied=blocks!=0 if numeric else ~np.isin(blocks,AIR)
    band=(np.arange(blocks.shape[0])+low)[:,None,None]>=heights[None,:,:]-depth
    vertices=[]; normals=[]; rgba=[];uvs=[]
    if numeric:
        palette=np.asarray(materials,dtype=np.float32)
        transparent=palette[blocks,3]<1
        shapes=np.asarray(block_shapes,dtype=object) if block_shapes else np.array([render_shape(name) for name in block_names],dtype=object) if block_names else np.full(len(materials),'cube',dtype=object)
        cube=np.isin(shapes[blocks],('cube','cutout_cube'))
        neighbor_occludes=shapes[padded]=='cube'
    else:
        palette={str(n):material(str(n),colors) for n in np.unique(blocks)}
        translucent_ids=[n for n in np.unique(padded) if 'water' in str(n) or 'glass' in str(n)]
        transparent=np.isin(blocks,translucent_ids)
        cube=np.vectorize(lambda name:render_shape(str(name))=='cube')(blocks)
        neighbor_occludes=np.vectorize(lambda name:render_shape(str(name))=='cube')(padded)
    for face_index,((dx,dy,dz),corners) in enumerate(FACES):
        neighbor=padded[1+dy:1+dy+blocks.shape[0],1+dz:17+dz,1+dx:17+dx]
        air=neighbor==0 if numeric else np.isin(neighbor,AIR)
        translucent=palette[neighbor,3]<1 if numeric else np.isin(neighbor,translucent_ids)
        occludes=neighbor_occludes[1+dy:1+dy+blocks.shape[0],1+dz:17+dz,1+dx:17+dx]
        exposed=occupied & cube & band & (air | ~occludes | (translucent & ~transparent))
        yy,zz,xx=np.nonzero(exposed)
        if not len(xx):continue
        origins=np.column_stack((xx,yy+low,zz))
        quad=origins[:,None,:]+np.asarray(corners)[None,:,:]
        # Ursina's Y-up left-handed scene expects clockwise face winding.
        vertices.append(quad[:,[0,2,1,0,3,2],:].reshape(-1,3))
        normals.append(np.tile((dx,dy,dz),(len(xx)*6,1)))
        face_colors=palette[blocks[yy,zz,xx]] if numeric else np.array([palette[str(n)] for n in blocks[yy,zz,xx]])
        face_uv=np.tile(np.array([0,1],dtype=np.float32),(len(xx),6,1))
        if atlas is not None:
            from .textures3d import FACE_NAMES
            ids=blocks[yy,zz,xx]
            for block_id in np.unique(ids):
                properties=block_properties[int(block_id)] if block_properties else {}
                uv,found,tinted=atlas.face(block_names[int(block_id)],FACE_NAMES[face_index],properties)
                mask=ids==block_id;face_uv[mask]=uv
                if found and not tinted:face_colors[mask,:3]=1
        uvs.append(face_uv.reshape(-1,2))
        rgba.append(np.repeat(face_colors,6,axis=0))
    special=_special_geometry(blocks,band,low,palette,atlas,block_names,block_properties,block_shapes,numeric) if (not numeric or block_names) else ([],[],[],[])
    for target,values in zip((vertices,normals,rgba,uvs),special):target.extend(values)
    if not vertices:return empty_mesh()
    return {'vertices':np.concatenate(vertices).astype('float32'),'normals':np.concatenate(normals).astype('float32'),'colors':np.concatenate(rgba).astype('float32'),'uvs':np.concatenate(uvs)}


def empty_mesh():
    return {'vertices':np.empty((0,3),dtype='float32'),'normals':np.empty((0,3),dtype='float32'),'colors':np.empty((0,4),dtype='float32'),'uvs':np.empty((0,2),dtype='float32')}


def terrain_jobs(known,cx,cz,near,far):
    """Individual detailed chunks and 8x8 distant groups, nearest first."""
    groups=defaultdict(list)
    for x,z in known:
        if abs(x-cx)*16>far or abs(z-cz)*16>far:continue
        detail=abs(x-cx)*16<=near and abs(z-cz)*16<=near
        key=('near',x,z) if detail else ('far',x//8*8,z//8*8)
        groups[key].append((x,z))
    return sorted(((key,tuple(sorted(coords))) for key,coords in groups.items()),
                  key=lambda job:(job[0][0]!='near',(job[0][1]-cx)**2+(job[0][2]-cz)**2))


def distant_mesh(names,heights,visible,colors):
    vertices=[]; rgba=[]
    # Four-block cells: inexpensive surface shell; no fictitious unexplored cells.
    for z in range(0,16,4):
        for x in range(0,16,4):
            if not visible[z:z+4,x:x+4].all():continue
            points=[(x,float(heights[z,x])+1,z),(x,float(heights[min(z+4,15),x])+1,z+4),
                    (x+4,float(heights[min(z+4,15),min(x+4,15)])+1,z+4),(x+4,float(heights[z,min(x+4,15)])+1,z)]
            vertices.extend(points[i] for i in (0,2,1,0,3,2))
            rgba.extend([material(str(names[z,x]),colors)]*6)
    if not vertices:return empty_mesh()
    v=np.array(vertices,dtype='float32'); tris=v.reshape(-1,3,3)
    normals=-np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-6)
    return {'vertices':v,'normals':np.repeat(normals,3,axis=0),'colors':np.asarray(rgba,dtype='float32'),'uvs':np.tile(np.array([0,1],dtype=np.float32),(len(v),1))}


class MeshWorld:
    def __init__(self, source, output, world_uuid, atlas=None):
        self.source=Path(source)
        self.atlas=atlas
        self.cache=Path(output)/world_uuid/'3d'/VERSION/(atlas.fingerprint if atlas else 'flat')
        self.colors=json.loads(Path(__file__).with_name('data').joinpath('block_colors.json').read_text())
        self.chunks=OrderedDict()
        self.sections=OrderedDict()
        self.block_ids={(name,()):0 for name in AIR}
        self.materials=[(0,0,0,0)]
        self.block_names=['minecraft:air']
        self.block_properties=[{}]
        self.block_shapes=['cube']
        self.region_stamps={}
        self.signatures={}

    def begin_reload(self):
        self.chunks.clear();self.sections.clear();self.region_stamps.clear();self.signatures.clear()

    def block_id(self,name,properties=None):
        properties={str(k):str(v) for k,v in (properties or {}).items()}
        key=(name,tuple(sorted(properties.items())))
        if key not in self.block_ids:
            self.block_ids[key]=len(self.materials)
            self.materials.append(material(name,self.colors))
            self.block_names.append(name)
            self.block_properties.append(properties)
            self.block_shapes.append(self.atlas.render_shape(name,properties) if self.atlas else render_shape(name))
        return self.block_ids[key]

    def section(self,x,z,sy):
        key=(x,z,sy)
        if key not in self.sections:
            chunk=self.chunk(x,z)
            level=chunk.get('Level',chunk) if chunk else {}
            section=next((s for s in level.get('sections',level.get('Sections',[])) if int(s['Y'])==sy),{})
            state=section.get('block_states',{})
            palette=state.get('palette',section.get('Palette',[]))
            if palette:
                ids=np.array([self.block_id(str(p.get('Name','minecraft:air')),p.get('Properties')) for p in palette],dtype=np.uint32)
                indices=unpack_values(state.get('data',section.get('BlockStates',[])),np.arange(4096),max(4,(len(ids)-1).bit_length()),int(chunk.get('DataVersion',0))>=2529)
                result=ids[indices].reshape(16,16,16)
            elif len(section.get('Blocks',[]))==4096:
                legacy_ids=np.asarray(section['Blocks'],dtype=np.int64)&255
                packed_data=np.asarray(section.get('Data',np.zeros(2048)),dtype=np.uint8)&255
                metadata=np.zeros(4096,dtype=np.uint8)
                metadata[0::2]=packed_data&15;metadata[1::2]=packed_data>>4
                pairs=legacy_ids*16+metadata
                lookup={int(pair):self.block_id(LEGACY_MATERIALS.get(int(pair)//16,'minecraft:unknown'),
                                                 legacy_properties(int(pair)//16,int(pair)%16))
                        for pair in np.unique(pairs)}
                result=np.array([lookup[int(pair)] for pair in pairs],dtype=np.uint32).reshape(16,16,16)
            else:result=np.zeros((16,16,16),dtype=np.uint32)
            self.sections[key]=result
        self.sections.move_to_end(key)
        while len(self.sections)>512:self.sections.popitem(last=False)
        return self.sections[key]

    def band(self,x,z,bottom,top,edge=None):
        # Only sections intersecting the visible band are decoded. Neighbour
        # requests copy a single 16-block-wide edge, never a full volume.
        shape=(top-bottom,16,16) if edge is None else (top-bottom,16)
        result=np.zeros(shape,dtype=np.uint32)
        for sy in range(bottom//16,(top-1)//16+1):
            section=self.section(x,z,sy)
            lo,hi=max(bottom,sy*16),min(top,sy*16+16)
            values=section[lo-sy*16:hi-sy*16]
            if edge is not None:
                axis,index=edge
                values=values[:,:,index] if axis=='x' else values[:,index,:]
            result[lo-bottom:hi-bottom]=values
        return result

    def region(self,x,z):return self.source/'region'/f'r.{x//32}.{z//32}.mca'

    def chunk(self,x,z):
        key=(x,z)
        if key not in self.chunks:
            path=self.region(x,z)
            data=None
            if path.exists():
                index=x%32+z%32*32
                with path.open('rb') as stream:
                    stream.seek(index*4);entry=int.from_bytes(stream.read(4),'big')
                if entry:data=JavaWorldReader._read_chunk(path,index)
            self.chunks[key]=data
        self.chunks.move_to_end(key)
        while len(self.chunks)>128:self.chunks.popitem(last=False)
        return self.chunks[key]

    def signature(self,x,z,detail):
        paths={self.region(x+dx,z+dz) for dx,dz in ((0,0),(-1,0),(1,0),(0,-1),(0,1))}
        records=[]
        for path in sorted(paths):
            if path not in self.region_stamps:
                stat=path.stat() if path.exists() else None
                self.region_stamps[path]=(str(path),stat.st_mtime_ns if stat else None,stat.st_size if stat else None)
            records.append(self.region_stamps[path])
        key=(detail,tuple(records))
        if key not in self.signatures:
            self.signatures[key]=hashlib.sha256(json.dumps([VERSION,detail,records,self.colors,self.atlas.fingerprint if self.atlas else None]).encode()).hexdigest()
        return self.signatures[key]

    def job_signature(self,key,coords):
        detail=key[0]=='near'
        signatures=sorted({self.signature(x,z,detail) for x,z in coords})
        return hashlib.sha256(json.dumps([key,coords,signatures]).encode()).hexdigest()

    def job_mesh(self,key,coords,signature):
        if key[0]=='near':return self.mesh(key[1],key[2],True)
        path=self.cache/'batches'/f'{signature}.npz'
        if path.exists():
            try:
                with np.load(path,allow_pickle=False) as data:
                    return {k:data[k] for k in ARRAYS}
            except (OSError,ValueError):logging.exception('Invalid batch cache %s',path)
        parts=[];failed=0
        for x,z in coords:
            try:data=self.mesh(x,z,False,persist=False)
            except Exception:
                logging.exception('Skipping unreadable distant chunk %s,%s',x,z)
                failed+=1
                continue
            data['vertices']=data['vertices']+np.array([(x-key[1])*16,0,(z-key[2])*16],dtype=np.float32)
            parts.append(data)
        result={k:np.concatenate([part[k] for part in parts]) for k in ARRAYS} if parts else empty_mesh()
        if failed:
            # Never persist incomplete batches or mark them reusable on reload.
            result['failed_chunks']=failed
            return result
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp')
        with temp.open('wb') as stream:np.savez_compressed(stream,**result)
        temp.replace(path)
        return result

    def mesh(self,x,z,detail,persist=True):
        start=perf_counter();mode='near' if detail else 'far'
        path=self.cache/'minecraft_overworld'/f'c.{x}.{z}.{mode}.npz'
        signature=self.signature(x,z,detail)
        if path.exists():
            try:
                with np.load(path,allow_pickle=False) as data:
                    if str(data['signature'])==signature or not self.source.exists():
                        logging.info('3D chunk %s,%s %s cache hit %.3fs',x,z,mode,perf_counter()-start)
                        return {k:data[k] for k in ARRAYS}
            except (OSError,ValueError):logging.exception('Invalid mesh cache %s',path)
        chunk=self.chunk(x,z)
        if chunk is None:return empty_mesh()
        read_time=perf_counter()-start
        surface_start=perf_counter()
        names,heights,_,visible=surface_arrays(chunk,defaultdict(float))
        surface_time=perf_counter()-surface_start
        mesh_start=perf_counter()
        if detail:
            if not visible.any():return empty_mesh()
            low=int(heights[visible].min())-16
            top=int(heights[visible].max())+1
            padded=np.zeros((top-low+2,18,18),dtype=np.uint32)
            padded[:,1:-1,1:-1]=self.band(x,z,low-1,top+1)
            for dx,dz in ((-1,0),(1,0),(0,-1),(0,1)):
                if dx:padded[:,1:-1,0 if dx<0 else 17]=self.band(x+dx,z,low-1,top+1,('x',15 if dx<0 else 0))
                else:padded[:,0 if dz<0 else 17,1:-1]=self.band(x,z+dz,low-1,top+1,('z',15 if dz<0 else 0))
            result=mesh_volume(padded,low,heights,self.colors,materials=self.materials,atlas=self.atlas,block_names=self.block_names,block_properties=self.block_properties,block_shapes=self.block_shapes)
        else:result=distant_mesh(names,heights,visible,self.colors)
        mesh_time=perf_counter()-mesh_start
        if persist:
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp')
            with temp.open('wb') as stream:np.savez_compressed(stream,signature=signature,**result)
            temp.replace(path)
        logging.info('3D chunk %s,%s %s cache miss vertices=%s triangles=%s read=%.3fs surface=%.3fs mesh=%.3fs total=%.3fs',x,z,mode,len(result['vertices']),len(result['vertices'])//3,read_time,surface_time,mesh_time,perf_counter()-start)
        return result

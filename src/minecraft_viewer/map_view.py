"""Continuous world-coordinate map with one bounded background tile worker."""
import math
import re
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from collections import OrderedDict
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor
from tkinter import ttk, messagebox, filedialog

from PIL import Image, ImageTk, ImageDraw
from PIL.PngImagePlugin import PngInfo

from .tile_cache import TileCache, render_tile, configure_render_logging


def export_filename(world_name, layer, x, z):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', world_name).strip(' .')[:100] or 'World'
    return f"{name}_{layer}_X{math.floor(x)}_Z{math.floor(z)}.png"


@dataclass
class Camera:
    x: float = 0
    z: float = 0
    zoom: float = 1

    def world(self, sx, sy, width, height):
        return self.x+(sx-width/2)/self.zoom, self.z+(sy-height/2)/self.zoom

    def screen(self, x, z, width, height):
        return (x-self.x)*self.zoom+width/2, (z-self.z)*self.zoom+height/2

    def zoom_at(self, factor, sx, sy, width, height):
        x, z = self.world(sx,sy,width,height)
        self.zoom = max(1/64,min(8,self.zoom*factor))
        self.x = x-(sx-width/2)/self.zoom
        self.z = z-(sy-height/2)/self.zoom

    def regions(self, width, height):
        left, top = self.world(0,0,width,height)
        right, bottom = self.world(width,height,width,height)
        return [(x,z) for z in range(math.floor(top/512),math.ceil(bottom/512))
                for x in range(math.floor(left/512),math.ceil(right/512))]


class MapView(ttk.Frame):
    def __init__(self, parent, db, output, on_status=None, render_workers=4, log_path=None):
        super().__init__(parent)
        self.db, self.output = db, output
        self.render_workers = max(1,min(4,int(render_workers)))
        self.log_path = str(log_path) if log_path else None
        self.on_status = on_status or (lambda text, done, total: None)
        self.visible_keys = set()
        self.active_job = None
        self.last_status = None
        self.camera = Camera()
        self.spawn = (0,0)
        self.world_id = None
        self.world_name = "World"
        self.cache = None
        self.known_regions = None
        self.empty_image = Image.new("RGB",(512,512),(30,30,34))
        self.empty_image.info['empty_region'] = True
        self.epoch = 0
        self.images = OrderedDict()
        self.photos = {}
        self.pending = set()
        self.failed = set()
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.closed = threading.Event()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        toolbar = ttk.Frame(self); toolbar.pack(fill="x")
        self.layer = ttk.Combobox(toolbar, values=("surface","biome","height","activity"), state="readonly", width=12)
        self.layer.set("surface"); self.layer.pack(side="left")
        self.layer.bind("<<ComboboxSelected>>", lambda _: self.redraw())
        self.dimension = ttk.Combobox(toolbar, state="readonly", width=26)
        self.dimension.pack(side="left", padx=4)
        self.dimension.bind("<<ComboboxSelected>>", lambda _: self._set_dimension())
        ttk.Button(toolbar,text="−",command=lambda:self.zoom(.5)).pack(side="left")
        ttk.Button(toolbar,text="+",command=lambda:self.zoom(2)).pack(side="left")
        ttk.Button(toolbar,text="Go To Spawn",command=self.go_spawn).pack(side="left")
        navigation = ttk.Frame(self); navigation.pack(fill="x")
        self.grid_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(navigation,text="Chunk / region grid",variable=self.grid_enabled,command=self.redraw).pack(side="left")
        self.entries = []
        for name in ("X", "Z"):
            ttk.Label(navigation,text=name).pack(side="left")
            entry = ttk.Entry(navigation,width=10); entry.pack(side="left"); self.entries.append(entry)
            entry.bind("<Return>",lambda _:self.go_coordinate())
        ttk.Button(navigation,text="Go",command=self.go_coordinate).pack(side="left")
        ttk.Button(navigation,text="Fit saved world",command=self.fit_world).pack(side="left",padx=4)
        self.builds_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(navigation,text="Builds (likely)",variable=self.builds_enabled,command=self.redraw).pack(side="left")
        self.export_button = ttk.Button(navigation,text="Export PNG...",command=self.export_png, state="disabled")
        self.export_button.pack(side="left", padx=8)
        self.info = ttk.Label(self,text="Select a world. Drag to pan; wheel to zoom; arrows/WASD to move.")
        self.info.pack(side="bottom",fill="x")
        self.loading_info = ttk.Label(self, text="Dark grey = no rendered terrain. Tiles load automatically.")
        self.loading_info.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(self,bg="#1e1e22",highlightthickness=0,takefocus=True)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _:self.redraw())
        for button in (1,2):
            self.canvas.bind(f"<ButtonPress-{button}>",self._drag_start)
            self.canvas.bind(f"<B{button}-Motion>",self._drag)
        self.canvas.bind("<Motion>",self._coordinates)
        self.canvas.bind("<MouseWheel>",lambda e:self.zoom(2 if e.delta>0 else .5,e.x,e.y))
        self.canvas.bind("<Button-4>",lambda e:self.zoom(2,e.x,e.y))
        self.canvas.bind("<Button-5>",lambda e:self.zoom(.5,e.x,e.y))
        self.canvas.bind("<KeyPress>",self._key)
        self.bind("<Destroy>",self._destroy)
        self.after(80,self._poll)

    def set_world(self, world_id):
        world = self.db.row("SELECT * FROM mc_world WHERE world_id=?",(world_id,))
        if world is None:
            return
        changed = world_id != self.world_id
        self.world_id = world_id
        self.world_name = world["world_name"] or "World"
        self.spawn = (world["spawn_x"] or 0,world["spawn_z"] or 0)
        self.dimensions = self.db.rows("SELECT * FROM mc_dimension WHERE world_id=? AND import_id=(SELECT MAX(import_id) FROM mc_import WHERE world_id=? AND status IN ('COMPLETE','PARTIAL'))",(world_id,world_id))
        keys = [d["dimension_key"] for d in self.dimensions]
        self.dimension["values"] = keys
        if changed or self.dimension.get() not in keys:
            self.dimension.set("minecraft:overworld" if "minecraft:overworld" in keys else (keys[0] if keys else ""))
        if changed:
            self.camera = Camera(*self.spawn)
        self._set_dimension()

    def _set_dimension(self):
        self.epoch += 1
        self.images.clear(); self.failed.clear()
        self.cache = None
        for d in self.dimensions:
            if d["dimension_key"] == self.dimension.get():
                self.cache = TileCache(self.db,self.output,self.world_id,d["import_id"],d["dimension_key"],d["source_path"])
        self.known_regions = self.cache.known_regions() if self.cache else None
        self.redraw()

    def effective_layer(self):
        return 'builds' if self.builds_enabled.get() else self.layer.get()

    def fit_world(self):
        if not self.cache: return
        row = self.db.row('SELECT MIN(chunk_x),MAX(chunk_x),MIN(chunk_z),MAX(chunk_z) FROM mc_chunk WHERE import_id=? AND dimension_key=?',
                          (self.cache.import_id,self.cache.dimension))
        if row is None or row[0] is None: return
        x0,x1,z0,z1 = row[0]*16,(row[1]+1)*16,row[2]*16,(row[3]+1)*16
        self.camera.x,self.camera.z = (x0+x1)/2,(z0+z1)/2
        scale = min(self.canvas.winfo_width()/max(1,x1-x0),self.canvas.winfo_height()/max(1,z1-z0))*.9
        self.camera.zoom = max(1/64,min(8,2**math.floor(math.log2(scale))))
        self.redraw()

    def go_spawn(self):
        if "minecraft:overworld" in self.dimension["values"] and self.dimension.get() != "minecraft:overworld":
            self.dimension.set("minecraft:overworld"); self._set_dimension()
        self.camera.x,self.camera.z = self.spawn
        self.redraw()

    def go_coordinate(self):
        try:
            x,z = (float(e.get()) for e in self.entries)
            if not math.isfinite(x) or not math.isfinite(z):
                raise ValueError()
        except ValueError:
            messagebox.showerror("Coordinates","Enter finite numbers for X and Z.",parent=self)
            return
        self.camera.x,self.camera.z = x,z
        self.redraw(); self.canvas.focus_set()

    def zoom(self,factor,x=None,y=None):
        w,h = self.canvas.winfo_width(),self.canvas.winfo_height()
        self.camera.zoom_at(factor,w/2 if x is None else x,h/2 if y is None else y,w,h)
        self.redraw()

    def _drag_start(self,event):
        self.canvas.focus_set(); self.drag = (event.x,event.y)

    def _drag(self,event):
        self.camera.x -= (event.x-self.drag[0])/self.camera.zoom
        self.camera.z -= (event.y-self.drag[1])/self.camera.zoom
        self.drag = (event.x,event.y)
        self.redraw(); self._coordinates(event)

    def _key(self,event):
        directions = {"Left":(-1,0),"a":(-1,0),"Right":(1,0),"d":(1,0),"Up":(0,-1),"w":(0,-1),"Down":(0,1),"s":(0,1)}
        if event.keysym == "Home": self.go_spawn()
        elif event.keysym in directions:
            dx,dz = directions[event.keysym]
            self.camera.x += dx*80/self.camera.zoom; self.camera.z += dz*80/self.camera.zoom
            self.redraw()
        return "break"

    def _coordinates(self,event):
        x,z = self.camera.world(event.x,event.y,self.canvas.winfo_width(),self.canvas.winfo_height())
        x,z = math.floor(x),math.floor(z)
        self.info.configure(text=f"X {x}  Z {z} | Chunk {x//16},{z//16} | Region {x//512},{z//512} | {self.camera.zoom:.0%}")

    def redraw(self):
        if not self.winfo_exists(): return
        c = self.canvas; w,h = c.winfo_width(),c.winfo_height()
        if w<=1 or h<=1: return
        c.delete("all"); self.photos.clear()
        # Drop queued work from old viewports; an in-flight tile can finish into cache.
        while True:
            try:
                old = self.jobs.get_nowait(); self.pending.discard(old[0])
            except queue.Empty: break
        if self.cache is None:
            self.visible_keys.clear()
            c.create_text(20,20,anchor="nw",fill="white",text="Select a world with imported dimensions.")
            self._report_status()
            return
        if self.known_regions is None:
            regions = self.camera.regions(w,h)
        else:
            left,top = self.camera.world(0,0,w,h)
            right,bottom = self.camera.world(w,h,w,h)
            regions = [(rx,rz) for rx,rz in self.known_regions
                       if rx*512 < right and (rx+1)*512 > left and rz*512 < bottom and (rz+1)*512 > top]
        self.visible_keys = {(self.epoch,self.effective_layer(),rx,rz) for rx,rz in regions}
        centre = (math.floor(self.camera.x/512),math.floor(self.camera.z/512))
        regions.sort(key=lambda r:(r != centre,(r[0]*512+256-self.camera.x)**2+(r[1]*512+256-self.camera.z)**2))
        for rx,rz in regions:
            key = (self.epoch,self.effective_layer(),rx,rz)
            if self.known_regions is not None and (rx,rz) not in self.known_regions:
                self.images[key] = self.empty_image
            x,y = self.camera.screen(rx*512,rz*512,w,h)
            right,bottom = self.camera.screen((rx+1)*512,(rz+1)*512,w,h)
            x,y,right,bottom = map(round,(x,y,right,bottom))
            if key in self.images:
                image = self.images[key]; self.images.move_to_end(key)
                # Crop before upscaling so 800% never allocates off-screen 4096px tiles.
                size = round(512*self.camera.zoom)
                if self.camera.zoom <= 1:
                    shown = image.resize((size,size),Image.Resampling.NEAREST)
                else:
                    left = max(0,math.floor(-x/self.camera.zoom)); top = max(0,math.floor(-y/self.camera.zoom))
                    end_x = min(512,math.ceil((w-x)/self.camera.zoom)); end_z = min(512,math.ceil((h-y)/self.camera.zoom))
                    shown = image.crop((left,top,end_x,end_z))
                    shown = shown.resize((round(shown.width*self.camera.zoom),round(shown.height*self.camera.zoom)),Image.Resampling.NEAREST)
                    x += round(left*self.camera.zoom); y += round(top*self.camera.zoom)
                photo = ImageTk.PhotoImage(shown); self.photos[key] = photo
                c.create_image(x,y,anchor="nw",image=photo)
            elif key in self.failed:
                c.create_text(x+8,y+8,anchor="nw",fill="#f99",text="Tile unavailable (see log)")
            else:
                c.create_text(x+8,y+8,anchor="nw",fill="#999",text=f"Loading {rx},{rz}…")
                if key not in self.pending:
                    self.pending.add(key); self.jobs.put((key,self.cache))
        # Never evict a visible tile: large windows at low zoom can exceed 512.
        for key in list(self.images):
            if len(self.images) <= max(512,len(self.visible_keys)): break
            if key not in self.visible_keys: del self.images[key]
        self._report_status()
        if self.grid_enabled.get():
            self._grid(w,h)
        if self.dimension.get()=="minecraft:overworld":
            sx,sy = self.camera.screen(*self.spawn,w,h)
            c.create_line(sx-10,sy,sx+10,sy,fill="#ff5252",width=3)
            c.create_line(sx,sy-10,sx,sy+10,fill="#ff5252",width=3)
            c.create_text(sx+12,sy,anchor="w",text="Spawn",fill="#ff8888")
        c.create_text(w-65,38,text="N (−Z)\n↑\nW ← + → E\n↓ S (+Z)",fill="white")

    def _grid(self,w,h):
        left,top = self.camera.world(0,0,w,h); right,bottom = self.camera.world(w,h,w,h)
        step = 16 if self.camera.zoom >= .5 else 512
        for x in range(math.floor(left/step)*step,math.ceil(right/step)*step+1,step):
            sx,_ = self.camera.screen(x,0,w,h)
            self.canvas.create_line(sx,0,sx,h,fill="#777" if x%512==0 else "#444",width=2 if x%512==0 else 1)
        for z in range(math.floor(top/step)*step,math.ceil(bottom/step)*step+1,step):
            _,sy = self.camera.screen(0,z,w,h)
            self.canvas.create_line(0,sy,w,sy,fill="#777" if z%512==0 else "#444",width=2 if z%512==0 else 1)

    def _worker(self):
        # Disk hits stay in this I/O thread. Only missing regions use processes.
        executor = None
        running = {}
        try:
            while not self.closed.is_set():
                for future in list(running):
                    if not future.done(): continue
                    key,_ = running.pop(future)
                    try: self.results.put((key,future.result(),None))
                    except Exception as exc:
                        import logging
                        logging.exception("Map tile failed: %s",key)
                        self.results.put((key,None,str(exc)))
                self.active_job = next(iter(running.values()),None)
                if len(running) >= self.render_workers:
                    self.closed.wait(.03)
                    continue
                try: key,cache = self.jobs.get(timeout=.05)
                except queue.Empty: continue
                try:
                    hit = cache.cached(*key[1:])
                    if hit is not None:
                        self.results.put((key,hit,None))
                        continue
                    if executor is None:
                        executor = ProcessPoolExecutor(max_workers=self.render_workers,
                            initializer=configure_render_logging,initargs=(self.log_path,))
                    future = executor.submit(render_tile,cache,*key[1:])
                    running[future] = (key,time.monotonic())
                except Exception as exc:
                    self.results.put((key,None,str(exc)))
        finally:
            self.active_job = None
            if executor is not None:
                executor.shutdown(wait=True,cancel_futures=True)

    def _report_status(self):
        total = len(self.visible_keys)
        ready = sum(k in self.images for k in self.visible_keys)
        empty = sum(bool(getattr(self.images.get(k),'info',{}).get('empty_region')) for k in self.visible_keys)
        errors = len(self.visible_keys & self.failed)
        done = ready + errors
        self.export_button.configure(state="normal" if total and ready == total else "disabled")
        if not total:
            text = "No saved regions in this view. Use Fit saved world or Go To Spawn." if self.cache else "Select a world to load its map."
        elif done == total:
            text = f"Finished loading map: {ready-empty}/{total-empty} terrain tiles; {empty} areas with no saved region"
            if errors:
                text += f"; {errors} failed (see log)"
            text += ". Dark grey = no rendered terrain, not still loading."
        else:
            text = f"Loading map: {done-empty}/{total-empty} terrain tiles complete; {total-done} remaining; {empty} empty areas skipped"
            active = self.active_job
            if active:
                key,started = active
                text += f" | Processing region {key[2]},{key[3]} ({int(time.monotonic()-started)}s)"
                if key not in self.visible_keys:
                    text += " from previous view"
        if self.builds_enabled.get():
            text += " | Gold: likely build materials (may include natural structures)."
        state = (text,done-empty,total-empty)
        if state != self.last_status:
            self.last_status = state
            self.loading_info.configure(text=text)
            self.on_status(*state)

    def export_png(self):
        """Export the displayed pixels; never re-read or render Minecraft data."""
        if not self.visible_keys or any(k not in self.images for k in self.visible_keys):
            messagebox.showinfo("Export PNG", "Wait for the visible map tiles to finish loading before exporting.", parent=self)
            return
        # Snapshot before opening the native dialog, which can process Tk events.
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        image = Image.new("RGB", (width,height), (30,30,34))
        for item in self.canvas.find_all():
            if self.canvas.type(item) == "image":
                x,y = self.canvas.coords(item)
                photo_name = self.canvas.itemcget(item,"image")
                photo = next((p for p in self.photos.values() if str(p)==photo_name),None)
                if photo is not None:
                    image.paste(ImageTk.getimage(photo).convert("RGB"),(round(x),round(y)))
        # Keep the optional grid and spawn marker, excluding UI controls/status.
        draw = ImageDraw.Draw(image)
        for item in self.canvas.find_all():
            kind = self.canvas.type(item)
            coords = self.canvas.coords(item)
            if kind == "line":
                draw.line(coords, fill=self.canvas.itemcget(item,"fill"), width=int(float(self.canvas.itemcget(item,"width"))))
        if self.dimension.get() == "minecraft:overworld":
            sx,sy = self.camera.screen(*self.spawn,width,height)
            if 0 <= sx < width and 0 <= sy < height:
                draw.text((sx+12,sy),"Spawn",fill="#ff8888")
        draw.text((width-75,8),"N (-Z)\n   ^\nW  +  E\n   v\nS (+Z)",fill="white")
        metadata = PngInfo()
        for key,value in {"World":self.world_name,"Dimension":self.dimension.get(),"Layer":self.effective_layer(),
                          "Centre X":self.camera.x,"Centre Z":self.camera.z,"Zoom":self.camera.zoom}.items():
            metadata.add_text(key,str(value))
        folder = Path(self.output) / "exports"
        folder.mkdir(parents=True,exist_ok=True)
        filename = filedialog.asksaveasfilename(parent=self,title="Export current map view to PNG",
            initialdir=str(folder.resolve()),initialfile=export_filename(self.world_name,self.effective_layer(),self.camera.x,self.camera.z),
            defaultextension=".png",filetypes=[("PNG image","*.png")])
        if not filename:
            return
        try:
            image.save(filename,format="PNG",pnginfo=metadata)
        except OSError as exc:
            messagebox.showerror("Export PNG",f"Could not save the map:\n{exc}",parent=self)
            return
        messagebox.showinfo("Export PNG",f"Map saved to:\n{filename}",parent=self)

    def _poll(self):
        changed = False
        while True:
            try: key,image,error = self.results.get_nowait()
            except queue.Empty: break
            self.pending.discard(key)
            if key[0] != self.epoch: continue
            if error: self.failed.add(key)
            else: self.images[key] = image
            changed = True
        if changed: self.redraw()
        else: self._report_status()
        if not self.closed.is_set(): self.after(80,self._poll)

    def _destroy(self,event):
        if event.widget is self:
            self.closed.set()

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


from .db import ArchiveDB
from .importer import import_world
from .map_view import MapView
from .world_layout import discover_worlds


class ViewerApp(tk.Tk):
    def __init__(self, db: ArchiveDB, config: dict, root_path: Path):
        super().__init__()
        self.db, self.settings, self.root_path = db, config, root_path
        self.selected_world: int | None = None
        self.events: queue.Queue = queue.Queue()
        self.import_jobs = 0
        self.map_status = ("Ready",0,0)
        self.title("Minecraft Viewer"); self.geometry("1200x760"); self.minsize(900, 600)
        self._menu(); self._layout(); self.refresh_worlds(); self.after(100, self._poll)

    def _menu(self):
        bar = tk.Menu(self); file = tk.Menu(bar, tearoff=False)
        file.add_command(label="Add World...", command=self.add_world); file.add_command(label="Scan Folder...", command=self.scan_folder)
        file.add_separator(); file.add_command(label="Exit", command=self.destroy)
        bar.add_cascade(label="File", menu=file); bar.add_cascade(label="Import", menu=file)
        help_menu = tk.Menu(bar, tearoff=False); help_menu.add_command(label="About", command=lambda: messagebox.showinfo("Minecraft Viewer", "Minecraft Viewer 0.1\nRead-only Java world archive"))
        bar.add_cascade(label="Help", menu=help_menu); self.config(menu=bar)

    def _layout(self):
        outer = ttk.Panedwindow(self, orient=tk.HORIZONTAL); outer.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        left = ttk.Frame(outer, width=260); right = ttk.Frame(outer); outer.add(left, weight=1); outer.add(right, weight=4)
        ttk.Label(left, text="Worlds", font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=5)
        self.worlds = ttk.Treeview(left, columns=("name",), show="tree", selectmode="browse"); self.worlds.pack(fill=tk.BOTH, expand=True)
        self.worlds.bind("<<TreeviewSelect>>", self._select_world)
        buttons = ttk.Frame(left); buttons.pack(fill=tk.X, pady=5)
        ttk.Button(buttons, text="Add World", command=self.add_world).pack(side=tk.LEFT); ttk.Button(buttons, text="Scan", command=self.scan_folder).pack(side=tk.LEFT)
        self.tabs = ttk.Notebook(right); self.tabs.pack(fill=tk.BOTH, expand=True)
        overview_frame = ttk.Frame(self.tabs); self.tabs.add(overview_frame, text="Overview")
        overview_tools = ttk.Frame(overview_frame); overview_tools.pack(fill=tk.X, pady=4)
        ttk.Button(overview_tools, text="Open Source Folder", command=self.open_source).pack(side=tk.LEFT, padx=3)
        ttk.Button(overview_tools, text="Import / Refresh", command=self.refresh_import).pack(side=tk.LEFT, padx=3)
        ttk.Button(overview_tools, text="Browse Map", command=self.generate_default_maps).pack(side=tk.LEFT, padx=3)
        self.overview = tk.Text(overview_frame, wrap="word", padx=12, pady=12); self.overview.pack(fill=tk.BOTH, expand=True)
        self.players_tab = ttk.Frame(self.tabs); self.tabs.add(self.players_tab, text="Players")
        self._players_ui(); self.stats_tab = ttk.Frame(self.tabs); self.tabs.add(self.stats_tab, text="Stats & Advancements"); self._stats_ui()
        self.maps_tab = ttk.Frame(self.tabs); self.tabs.add(self.maps_tab, text="Maps"); self._maps_ui()
        self.world_data = self._text_tab("World Data"); self.archive = self._table_tab("Archive", ("date", "source", "version", "layout", "status", "size"))
        future = self._text_tab("Sessions & Screenshots")
        future.insert("1.0", "Server Sessions & Screenshots\n\nFuture functionality:\n- import Minecraft server logs\n- record player join/leave sessions\n- index screenshots\n- correlate screenshots with active worlds\n- build a combined world timeline")
        future.configure(state="disabled")
        status = ttk.Frame(self); status.pack(fill=tk.X); self.status = ttk.Label(status, text="Ready"); self.status.pack(side=tk.LEFT, padx=6)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)
        self.tabs.bind("<<NotebookTabChanged>>", lambda _: self._display_map_status())

    def _text_tab(self, title):
        frame = ttk.Frame(self.tabs); self.tabs.add(frame, text=title); text = tk.Text(frame, wrap="word", padx=12, pady=12); text.pack(fill=tk.BOTH, expand=True); return text

    def _table_tab(self, title, columns):
        frame = ttk.Frame(self.tabs); self.tabs.add(frame, text=title); tree = ttk.Treeview(frame, columns=columns, show="headings")
        for c in columns: tree.heading(c, text=c.replace("_", " ").title()); tree.column(c, width=120)
        tree.pack(fill=tk.BOTH, expand=True); return tree

    def _players_ui(self):
        paned = ttk.Panedwindow(self.players_tab, orient=tk.HORIZONTAL); paned.pack(fill=tk.BOTH, expand=True)
        self.player_list = ttk.Treeview(paned, columns=("uuid", "name"), show="headings"); self.player_list.heading("uuid", text="UUID"); self.player_list.heading("name", text="Name")
        self.player_detail = tk.Text(paned, padx=10, pady=10); paned.add(self.player_list, weight=2); paned.add(self.player_detail, weight=3)
        self.player_list.bind("<<TreeviewSelect>>", self._show_player)

    def _stats_ui(self):
        top = ttk.Frame(self.stats_tab); top.pack(fill=tk.X, pady=4)
        ttk.Label(top, text="Player:").pack(side=tk.LEFT); self.stat_player = ttk.Combobox(top, state="readonly", width=40); self.stat_player.pack(side=tk.LEFT, padx=4); self.stat_player.bind("<<ComboboxSelected>>", lambda _: self._load_stats())
        ttk.Label(top, text="Filter:").pack(side=tk.LEFT); self.stat_filter = ttk.Entry(top); self.stat_filter.pack(side=tk.LEFT, padx=4); self.stat_filter.bind("<KeyRelease>", lambda _: self._load_stats())
        inner = ttk.Notebook(self.stats_tab); inner.pack(fill=tk.BOTH, expand=True)
        self.stats = self._tree_in_notebook(inner, "Statistics", ("group", "statistic", "value")); self.advancements = self._tree_in_notebook(inner, "Advancements", ("advancement", "complete", "date"))

    def _tree_in_notebook(self, notebook, title, columns):
        frame = ttk.Frame(notebook); notebook.add(frame, text=title); tree = ttk.Treeview(frame, columns=columns, show="headings")
        for c in columns: tree.heading(c, text=c.title()); tree.column(c, width=160)
        tree.pack(fill=tk.BOTH, expand=True); return tree

    def _maps_ui(self):
        output = Path(self.settings["map_output_path"])
        if not output.is_absolute():
            output = self.root_path / output
        log_path = self.root_path / "logs" / "minecraft_viewer.log"
        log_path.parent.mkdir(parents=True,exist_ok=True)
        self.map_view = MapView(self.maps_tab, self.db, output, self._map_status_changed,
                                self.settings.get("map_render_workers",4), log_path)
        self.map_view.pack(fill=tk.BOTH, expand=True)

    def refresh_worlds(self):
        self.worlds.delete(*self.worlds.get_children())
        for row in self.db.rows("SELECT world_id,world_name FROM mc_world ORDER BY world_name"):
            self.worlds.insert("", "end", iid=str(row[0]), text=row[1])

    def _select_world(self, _=None):
        selection = self.worlds.selection()
        if not selection: return
        self.selected_world = int(selection[0]); self.refresh_details(); self.map_view.set_world(self.selected_world)

    def refresh_details(self):
        w = self.db.row("SELECT * FROM mc_world WHERE world_id=?", (self.selected_world,)); s = self.db.row("SELECT * FROM mc_world_source WHERE world_id=? ORDER BY last_seen_at DESC LIMIT 1", (self.selected_world,))
        dims = self.db.rows("SELECT dimension_key,chunk_count FROM mc_dimension WHERE import_id=(SELECT MAX(import_id) FROM mc_import WHERE world_id=?)", (self.selected_world,))
        players = self.db.rows("SELECT * FROM mc_player WHERE world_id=?", (self.selected_world,))
        lines = [f"World name: {w['world_name']}", f"Source folder: {s['source_path'] if s else ''}", f"Edition: {w['edition']}", f"Minecraft / data version: {w['minecraft_version']} / {w['data_version']}", f"Seed: {w['seed']}", f"Game mode: {w['game_type']}", f"Difficulty: {w['difficulty']}", f"Hardcore: {bool(w['hardcore'])}", f"Spawn: {w['spawn_x']}, {w['spawn_y']}, {w['spawn_z']}", "", "Dimensions:"] + [f"  {d[0]}: {d[1]:,} chunks" for d in dims] + ["", f"Players: {len(players)}", f"Last import: {w['last_imported_at']}"]
        self._replace(self.overview, "\n".join(lines)); self.player_list.delete(*self.player_list.get_children())
        names = []
        for p in players: self.player_list.insert("", "end", iid=str(p[0]), values=(p[2], p[3] or "")); names.append(f"{p[2]} | {p[0]}")
        self.stat_player["values"] = names
        if names: self.stat_player.set(names[0]); self._load_stats()
        self.archive.delete(*self.archive.get_children())
        for r in self.db.rows("SELECT i.started_at,s.source_path,w.minecraft_version,i.layout_type,i.status,i.source_size_bytes FROM mc_import i JOIN mc_world_source s USING(world_source_id) JOIN mc_world w USING(world_id) WHERE i.world_id=? ORDER BY i.import_id DESC", (self.selected_world,)):
            self.archive.insert("", "end", values=tuple(r))
        props = self.db.rows("SELECT property_name,property_value,source FROM mc_world_property WHERE import_id=(SELECT MAX(import_id) FROM mc_import WHERE world_id=?)", (self.selected_world,))
        self._replace(self.world_data, "Dimensions\n" + "\n".join(f"{d[0]}: {d[1]} chunks" for d in dims) + "\n\nWorld properties\n" + "\n".join(f"{p[0]} = {p[1]} ({p[2]})" for p in props))

    def _replace(self, widget, text): widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", text); widget.configure(state="disabled")

    def add_world(self):
        path = filedialog.askdirectory(title="Choose a Minecraft Java world", initialdir=self.settings.get("last_world_folder") or None)
        if path: self._start_import(Path(path))

    def scan_folder(self):
        path = filedialog.askdirectory(title="Choose a folder containing worlds")
        if not path: return
        worlds = discover_worlds(path, recursive=True)
        if not worlds: messagebox.showinfo("Scan Folder", "No Java worlds were found."); return
        if messagebox.askyesno("Scan Folder", f"Found {len(worlds)} world(s). Import all? "):
            self._run(lambda: [import_world(self.db, p, self._post_status) for p in worlds], self._import_done)

    def _start_import(self, path): self._run(lambda: import_world(self.db, path, self._post_status), self._import_done)
    def _selected_source(self):
        if not self.selected_world: return None
        row = self.db.row("SELECT source_path FROM mc_world_source WHERE world_id=? AND is_current=1 ORDER BY last_seen_at DESC LIMIT 1", (self.selected_world,))
        return Path(row[0]) if row else None
    def open_source(self):
        source = self._selected_source()
        if source and source.exists(): os.startfile(source)
        else: messagebox.showinfo("World", "Select an imported world first.")
    def refresh_import(self):
        source = self._selected_source()
        if source: self._start_import(source)
        else: messagebox.showinfo("World", "Select an imported world first.")
    def generate_default_maps(self):
        if not self.selected_world:
            messagebox.showinfo("Maps", "Select a world first.")
            return
        self.tabs.select(self.maps_tab)
        self.map_view.go_spawn()

    def _run(self, work, done):
        self.import_jobs += 1
        self.progress.configure(mode="indeterminate")
        self.progress.pack(side=tk.RIGHT, padx=6)
        self.progress.start(10)
        def target():
            try: result = work(); self.events.put((done, result, None))
            except Exception as exc: self.events.put((done, None, exc))
        threading.Thread(target=target, daemon=True).start()
    def _post_status(self, text): self.events.put(("status", text, None))
    def _poll(self):
        try:
            while True:
                action, value, error = self.events.get_nowait()
                if action == "status": self.status.configure(text=value)
                else: action(value, error)
        except queue.Empty: pass
        self.after(100, self._poll)
    def _import_done(self, result, error):
        self.import_jobs = max(0,self.import_jobs-1)
        if not self.import_jobs:
            self.progress.stop()
            self.progress.pack_forget()
        if error: messagebox.showerror("Import failed", str(error)); self.status.configure(text="Import failed")
        else: self.status.configure(text="Import complete"); self.refresh_worlds()
        if self.tabs.select() == str(self.maps_tab): self._display_map_status()

    def _map_status_changed(self, text, done, total):
        self.map_status = (text, done, total)
        self._display_map_status()

    def _display_map_status(self):
        if not hasattr(self, "progress") or self.import_jobs:
            return
        self.progress.stop()
        self.progress.pack_forget()
        if self.tabs.select() != str(self.maps_tab):
            self.status.configure(text="Ready")
            return
        text, done, total = self.map_status
        self.status.configure(text=text)
        if done < total:
            self.progress.configure(mode="determinate", maximum=total, value=done)
            self.progress.pack(side=tk.RIGHT,padx=6)

    def _show_player(self, _=None):
        if not self.player_list.selection(): return
        pid = int(self.player_list.selection()[0]); p = self.db.row("SELECT p.*,s.* FROM mc_player p LEFT JOIN mc_player_snapshot s ON s.player_id=p.player_id WHERE p.player_id=? ORDER BY s.player_snapshot_id DESC LIMIT 1", (pid,))
        inv = self.db.rows("SELECT container_type,slot,item_id,count FROM mc_player_inventory WHERE player_snapshot_id=? ORDER BY container_type,slot", (p["player_snapshot_id"],)) if p and p["player_snapshot_id"] else []
        text = f"UUID: {p['player_uuid']}\nName: {p['player_name'] or '(unknown)'}\nPosition: {p['pos_x']}, {p['pos_y']}, {p['pos_z']}\nDimension: {p['dimension_key']}\nHealth / food: {p['health']} / {p['food_level']}\nXP level / total: {p['xp_level']} / {p['xp_total']}\nSpawn: {p['spawn_x']}, {p['spawn_y']}, {p['spawn_z']}\nLast death: {p['last_death_dimension']} {p['last_death_x']}, {p['last_death_y']}, {p['last_death_z']}\n\nInventory / Ender Chest\n" + "\n".join(f"{i[0]} [{i[1]}] {i[2]} x{i[3]}" for i in inv)
        self._replace(self.player_detail, text)

    def _load_stats(self):
        if not self.stat_player.get(): return
        pid = int(self.stat_player.get().rsplit("|", 1)[1]); query = self.stat_filter.get().lower()
        self.stats.delete(*self.stats.get_children()); self.advancements.delete(*self.advancements.get_children())
        for r in self.db.rows("SELECT stat_group,stat_name,value FROM mc_player_stat WHERE player_id=? AND import_id=(SELECT MAX(import_id) FROM mc_player_stat WHERE player_id=?)", (pid, pid)):
            if query in (r[0] + r[1]).lower(): self.stats.insert("", "end", values=tuple(r))
        for r in self.db.rows("SELECT advancement_key,completed,completed_at FROM mc_player_advancement WHERE player_id=? AND import_id=(SELECT MAX(import_id) FROM mc_player_advancement WHERE player_id=?) ORDER BY completed_at", (pid, pid)):
            self.advancements.insert("", "end", values=(r[0], "Yes" if r[1] else "No", r[2] or ""))

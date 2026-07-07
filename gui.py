"""
gui.py — Interface graphique du launcher, design sombre inspiré des launchers
premium type Lunar Client / Feather Client : sidebar de navigation, cartes
pour les instances et les mods, gros bouton JOUER arrondi, avatars de profil.
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, simpledialog

import core
import theme
from core import (
    APP_DIR, INSTANCES_DIR, SERVERS_DIR, MojangAPI, FabricAPI, ModrinthAPI, LaunchManager,
    ServerManager, get_local_ip, load_config, save_config, offline_uuid,
    DiscordPresence,
    install_forge,  # <--- AJOUT POUR FORGE
)
from theme import (
    BG_DARK, BG_DARKEST, BG_CARD, BG_CARD_HOVER, BG_INPUT, ACCENT, ACCENT_HOVER,
    SUCCESS, DANGER, WARNING, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BORDER,
    RoundedButton, Badge, ScrollableFrame, Avatar, font,
)

NAV_ITEMS = [
    ("play", "▶  Jouer"),
    ("mods", "🧩  Mods"),
    ("servers", "🖧  Serveurs"),
    ("accounts", "👤  Comptes"),
    ("settings", "⚙  Paramètres"),
    ("logs", "🖥  Logs"),
]


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PyMC Launcher")
        self.geometry("1150x720")
        self.minsize(1000, 620)
        theme.apply_global_theme(self)
        self.configure(bg=BG_DARK)

        self.cfg = load_config()
        self.pages = {}
        self.nav_buttons = {}
        self._current_page = "play"
        self.server_procs = {}          # nom -> subprocess.Popen
        self.server_logs = {}           # nom -> liste de lignes de console
        self._selected_server_name_value = None

        self._build_layout()
        self.show_page("play")
        self.refresh_instance_list()
        self.refresh_account_list()
        self.refresh_server_list()

        # Présence Discord au démarrage
        try:
            DiscordPresence.set_idle()
        except Exception:
            pass

    # ================================================================ Layout
    def _build_layout(self):
        root = tk.Frame(self, bg=BG_DARK)
        root.pack(fill="both", expand=True)

        # --- Sidebar ---
        sidebar = tk.Frame(root, bg=BG_DARKEST, width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        logo = tk.Label(sidebar, text="⛏ PyMC", bg=BG_DARKEST, fg=ACCENT,
                         font=font(20, "bold"))
        logo.pack(anchor="w", padx=20, pady=(24, 4))
        tk.Label(sidebar, text="LAUNCHER", bg=BG_DARKEST, fg=TEXT_MUTED,
                 font=font(9, "bold")).pack(anchor="w", padx=22, pady=(0, 25))

        for key, label in NAV_ITEMS:
            btn = tk.Label(sidebar, text=label, bg=BG_DARKEST, fg=TEXT_SECONDARY,
                            font=font(11), anchor="w", padx=22, pady=12, cursor="hand2")
            btn.pack(fill="x")
            btn.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            btn.bind("<Enter>", lambda e, b=btn, k=key: self._nav_hover(b, k, True))
            btn.bind("<Leave>", lambda e, b=btn, k=key: self._nav_hover(b, k, False))
            self.nav_buttons[key] = btn

        # Profil actif en bas de la sidebar
        profile_frame = tk.Frame(sidebar, bg=BG_DARKEST)
        profile_frame.pack(side="bottom", fill="x", padx=16, pady=18)
        self.sidebar_avatar_holder = tk.Frame(profile_frame, bg=BG_DARKEST)
        self.sidebar_avatar_holder.pack(side="left")
        info = tk.Frame(profile_frame, bg=BG_DARKEST)
        info.pack(side="left", padx=8)
        tk.Label(info, text="Connecté en tant que", bg=BG_DARKEST, fg=TEXT_MUTED,
                 font=font(8)).pack(anchor="w")
        self.sidebar_account_label = tk.Label(info, text="(aucun compte)", bg=BG_DARKEST,
                                               fg=TEXT_PRIMARY, font=font(10, "bold"))
        self.sidebar_account_label.pack(anchor="w")

        # --- Contenu principal ---
        self.content = tk.Frame(root, bg=BG_DARK)
        self.content.pack(side="left", fill="both", expand=True)

        for key, _ in NAV_ITEMS:
            page = tk.Frame(self.content, bg=BG_DARK)
            self.pages[key] = page

        self._build_play_page()
        self._build_mods_page()
        self._build_servers_page()
        self._build_accounts_page()
        self._build_settings_page()
        self._build_logs_page()

        # --- Barre de statut ---
        bottom = tk.Frame(self, bg=BG_DARKEST, height=34)
        bottom.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bottom, style="Accent.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True, padx=(10, 10), pady=8)
        self.status_var = tk.StringVar(value="Prêt.")
        tk.Label(bottom, textvariable=self.status_var, bg=BG_DARKEST, fg=TEXT_SECONDARY,
                 font=font(9), width=45, anchor="e").pack(side="right", padx=10)

    def _nav_hover(self, btn, key, entering):
        if key == self._current_page:
            return
        btn.config(bg=BG_CARD if entering else BG_DARKEST)

    def show_page(self, key):
        self._current_page = key
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, btn in self.nav_buttons.items():
            active = k == key
            btn.config(bg=BG_CARD if active else BG_DARKEST,
                       fg=ACCENT if active else TEXT_SECONDARY,
                       font=font(11, "bold" if active else "normal"))
        if key == "mods":
            self._refresh_mods_instance_combo()
        if key == "servers":
            self._refresh_server_console()

    def _refresh_sidebar_profile(self):
        for w in self.sidebar_avatar_holder.winfo_children():
            w.destroy()
        active = self.cfg.get("active_account")
        if active:
            Avatar(self.sidebar_avatar_holder, active[0], size=34, bg=ACCENT).pack()
            self.sidebar_account_label.config(text=active)
        else:
            Avatar(self.sidebar_avatar_holder, "?", size=34, bg=BG_CARD, fg=TEXT_MUTED).pack()
            self.sidebar_account_label.config(text="(aucun compte)")

    # ============================================================= Play page
    def _build_play_page(self):
        page = self.pages["play"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 10))
        tk.Label(header, text="Mes instances", bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=font(20, "bold")).pack(side="left")
        RoundedButton(header, "+ Nouvelle instance", command=self.create_instance_dialog,
                      bg=BG_CARD, hover_bg=BG_CARD_HOVER, width=190, height=38,
                      font_size=10).pack(side="right")

        body = tk.Frame(page, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=30, pady=10)

        # Liste des instances (cartes) à gauche
        list_col = tk.Frame(body, bg=BG_DARK)
        list_col.pack(side="left", fill="both", expand=True)
        self.instances_scroll = ScrollableFrame(list_col, bg=BG_DARK)
        self.instances_scroll.pack(fill="both", expand=True)

        # Panneau de détail / lancement à droite
        detail_col = tk.Frame(body, bg=BG_CARD, width=320)
        detail_col.pack(side="left", fill="y", padx=(20, 0))
        detail_col.pack_propagate(False)

        inner = tk.Frame(detail_col, bg=BG_CARD, padx=22, pady=22)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="DÉTAILS", bg=BG_CARD, fg=TEXT_MUTED, font=font(9, "bold")).pack(anchor="w")
        self.instance_name_label = tk.Label(inner, text="Aucune instance sélectionnée", bg=BG_CARD,
                                             fg=TEXT_PRIMARY, font=font(15, "bold"), wraplength=270, justify="left")
        self.instance_name_label.pack(anchor="w", pady=(4, 14))

        self.instance_meta_label = tk.Label(inner, text="", bg=BG_CARD, fg=TEXT_SECONDARY,
                                             font=font(10), justify="left")
        self.instance_meta_label.pack(anchor="w")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=18)

        RoundedButton(inner, "Installer / Vérifier", command=self.install_instance,
                      bg=BG_INPUT, hover_bg=BG_CARD_HOVER, width=276, height=40,
                      font_size=10).pack(pady=(0, 10))
        RoundedButton(inner, "Supprimer l'instance", command=self.delete_instance,
                      bg=BG_INPUT, hover_bg=DANGER, width=276, height=40,
                      font_size=10).pack(pady=(0, 20))

        self.play_button = RoundedButton(inner, "▶  JOUER", command=self.launch_instance,
                                          bg=ACCENT, hover_bg=ACCENT_HOVER, width=276, height=54,
                                          font_size=14)
        self.play_button.pack(side="bottom")

        self._selected_instance_name_value = None

    def refresh_instance_list(self):
        for w in self.instances_scroll.inner.winfo_children():
            w.destroy()
        for name, inst in self.cfg["instances"].items():
            self._make_instance_card(self.instances_scroll.inner, name, inst)
        if not self.cfg["instances"]:
            tk.Label(self.instances_scroll.inner, text="Aucune instance. Clique sur « + Nouvelle instance ».",
                     bg=BG_DARK, fg=TEXT_MUTED, font=font(10)).pack(pady=30)

    def _make_instance_card(self, parent, name, inst):
        selected = name == self._selected_instance_name_value
        card = tk.Frame(parent, bg=BG_CARD if not selected else BG_CARD_HOVER, cursor="hand2")
        card.pack(fill="x", pady=6)
        accent_strip = tk.Frame(card, bg=ACCENT if selected else BORDER, width=4)
        accent_strip.pack(side="left", fill="y")
        inner = tk.Frame(card, bg=card["bg"], padx=16, pady=12)
        inner.pack(side="left", fill="both", expand=True)

        title_row = tk.Frame(inner, bg=card["bg"])
        title_row.pack(fill="x", anchor="w")
        tk.Label(title_row, text=name, bg=card["bg"], fg=TEXT_PRIMARY,
                 font=font(12, "bold")).pack(side="left")
        loader = inst.get("loader", "vanilla")
        badge_text = loader.upper() if loader != "vanilla" else "VANILLA"
        badge_color = ACCENT if loader == "fabric" else (WARNING if loader == "forge" else TEXT_MUTED)
        Badge(title_row, badge_text, bg=badge_color).pack(side="left", padx=8)

        tk.Label(inner, text=f"Minecraft {inst['version']}", bg=card["bg"], fg=TEXT_SECONDARY,
                 font=font(9)).pack(anchor="w", pady=(4, 0))

        def select(_e=None):
            self._selected_instance_name_value = name
            self.refresh_instance_list()
            self._update_instance_details(name, inst)

        for widget in (card, inner, title_row) + tuple(inner.winfo_children()) + tuple(title_row.winfo_children()):
            widget.bind("<Button-1>", select)

    def _selected_instance_name(self):
        return self._selected_instance_name_value

    def _update_instance_details(self, name, inst):
        self.instance_name_label.config(text=name)
        loader_txt = inst.get("loader", "vanilla")
        if inst.get("loader_version"):
            loader_txt += f" {inst['loader_version']}"
        java_txt = inst.get("java_path") or "Java système (voir Paramètres)"
        self.instance_meta_label.config(
            text=f"Version : {inst['version']}\nLoader : {loader_txt}\nJava : {java_txt}\nDossier :\n{inst['dir']}"
        )

    def create_instance_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Nouvelle instance")
        dialog.geometry("440x380")
        dialog.configure(bg=BG_DARK)
        dialog.grab_set()

        pad = dict(padx=18)
        tk.Label(dialog, text="Nom de l'instance", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", **pad, pady=(18, 2))
        name_var = tk.StringVar()
        tk.Entry(dialog, textvariable=name_var, bg=BG_INPUT, fg=TEXT_PRIMARY,
                 insertbackground=TEXT_PRIMARY, relief="flat", font=font(11)).pack(fill="x", **pad, ipady=6)

        show_snap_var = tk.BooleanVar(value=False)
        snap_row = tk.Frame(dialog, bg=BG_DARK)
        snap_row.pack(fill="x", **pad, pady=(14, 0))
        tk.Checkbutton(snap_row, text="Afficher les snapshots", variable=show_snap_var,
                        bg=BG_DARK, fg=TEXT_SECONDARY, selectcolor=BG_INPUT,
                        activebackground=BG_DARK, command=lambda: populate_versions(),
                        font=font(9)).pack(anchor="w")

        tk.Label(dialog, text="Version Minecraft", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", **pad, pady=(14, 2))
        version_var = tk.StringVar()
        version_combo = ttk.Combobox(dialog, textvariable=version_var, state="readonly")
        version_combo.pack(fill="x", **pad)

        def populate_versions():
            try:
                versions = MojangAPI.all_versions() if show_snap_var.get() else MojangAPI.release_versions()
            except Exception as e:
                messagebox.showerror("Erreur réseau", str(e))
                return
            ids = [v["id"] for v in versions]
            version_combo["values"] = ids
            if ids:
                version_var.set(ids[0])

        threading.Thread(target=populate_versions, daemon=True).start()

        tk.Label(dialog, text="Mod loader", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", **pad, pady=(14, 2))
        loader_var = tk.StringVar(value="vanilla")
        ttk.Combobox(dialog, textvariable=loader_var, state="readonly",
                     values=["vanilla", "fabric", "forge"]).pack(fill="x", **pad)  # <--- AJOUT FORGE

        def confirm():
            name = name_var.get().strip()
            version = version_var.get().strip()
            if not name or not version:
                messagebox.showinfo("Info", "Renseignez un nom et une version.")
                return
            if name in self.cfg["instances"]:
                messagebox.showerror("Erreur", "Ce nom d'instance existe déjà.")
                return
            inst_dir = INSTANCES_DIR / name
            self.cfg["instances"][name] = {
                "version": version,
                "loader": loader_var.get(),
                "loader_version": None,
                "fabric_info": None,
                "forge_info": None,  # <--- AJOUT POUR FORGE
                "dir": str(inst_dir),
            }
            save_config(self.cfg)
            self.refresh_instance_list()
            dialog.destroy()
            self.set_status(f"Instance '{name}' créée. Pense à l'installer avant de jouer.")

        RoundedButton(dialog, "Créer l'instance", command=confirm, bg=ACCENT, hover_bg=ACCENT_HOVER,
                      width=200, height=42, font_size=11).pack(pady=24)

    def delete_instance(self):
        name = self._selected_instance_name()
        if not name:
            messagebox.showinfo("Info", "Sélectionne une instance.")
            return
        if messagebox.askyesno("Confirmer", f"Supprimer l'instance '{name}' (config uniquement) ?"):
            del self.cfg["instances"][name]
            save_config(self.cfg)
            self._selected_instance_name_value = None
            self.refresh_instance_list()

    def install_instance(self):
        name = self._selected_instance_name()
        if not name:
            messagebox.showinfo("Info", "Sélectionne une instance.")
            return
        inst = self.cfg["instances"][name]
        threading.Thread(target=self._install_instance_thread, args=(name, inst), daemon=True).start()

    def _install_instance_thread(self, name, inst):
        try:
            def cb(label, done, total):
                pct = (done / total) * 100 if total else 0
                self.after(0, lambda: self.set_status(f"{label} ({done}/{total})"))
                self.after(0, lambda: self.progress.config(value=pct))

            self.after(0, lambda: self.set_status("Installation de Minecraft..."))
            vjson = MojangAPI.install_version(inst["version"], progress_cb=cb)

            java_component = vjson.get("javaVersion", {}).get("component")
            if java_component:
                try:
                    java_exe = core.JavaRuntimeAPI.install(java_component, progress_cb=cb)
                    inst["java_path"] = str(java_exe)
                    save_config(self.cfg)
                except Exception as e:
                    self.after(0, lambda: self.set_status(f"Runtime Java officiel indisponible ({e}), Java système utilisé."))

            # --- Installation de Fabric ---
            if inst.get("loader") == "fabric":
                loaders = FabricAPI.loader_versions(inst["version"])
                if not loaders:
                    raise RuntimeError("Aucune version de Fabric disponible pour cette version de Minecraft.")
                loader_version = loaders[0]["loader"]["version"]
                fabric_info = FabricAPI.install(inst["version"], loader_version, progress_cb=cb)
                inst["loader_version"] = loader_version
                inst["fabric_info"] = {
                    "mainClass": fabric_info["mainClass"],
                    "libraries": [str(p) for p in fabric_info["libraries"]],
                }
                save_config(self.cfg)

            # <--- AJOUT : Installation de Forge
            if inst.get("loader") == "forge":
                self.after(0, lambda: self.set_status("Installation de Forge..."))
                try:
                    forge_version = install_forge(inst["version"], Path(inst["dir"]), progress_cb=cb)
                    if forge_version:
                        inst["loader_version"] = forge_version
                        inst["forge_info"] = {"installed": True, "version": forge_version}
                        save_config(self.cfg)
                        self.after(0, lambda: self.set_status(f"Forge {forge_version} installé !"))
                    else:
                        self.after(0, lambda: self.set_status("Échec de l'installation de Forge"))
                except Exception as e:
                    self.after(0, lambda: self.set_status(f"Erreur Forge : {e}"))

            self.after(0, lambda: self.progress.config(value=100))
            self.after(0, lambda: self.set_status(f"Instance '{name}' installée avec succès."))
            self.after(0, lambda: messagebox.showinfo("Succès", f"Instance '{name}' installée !"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur d'installation", str(e)))
            self.after(0, lambda: self.set_status("Échec de l'installation."))
        finally:
            self.after(0, lambda: self.progress.config(value=0))

    def launch_instance(self):
        name = self._selected_instance_name()
        if not name:
            messagebox.showinfo("Info", "Sélectionne une instance.")
            return
        if not self.cfg.get("active_account"):
            messagebox.showinfo("Info", "Ajoute et sélectionne un compte dans l'onglet Comptes.")
            return
        inst = self.cfg["instances"][name]
        account = next((a for a in self.cfg["accounts"] if a["username"] == self.cfg["active_account"]), None)
        if account is None:
            messagebox.showerror("Erreur", "Compte actif introuvable.")
            return

        client_jar = Path(core.VERSIONS_DIR) / inst["version"] / f"{inst['version']}.jar"
        if not client_jar.exists():
            if messagebox.askyesno("Non installé", "Cette instance n'est pas encore installée. L'installer maintenant ?"):
                self.install_instance()
            return

        self.play_button.set_enabled(False)
        self.play_button.set_text("Lancement...")
        threading.Thread(target=self._launch_thread, args=(inst, account), daemon=True).start()

    def _launch_thread(self, inst, account):
        try:
            self.after(0, lambda: self.set_status("Lancement de Minecraft..."))

            def log(line):
                self.after(0, lambda: self._append_log(line))

            java_path = inst.get("java_path") or self.cfg.get("java_path", "java")
            min_ram = self.cfg.get("min_ram", 1)
            max_ram = self.cfg.get("max_ram", 4)

            # Présence Discord : "en train de jouer"
            self.after(0, lambda: DiscordPresence.set_playing())

            LaunchManager.launch(inst, account, java_path, min_ram, max_ram, log_cb=log)

            self.after(0, lambda: self.set_status("Minecraft fermé."))
            self.after(0, lambda: DiscordPresence.set_idle())  # Retour à l'état idle
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur de lancement", str(e)))
            self.after(0, lambda: DiscordPresence.set_idle())
        finally:
            self.after(0, lambda: self.play_button.set_enabled(True))
            self.after(0, lambda: self.play_button.set_text("▶  JOUER"))

    # ============================================================= Mods page
    def _build_mods_page(self):
        page = self.pages["mods"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 10))
        tk.Label(header, text="Mods — Modrinth", bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=font(20, "bold")).pack(side="left")

        controls = tk.Frame(page, bg=BG_DARK)
        controls.pack(fill="x", padx=30, pady=(0, 12))

        tk.Label(controls, text="Instance :", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(side="left")
        self.mods_instance_var = tk.StringVar()
        self.mods_instance_combo = ttk.Combobox(controls, textvariable=self.mods_instance_var,
                                                 state="readonly", width=22)
        self.mods_instance_combo.pack(side="left", padx=(6, 20))

        tk.Label(controls, text="Recherche :", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(side="left")
        self.mod_query_var = tk.StringVar()
        entry = tk.Entry(controls, textvariable=self.mod_query_var, bg=BG_INPUT, fg=TEXT_PRIMARY,
                          insertbackground=TEXT_PRIMARY, relief="flat", width=30, font=font(10))
        entry.pack(side="left", padx=6, ipady=5)
        entry.bind("<Return>", lambda e: self.search_mods())
        RoundedButton(controls, "Rechercher", command=self.search_mods, bg=ACCENT, hover_bg=ACCENT_HOVER,
                      width=130, height=32, font_size=9).pack(side="left", padx=8)

        body = tk.Frame(page, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=30, pady=10)

        list_col = tk.Frame(body, bg=BG_DARK)
        list_col.pack(side="left", fill="both", expand=True)
        self.mods_scroll = ScrollableFrame(list_col, bg=BG_DARK)
        self.mods_scroll.pack(fill="both", expand=True)

        detail_col = tk.Frame(body, bg=BG_CARD, width=320)
        detail_col.pack(side="left", fill="y", padx=(20, 0))
        detail_col.pack_propagate(False)
        inner = tk.Frame(detail_col, bg=BG_CARD, padx=20, pady=20)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="DESCRIPTION", bg=BG_CARD, fg=TEXT_MUTED, font=font(9, "bold")).pack(anchor="w")
        self.mod_desc_label = tk.Label(inner, text="Sélectionne un mod à gauche.", bg=BG_CARD, fg=TEXT_SECONDARY,
                                        font=font(9), wraplength=270, justify="left")
        self.mod_desc_label.pack(anchor="w", pady=(4, 14))

        tk.Label(inner, text="VERSIONS COMPATIBLES", bg=BG_CARD, fg=TEXT_MUTED, font=font(9, "bold")).pack(anchor="w")
        self.mod_versions_scroll = ScrollableFrame(inner, bg=BG_CARD)
        self.mod_versions_scroll.pack(fill="both", expand=True, pady=(6, 0))

        self.mod_results = []
        self.mod_versions = []
        self.selected_mod_project = None

    def _refresh_mods_instance_combo(self):
        names = list(self.cfg["instances"].keys())
        self.mods_instance_combo["values"] = names
        if names and not self.mods_instance_var.get():
            self.mods_instance_var.set(names[0])

    def search_mods(self):
        query = self.mod_query_var.get().strip()
        if not query:
            return
        name = self.mods_instance_var.get()
        inst = self.cfg["instances"].get(name)
        mc_version = inst["version"] if inst else None
        loader = inst.get("loader") if inst else None
        self.set_status("Recherche de mods...")
        threading.Thread(target=self._search_mods_thread, args=(query, mc_version, loader), daemon=True).start()

    def _search_mods_thread(self, query, mc_version, loader):
        try:
            self.mod_results = ModrinthAPI.search(query, mc_version=mc_version, loader=loader)
            self.after(0, self._populate_mod_results)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur réseau", str(e)))

    def _populate_mod_results(self):
        for w in self.mods_scroll.inner.winfo_children():
            w.destroy()
        for r in self.mod_results:
            self._make_mod_card(r)
        if not self.mod_results:
            tk.Label(self.mods_scroll.inner, text="Aucun résultat.", bg=BG_DARK, fg=TEXT_MUTED,
                     font=font(10)).pack(pady=30)
        self.set_status(f"{len(self.mod_results)} mod(s) trouvé(s).")

    def _make_mod_card(self, r):
        selected = self.selected_mod_project is r
        card = tk.Frame(self.mods_scroll.inner, bg=BG_CARD_HOVER if selected else BG_CARD, cursor="hand2")
        card.pack(fill="x", pady=6)
        inner = tk.Frame(card, bg=card["bg"], padx=16, pady=10)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=r.get("title", "Sans nom"), bg=card["bg"], fg=TEXT_PRIMARY,
                 font=font(12, "bold")).pack(anchor="w")
        tk.Label(inner, text=f"par {r.get('author', '?')}  ·  {r.get('downloads', 0):,} téléchargements",
                 bg=card["bg"], fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", pady=(2, 0))

        def select(_e=None):
            self._on_mod_select(r)

        for w in (card, inner) + tuple(inner.winfo_children()):
            w.bind("<Button-1>", select)

    def _on_mod_select(self, project):
        self.selected_mod_project = project
        self._populate_mod_results()  # pour re-highlighter la carte sélectionnée
        self.mod_desc_label.config(text=project.get("description", ""))

        for w in self.mod_versions_scroll.inner.winfo_children():
            w.destroy()
        tk.Label(self.mod_versions_scroll.inner, text="Chargement...", bg=BG_CARD, fg=TEXT_MUTED,
                 font=font(9)).pack(pady=10)

        name = self.mods_instance_var.get()
        inst = self.cfg["instances"].get(name)
        mc_version = inst["version"] if inst else None
        loader = inst.get("loader") if inst else None
        project_id = project.get("project_id") or project.get("slug")
        threading.Thread(target=self._load_mod_versions_thread, args=(project_id, mc_version, loader), daemon=True).start()

    def _load_mod_versions_thread(self, project_id, mc_version, loader):
        try:
            self.mod_versions = ModrinthAPI.project_versions(project_id, mc_version=mc_version, loader=loader)
            self.after(0, self._populate_mod_versions)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur réseau", str(e)))

    def _populate_mod_versions(self):
        for w in self.mod_versions_scroll.inner.winfo_children():
            w.destroy()
        if not self.mod_versions:
            tk.Label(self.mod_versions_scroll.inner, text="Aucune version compatible.", bg=BG_CARD,
                     fg=TEXT_MUTED, font=font(9), wraplength=260, justify="left").pack(pady=10)
            return
        for v in self.mod_versions:
            row = tk.Frame(self.mod_versions_scroll.inner, bg=BG_INPUT, cursor="hand2")
            row.pack(fill="x", pady=3)
            name = v.get("name") or v.get("version_number")
            gv = ", ".join(v.get("game_versions", []))
            tk.Label(row, text=name, bg=BG_INPUT, fg=TEXT_PRIMARY, font=font(9, "bold"),
                     anchor="w", padx=10, pady=6).pack(side="left", fill="x", expand=True)
            dl_btn = RoundedButton(row, "↓", command=lambda ver=v: self._download_mod_version(ver),
                                    bg=ACCENT, hover_bg=ACCENT_HOVER, width=34, height=28,
                                    radius=8, font_size=10)
            dl_btn.pack(side="right", padx=6, pady=3)
            tk.Label(row, text=gv, bg=BG_INPUT, fg=TEXT_MUTED, font=font(8)).pack(side="right", padx=4)

    def _download_mod_version(self, version):
        name = self.mods_instance_var.get()
        inst = self.cfg["instances"].get(name)
        if not inst:
            messagebox.showinfo("Info", "Choisis d'abord une instance cible.")
            return
        files = version.get("files", [])
        if not files:
            messagebox.showerror("Erreur", "Aucun fichier pour cette version.")
            return
        file_info = next((f for f in files if f.get("primary")), files[0])
        mods_dir = Path(inst["dir"]) / "mods"
        self.set_status(f"Téléchargement de {file_info['filename']}...")
        threading.Thread(target=self._download_mod_thread, args=(file_info, mods_dir), daemon=True).start()

    def _download_mod_thread(self, file_info, mods_dir):
        try:
            def cb(label, done, total):
                pct = done / total * 100 if total else 0
                self.after(0, lambda: self.progress.config(value=pct))

            ModrinthAPI.download_mod_file(file_info, mods_dir, progress_cb=cb)
            self.after(0, lambda: self.set_status(f"Mod installé : {file_info['filename']}"))
            self.after(0, lambda: self.progress.config(value=0))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur", str(e)))

    # =========================================================== Servers page
    def _build_servers_page(self):
        page = self.pages["servers"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 10))
        tk.Label(header, text="Serveurs locaux", bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=font(20, "bold")).pack(side="left")
        RoundedButton(header, "+ Nouveau serveur", command=self.create_server_dialog,
                      bg=BG_CARD, hover_bg=BG_CARD_HOVER, width=190, height=38,
                      font_size=10).pack(side="right")

        body = tk.Frame(page, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=30, pady=10)

        list_col = tk.Frame(body, bg=BG_DARK)
        list_col.pack(side="left", fill="both", expand=True)
        self.servers_scroll = ScrollableFrame(list_col, bg=BG_DARK)
        self.servers_scroll.pack(fill="both", expand=True)

        detail_col = tk.Frame(body, bg=BG_CARD, width=420)
        detail_col.pack(side="left", fill="y", padx=(20, 0))
        detail_col.pack_propagate(False)
        inner = tk.Frame(detail_col, bg=BG_CARD, padx=20, pady=20)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="DÉTAILS", bg=BG_CARD, fg=TEXT_MUTED, font=font(9, "bold")).pack(anchor="w")
        self.server_name_label = tk.Label(inner, text="Aucun serveur sélectionné", bg=BG_CARD,
                                           fg=TEXT_PRIMARY, font=font(14, "bold"), wraplength=370, justify="left")
        self.server_name_label.pack(anchor="w", pady=(4, 8))
        self.server_meta_label = tk.Label(inner, text="", bg=BG_CARD, fg=TEXT_SECONDARY,
                                           font=font(9), justify="left")
        self.server_meta_label.pack(anchor="w")

        btn_row = tk.Frame(inner, bg=BG_CARD)
        btn_row.pack(fill="x", pady=(12, 4))
        self.server_start_btn = RoundedButton(btn_row, "▶ Démarrer", command=self.start_server,
                                               bg=ACCENT, hover_bg=ACCENT_HOVER, width=170, height=38, font_size=10)
        self.server_start_btn.pack(side="left")
        self.server_stop_btn = RoundedButton(btn_row, "■ Arrêter", command=self.stop_server,
                                              bg=BG_INPUT, hover_bg=DANGER, width=170, height=38, font_size=10)
        self.server_stop_btn.pack(side="left", padx=8)
        self.server_stop_btn.set_enabled(False)

        RoundedButton(inner, "Supprimer le serveur", command=self.delete_server,
                      bg=BG_INPUT, hover_bg=DANGER, width=350, height=34, font_size=9).pack(pady=(4, 10))

        tk.Label(inner, text="CONSOLE", bg=BG_CARD, fg=TEXT_MUTED, font=font(9, "bold")).pack(anchor="w", pady=(6, 4))
        self.server_console = tk.Text(inner, height=16, wrap="word", state="disabled", bg="#0a0a0d",
                                       fg=SUCCESS, insertbackground=SUCCESS, relief="flat", font=("Consolas", 9))
        self.server_console.pack(fill="both", expand=True)

        cmd_row = tk.Frame(inner, bg=BG_CARD)
        cmd_row.pack(fill="x", pady=(8, 0))
        self.server_command_var = tk.StringVar()
        cmd_entry = tk.Entry(cmd_row, textvariable=self.server_command_var, bg=BG_INPUT, fg=TEXT_PRIMARY,
                              insertbackground=TEXT_PRIMARY, relief="flat", font=font(9))
        cmd_entry.pack(side="left", fill="x", expand=True, ipady=5)
        cmd_entry.bind("<Return>", lambda e: self.send_server_command())
        RoundedButton(cmd_row, "Envoyer", command=self.send_server_command, bg=BG_INPUT, hover_bg=ACCENT,
                      width=90, height=30, font_size=9).pack(side="left", padx=(6, 0))

        self._selected_server_name_value = None

    def refresh_server_list(self):
        for w in self.servers_scroll.inner.winfo_children():
            w.destroy()
        for name, srv in self.cfg["servers"].items():
            self._make_server_card(name, srv)
        if not self.cfg["servers"]:
            tk.Label(self.servers_scroll.inner, text="Aucun serveur. Clique sur « + Nouveau serveur ».",
                     bg=BG_DARK, fg=TEXT_MUTED, font=font(10)).pack(pady=30)

    def _make_server_card(self, name, srv):
        selected = name == self._selected_server_name_value
        running = name in self.server_procs and self.server_procs[name].poll() is None
        card = tk.Frame(self.servers_scroll.inner, bg=BG_CARD if not selected else BG_CARD_HOVER, cursor="hand2")
        card.pack(fill="x", pady=6)
        strip_color = SUCCESS if running else (ACCENT if selected else BORDER)
        tk.Frame(card, bg=strip_color, width=4).pack(side="left", fill="y")
        inner = tk.Frame(card, bg=card["bg"], padx=16, pady=12)
        inner.pack(side="left", fill="both", expand=True)

        title_row = tk.Frame(inner, bg=card["bg"])
        title_row.pack(fill="x", anchor="w")
        tk.Label(title_row, text=name, bg=card["bg"], fg=TEXT_PRIMARY, font=font(12, "bold")).pack(side="left")
        Badge(title_row, "en ligne" if running else "arrêté", bg=SUCCESS if running else TEXT_MUTED).pack(side="left", padx=8)

        tk.Label(inner, text=f"Minecraft {srv['version']}  ·  port {srv.get('port', 25565)}",
                 bg=card["bg"], fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", pady=(4, 0))

        def select(_e=None):
            self._selected_server_name_value = name
            self.refresh_server_list()
            self._update_server_details(name, srv)

        for w in (card, inner, title_row) + tuple(inner.winfo_children()) + tuple(title_row.winfo_children()):
            w.bind("<Button-1>", select)

    def _selected_server_name(self):
        return self._selected_server_name_value

    def _update_server_details(self, name, srv):
        self.server_name_label.config(text=name)
        running = name in self.server_procs and self.server_procs[name].poll() is None
        ip = get_local_ip()
        status = "🟢 En ligne" if running else "⚪ Arrêté"
        self.server_meta_label.config(
            text=f"{status}\nVersion : {srv['version']}\nPort : {srv.get('port', 25565)}\n"
                 f"Adresse LAN à partager : {ip}:{srv.get('port', 25565)}\nDossier : {srv['dir']}"
        )
        self.server_start_btn.set_enabled(not running)
        self.server_stop_btn.set_enabled(running)
        self._refresh_server_console()

    def create_server_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Nouveau serveur")
        dialog.geometry("440x520")
        dialog.configure(bg=BG_DARK)
        dialog.grab_set()
        pad = dict(padx=18)

        tk.Label(dialog, text="Nom du serveur", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", **pad, pady=(16, 2))
        name_var = tk.StringVar()
        tk.Entry(dialog, textvariable=name_var, bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                 relief="flat", font=font(11)).pack(fill="x", **pad, ipady=6)

        tk.Label(dialog, text="Version Minecraft", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w", **pad, pady=(12, 2))
        version_var = tk.StringVar()
        version_combo = ttk.Combobox(dialog, textvariable=version_var, state="readonly")
        version_combo.pack(fill="x", **pad)

        def populate_versions():
            try:
                versions = MojangAPI.release_versions()
            except Exception as e:
                messagebox.showerror("Erreur réseau", str(e))
                return
            ids = [v["id"] for v in versions]
            version_combo["values"] = ids
            if ids:
                version_var.set(ids[0])

        threading.Thread(target=populate_versions, daemon=True).start()

        row1 = tk.Frame(dialog, bg=BG_DARK)
        row1.pack(fill="x", **pad, pady=(12, 0))
        tk.Label(row1, text="Port", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w")
        port_var = tk.StringVar(value="25565")
        tk.Entry(row1, textvariable=port_var, bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                 relief="flat", font=font(10)).pack(fill="x", ipady=5)

        row2 = tk.Frame(dialog, bg=BG_DARK)
        row2.pack(fill="x", **pad, pady=(12, 0))
        tk.Label(row2, text="Mode de jeu", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w")
        gamemode_var = tk.StringVar(value="survival")
        ttk.Combobox(row2, textvariable=gamemode_var, state="readonly",
                     values=["survival", "creative", "adventure", "spectator"]).pack(fill="x")

        row3 = tk.Frame(dialog, bg=BG_DARK)
        row3.pack(fill="x", **pad, pady=(12, 0))
        tk.Label(row3, text="Difficulté", bg=BG_DARK, fg=TEXT_SECONDARY, font=font(9)).pack(anchor="w")
        difficulty_var = tk.StringVar(value="normal")
        ttk.Combobox(row3, textvariable=difficulty_var, state="readonly",
                     values=["peaceful", "easy", "normal", "hard"]).pack(fill="x")

        eula_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dialog, text="J'accepte l'EULA de Mojang (eula.mojang.com)", variable=eula_var,
                       bg=BG_DARK, fg=TEXT_SECONDARY, selectcolor=BG_INPUT, activebackground=BG_DARK,
                       font=font(9)).pack(anchor="w", **pad, pady=(16, 0))

        note = ("Le serveur tournera sur ce PC. Tes amis sur le même réseau (WiFi/LAN)\n"
                "pourront le rejoindre avec l'adresse IP locale affichée après création.\n"
                "Pour jouer via Internet, une redirection de port sur ta box est nécessaire.")
        tk.Label(dialog, text=note, bg=BG_DARK, fg=TEXT_MUTED, font=font(8), justify="left").pack(anchor="w", **pad, pady=(10, 0))

        def confirm():
            name = name_var.get().strip()
            version = version_var.get().strip()
            if not name or not version:
                messagebox.showinfo("Info", "Renseigne un nom et une version.")
                return
            if not eula_var.get():
                messagebox.showinfo("EULA requise", "Tu dois accepter l'EULA de Mojang pour héberger un serveur.")
                return
            if name in self.cfg["servers"]:
                messagebox.showerror("Erreur", "Ce nom de serveur existe déjà.")
                return
            try:
                port = int(port_var.get().strip() or "25565")
            except ValueError:
                port = 25565
            server_dir = SERVERS_DIR / name
            self.cfg["servers"][name] = {
                "version": version,
                "dir": str(server_dir),
                "port": port,
                "gamemode": gamemode_var.get(),
                "difficulty": difficulty_var.get(),
                "java_path": None,
                "installed": False,
            }
            save_config(self.cfg)
            self.refresh_server_list()
            dialog.destroy()
            self.set_status(f"Serveur '{name}' créé. Installation en cours...")
            self._install_server(name, self.cfg["servers"][name])

        RoundedButton(dialog, "Créer le serveur", command=confirm, bg=ACCENT, hover_bg=ACCENT_HOVER,
                      width=200, height=42, font_size=11).pack(pady=18)

    def _install_server(self, name, srv):
        threading.Thread(target=self._install_server_thread, args=(name, srv), daemon=True).start()

    def _install_server_thread(self, name, srv):
        try:
            def cb(label, done, total):
                pct = (done / total) * 100 if total else 0
                self.after(0, lambda: self.set_status(f"{label} ({done}/{total})"))
                self.after(0, lambda: self.progress.config(value=pct))

            properties = {"server-port": srv["port"], "gamemode": srv["gamemode"], "difficulty": srv["difficulty"]}
            java_path = ServerManager.install(srv["version"], Path(srv["dir"]), properties, progress_cb=cb)
            srv["java_path"] = java_path
            srv["installed"] = True
            save_config(self.cfg)
            self.after(0, lambda: self.progress.config(value=100))
            self.after(0, lambda: self.set_status(f"Serveur '{name}' prêt."))
            self.after(0, self.refresh_server_list)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Erreur d'installation", str(e)))
        finally:
            self.after(0, lambda: self.progress.config(value=0))

    def start_server(self):
        name = self._selected_server_name()
        if not name:
            messagebox.showinfo("Info", "Sélectionne un serveur.")
            return
        srv = self.cfg["servers"][name]
        if not srv.get("installed"):
            messagebox.showinfo("Info", "Ce serveur n'est pas encore installé, patiente ou relance sa création.")
            return
        if name in self.server_procs and self.server_procs[name].poll() is None:
            messagebox.showinfo("Info", "Ce serveur tourne déjà.")
            return

        self.server_logs.setdefault(name, [])
        min_ram = self.cfg.get("min_ram", 1)
        max_ram = self.cfg.get("max_ram", 4)
        java_path = srv.get("java_path") or self.cfg.get("java_path", "java")

        def log(line):
            lines = self.server_logs.setdefault(name, [])
            lines.append(line)
            if len(lines) > 2000:
                del lines[:500]
            if self._selected_server_name() == name:
                self.after(0, self._refresh_server_console)

        def run():
            proc = ServerManager.start(Path(srv["dir"]), java_path, min_ram, max_ram, log_cb=log)
            self.server_procs[name] = proc

            # Présence Discord : "héberge un serveur"
            self.after(0, lambda: DiscordPresence.set_hosting())
            self.after(0, lambda: self._update_server_details(name, srv))
            self.after(0, self.refresh_server_list)

            for line in proc.stdout:
                log(line.rstrip())
            log(f"=== Serveur arrêté (code retour : {proc.returncode}) ===")

            self.after(0, lambda: DiscordPresence.set_idle())  # Retour à l'état idle
            self.after(0, lambda: self._update_server_details(name, srv))
            self.after(0, self.refresh_server_list)

        threading.Thread(target=run, daemon=True).start()
        self.set_status(f"Démarrage du serveur '{name}'...")

    def stop_server(self):
        name = self._selected_server_name()
        if not name or name not in self.server_procs:
            return
        proc = self.server_procs[name]

        # Présence Discord : retour à l'état idle pendant l'arrêt
        self.after(0, lambda: DiscordPresence.set_idle())

        self.set_status(f"Arrêt du serveur '{name}'...")
        threading.Thread(target=lambda: ServerManager.stop(proc), daemon=True).start()

    def send_server_command(self):
        name = self._selected_server_name()
        if not name or name not in self.server_procs:
            return
        command = self.server_command_var.get().strip()
        if not command:
            return
        ServerManager.send_command(self.server_procs[name], command)
        self.server_command_var.set("")

    def delete_server(self):
        name = self._selected_server_name()
        if not name:
            return
        if name in self.server_procs and self.server_procs[name].poll() is None:
            messagebox.showinfo("Info", "Arrête le serveur avant de le supprimer.")
            return
        if messagebox.askyesno("Confirmer", f"Supprimer le serveur '{name}' (config uniquement, les fichiers restent sur le disque) ?"):
            del self.cfg["servers"][name]
            save_config(self.cfg)
            self._selected_server_name_value = None
            self.refresh_server_list()

    def _refresh_server_console(self):
        name = self._selected_server_name()
        self.server_console.config(state="normal")
        self.server_console.delete("1.0", "end")
        if name:
            lines = self.server_logs.get(name, [])
            self.server_console.insert("1.0", "\n".join(lines[-500:]))
            self.server_console.see("end")
        self.server_console.config(state="disabled")

    # ========================================================= Accounts page
    def _build_accounts_page(self):
        page = self.pages["accounts"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 10))
        tk.Label(header, text="Comptes", bg=BG_DARK, fg=TEXT_PRIMARY, font=font(20, "bold")).pack(side="left")
        RoundedButton(header, "+ Ajouter (hors-ligne)", command=self.add_account_dialog,
                      bg=ACCENT, hover_bg=ACCENT_HOVER, width=210, height=38, font_size=10).pack(side="right")

        note = ("Compte hors-ligne : fonctionne en solo et sur les serveurs configurés en\n"
                "« online-mode=false ». Le multijoueur premium officiel nécessiterait une\n"
                "authentification Microsoft/Xbox Live (non incluse). Utilise ce launcher\n"
                "avec un jeu que tu possèdes légalement.")
        tk.Label(page, text=note, bg=BG_DARK, fg=TEXT_MUTED, font=font(9), justify="left").pack(
            anchor="w", padx=30, pady=(0, 14))

        self.accounts_scroll = ScrollableFrame(page, bg=BG_DARK)
        self.accounts_scroll.pack(fill="both", expand=True, padx=30, pady=(0, 20))

    def refresh_account_list(self):
        for w in self.accounts_scroll.inner.winfo_children():
            w.destroy()
        for a in self.cfg["accounts"]:
            self._make_account_card(a)
        if not self.cfg["accounts"]:
            tk.Label(self.accounts_scroll.inner, text="Aucun compte. Clique sur « + Ajouter ».",
                     bg=BG_DARK, fg=TEXT_MUTED, font=font(10)).pack(pady=30)
        self._refresh_sidebar_profile()

    def _make_account_card(self, account):
        is_active = account["username"] == self.cfg.get("active_account")
        card = tk.Frame(self.accounts_scroll.inner, bg=BG_CARD_HOVER if is_active else BG_CARD)
        card.pack(fill="x", pady=6)
        inner = tk.Frame(card, bg=card["bg"], padx=16, pady=12)
        inner.pack(fill="x")

        Avatar(inner, account["username"][0], size=38, bg=ACCENT).pack(side="left")
        text_col = tk.Frame(inner, bg=card["bg"])
        text_col.pack(side="left", padx=12, fill="x", expand=True)
        row = tk.Frame(text_col, bg=card["bg"])
        row.pack(anchor="w", fill="x")
        tk.Label(row, text=account["username"], bg=card["bg"], fg=TEXT_PRIMARY, font=font(12, "bold")).pack(side="left")
        if is_active:
            Badge(row, "actif", bg=SUCCESS).pack(side="left", padx=8)
        tk.Label(text_col, text=account["uuid"], bg=card["bg"], fg=TEXT_MUTED, font=font(8)).pack(anchor="w")

        btns = tk.Frame(inner, bg=card["bg"])
        btns.pack(side="right")
        RoundedButton(btns, "Activer", command=lambda: self.set_active_account(account["username"]),
                      bg=BG_INPUT, hover_bg=ACCENT, width=90, height=30, font_size=9).pack(side="left", padx=4)
        RoundedButton(btns, "Suppr.", command=lambda: self.remove_account(account["username"]),
                      bg=BG_INPUT, hover_bg=DANGER, width=80, height=30, font_size=9).pack(side="left")

    def add_account_dialog(self):
        username = simpledialog.askstring("Nouveau compte", "Pseudo (hors-ligne) :")
        if not username:
            return
        username = username.strip()
        if any(a["username"] == username for a in self.cfg["accounts"]):
            messagebox.showerror("Erreur", "Ce pseudo existe déjà.")
            return
        self.cfg["accounts"].append({"username": username, "uuid": offline_uuid(username)})
        if not self.cfg.get("active_account"):
            self.cfg["active_account"] = username
        save_config(self.cfg)
        self.refresh_account_list()

    def set_active_account(self, username):
        self.cfg["active_account"] = username
        save_config(self.cfg)
        self.refresh_account_list()

    def remove_account(self, username):
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a["username"] != username]
        if self.cfg.get("active_account") == username:
            self.cfg["active_account"] = None
        save_config(self.cfg)
        self.refresh_account_list()

    # ========================================================= Settings page
    def _build_settings_page(self):
        page = self.pages["settings"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 20))
        tk.Label(header, text="Paramètres", bg=BG_DARK, fg=TEXT_PRIMARY, font=font(20, "bold")).pack(side="left")

        card = tk.Frame(page, bg=BG_CARD, padx=24, pady=24)
        card.pack(fill="x", padx=30)
        card.grid_columnconfigure(0, weight=1)

        tk.Label(card, text="Chemin de l'exécutable Java", bg=BG_CARD, fg=TEXT_SECONDARY, font=font(9)).grid(row=0, column=0, sticky="w")
        self.java_path_var = tk.StringVar(value=self.cfg.get("java_path", "java"))
        tk.Entry(card, textvariable=self.java_path_var, bg=BG_INPUT, fg=TEXT_PRIMARY,
                 insertbackground=TEXT_PRIMARY, relief="flat", font=font(10)).grid(row=1, column=0, sticky="ew", ipady=6, pady=(2, 14))

        tk.Label(card, text="RAM minimum (Go)", bg=BG_CARD, fg=TEXT_SECONDARY, font=font(9)).grid(row=2, column=0, sticky="w")
        self.min_ram_var = tk.IntVar(value=self.cfg.get("min_ram", 1))
        tk.Spinbox(card, from_=1, to=32, textvariable=self.min_ram_var, width=10, bg=BG_INPUT, fg=TEXT_PRIMARY,
                   relief="flat", buttonbackground=BG_INPUT).grid(row=3, column=0, sticky="w", pady=(2, 14))

        tk.Label(card, text="RAM maximum (Go)", bg=BG_CARD, fg=TEXT_SECONDARY, font=font(9)).grid(row=4, column=0, sticky="w")
        self.max_ram_var = tk.IntVar(value=self.cfg.get("max_ram", 4))
        tk.Spinbox(card, from_=1, to=64, textvariable=self.max_ram_var, width=10, bg=BG_INPUT, fg=TEXT_PRIMARY,
                   relief="flat", buttonbackground=BG_INPUT).grid(row=5, column=0, sticky="w", pady=(2, 14))

        tk.Label(card, text=f"Dossier de données : {APP_DIR}", bg=BG_CARD, fg=TEXT_MUTED, font=font(8)).grid(
            row=6, column=0, sticky="w", pady=(10, 0))

        RoundedButton(card, "Enregistrer", command=self.save_settings, bg=ACCENT, hover_bg=ACCENT_HOVER,
                      width=160, height=38, font_size=10).grid(row=7, column=0, sticky="w", pady=(20, 0))

        tk.Frame(card, bg=BORDER, height=1).grid(row=8, column=0, sticky="ew", pady=18)

        tk.Label(card, text="Diagnostic Java", bg=BG_CARD, fg=TEXT_SECONDARY, font=font(9, "bold")).grid(
            row=9, column=0, sticky="w")
        self.java_check_label = tk.Label(card, text="Clique sur « Vérifier Java » pour voir la version/architecture détectée.",
                                          bg=BG_CARD, fg=TEXT_MUTED, font=font(9), justify="left", wraplength=500)
        self.java_check_label.grid(row=10, column=0, sticky="w", pady=(4, 10))
        RoundedButton(card, "Vérifier Java", command=self.check_java_version, bg=BG_INPUT, hover_bg=BG_CARD_HOVER,
                      width=160, height=36, font_size=10).grid(row=11, column=0, sticky="w")

    def check_java_version(self):
        java_path = self.java_path_var.get().strip() or "java"
        self.java_check_label.config(text="Vérification en cours...", fg=TEXT_MUTED)
        threading.Thread(target=self._check_java_thread, args=(java_path,), daemon=True).start()

    def _check_java_thread(self, java_path):
        output, is_64bit = core.check_java(java_path)
        if is_64bit is True:
            prefix = "✓ Java 64 bits détecté.\n"
            color = SUCCESS
        elif is_64bit is False:
            prefix = ("⚠ Java 32 BITS détecté ! C'est très probablement la cause de l'erreur "
                      "\"Could not create the Java Virtual Machine\". Un Java 32 bits ne peut pas "
                      "allouer autant de RAM (ex: 4 Go). Installe un Java 64 bits (Temurin/Adoptium) "
                      "et mets à jour le chemin ci-dessus, ou réduis fortement la RAM en dessous.\n\n")
            color = DANGER
        else:
            prefix = ""
            color = WARNING
        self.after(0, lambda: self.java_check_label.config(text=prefix + output, fg=color))

    def save_settings(self):
        self.cfg["java_path"] = self.java_path_var.get().strip() or "java"
        self.cfg["min_ram"] = int(self.min_ram_var.get())
        self.cfg["max_ram"] = int(self.max_ram_var.get())
        save_config(self.cfg)
        messagebox.showinfo("OK", "Paramètres enregistrés.")

    # ============================================================= Logs page
    def _build_logs_page(self):
        page = self.pages["logs"]
        header = tk.Frame(page, bg=BG_DARK)
        header.pack(fill="x", padx=30, pady=(26, 10))
        tk.Label(header, text="Logs", bg=BG_DARK, fg=TEXT_PRIMARY, font=font(20, "bold")).pack(side="left")

        frame = tk.Frame(page, bg=BG_DARK)
        frame.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        self.log_text = tk.Text(frame, state="disabled", wrap="word", bg="#0a0a0d", fg=SUCCESS,
                                 insertbackground=SUCCESS, relief="flat", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)

    def _append_log(self, line):
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ==================================================================== Misc
    def set_status(self, text):
        self.status_var.set(text)


def main():
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()

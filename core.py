"""
core.py — Logique métier du launcher Minecraft.

Contient :
- Gestion des chemins / configuration (JSON local)
- MojangAPI : manifest des versions officielles, installation (client jar,
  libraries, natives, assets) via l'API publique de Mojang (piston-meta)
- FabricAPI : installation du mod loader Fabric via l'API publique Fabric
- ForgeAPI : installation du mod loader Forge via portablemc
- ModrinthAPI : recherche et téléchargement de mods via l'API publique Modrinth
- LaunchManager : construction de la commande Java et lancement du jeu

Toutes les API utilisées ici sont publiques et gratuites, sans clé requise :
- https://piston-meta.mojang.com
- https://resources.download.minecraft.net
- https://meta.fabricmc.net
- https://api.modrinth.com

Note légale : ce launcher télécharge les fichiers officiels du jeu distribués
publiquement par Mojang (comme le font des launchers open source connus).
Il propose un mode "compte hors-ligne" (offline/cracked-style, UUID dérivé du
pseudo) qui fonctionne pour le solo et les serveurs configurés en
`online-mode=false`. Jouer sur les serveurs officiels / multijoueur premium
nécessite un compte Microsoft possédant une licence Minecraft valide et une
authentification Xbox Live (OAuth), non incluse ici car elle nécessite
l'enregistrement d'une application Azure personnelle. Voir README.
"""

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HEADERS = {"User-Agent": "PyMCLauncher/1.0 (contact: example@example.com)"}

# Session HTTP partagée : réutilise les connexions TCP/TLS au lieu d'en
# rouvrir une par fichier. Sans ça, télécharger des dizaines de milliers de
# petits fichiers (assets) en parallèle fait refaire une négociation TLS à
# chaque fois -> gros pic de charge CPU (et de chaleur) pour rien.
_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=2)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_session.headers.update(HEADERS)

# ---------------------------------------------------------------------------
# Chemins & configuration
# ---------------------------------------------------------------------------

APP_DIR = Path.home() / ".pymc_launcher"
INSTANCES_DIR = APP_DIR / "instances"
SERVERS_DIR = APP_DIR / "servers"          # serveurs locaux hébergés
LIBRARIES_DIR = APP_DIR / "libraries"      # librairies partagées entre instances
ASSETS_DIR = APP_DIR / "assets"            # assets partagés entre instances
VERSIONS_DIR = APP_DIR / "versions"        # jars/json des versions vanilla
CONFIG_FILE = APP_DIR / "config.json"

for d in (APP_DIR, INSTANCES_DIR, SERVERS_DIR, LIBRARIES_DIR, ASSETS_DIR, VERSIONS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.setdefault("servers", {})
            return cfg
        except Exception:
            pass
    return {
        "instances": {},     # nom -> {version, loader, loader_version, dir}
        "servers": {},        # nom -> {version, dir, port, java_path, ...}
        "accounts": [],       # [{username, uuid}]
        "active_account": None,
        "java_path": shutil.which("javaw") or shutil.which("java") or "java",
        "min_ram": 1,
        "max_ram": 4,
    }


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Utilitaires système / téléchargement
# ---------------------------------------------------------------------------

def os_name():
    s = platform.system()
    if s == "Windows":
        return "windows"
    if s == "Darwin":
        return "osx"
    return "linux"


def os_arch():
    machine = platform.machine().lower()
    if "64" in machine or "amd64" in machine or "x86_64" in machine:
        return "64"
    return "32"


def os_arch_name():
    """Nom d'architecture au format utilisé par les rules Mojang ('x86', 'arm64'...)."""
    machine = platform.machine().lower()
    if "aarch64" in machine or "arm64" in machine:
        return "arm64"
    if "arm" in machine:
        return "arm"
    if machine in ("i386", "i686", "x86"):
        return "x86"
    return "x64"


def rule_allows(rules):
    """Évalue une liste de rules Mojang (allow/disallow selon l'OS ET l'architecture)."""
    if not rules:
        return True
    allowed = False
    for rule in rules:
        action = rule.get("action") == "allow"
        os_rule = rule.get("os")
        if os_rule:
            name = os_rule.get("name")
            arch = os_rule.get("arch")
            name_ok = name is None or name == os_name()
            arch_ok = arch is None or arch == os_arch_name()
            if name_ok and arch_ok:
                allowed = action
        else:
            allowed = action
    return allowed


def download_file(url, dest: Path, progress_cb=None, label=""):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    with _session.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(label, done, total)
        tmp.rename(dest)


def offline_uuid(username: str) -> str:
    """Reproduit UUID.nameUUIDFromBytes("OfflinePlayer:<name>") de Java."""
    data = f"OfflinePlayer:{username}".encode("utf-8")
    digest = bytearray(hashlib.md5(data).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def check_java(java_path):
    """Exécute `java -version` et retourne la sortie brute (version + architecture)."""
    try:
        result = subprocess.run([java_path, "-version"], capture_output=True, text=True, timeout=10)
        output = (result.stderr or "") + (result.stdout or "")
        output = output.strip()
        if not output:
            return "Aucune sortie reçue — vérifie le chemin de l'exécutable.", None
        is_64bit = "64-Bit" in output or "64-bit" in output
        return output, is_64bit
    except FileNotFoundError:
        return f"Introuvable : '{java_path}'. Vérifie le chemin.", None
    except Exception as e:
        return f"Erreur : {e}", None


# ---------------------------------------------------------------------------
# API Mojang
# ---------------------------------------------------------------------------

def runtime_platform_key():
    """Clé de plateforme utilisée par le manifest des runtimes Java de Mojang."""
    s = os_name()
    arch = os_arch_name()
    if s == "windows":
        if arch == "arm64":
            return "windows-arm64"
        if arch == "x86":
            return "windows-x86"
        return "windows-x64"
    if s == "osx":
        return "mac-os-arm64" if arch == "arm64" else "mac-os"
    return "linux-i386" if arch == "x86" else "linux"


class JavaRuntimeAPI:
    """Télécharge le runtime Java officiel de Mojang correspondant à une version
    de Minecraft (comme le fait le launcher officiel), pour éviter tout souci
    de compatibilité avec un Java installé manuellement par l'utilisateur."""

    ALL_URL = "https://piston-meta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
    RUNTIMES_DIR = APP_DIR / "runtimes"

    _manifest_cache = None

    @classmethod
    def get_manifest(cls):
        if cls._manifest_cache is None:
            resp = _session.get(cls.ALL_URL, timeout=15)
            resp.raise_for_status()
            cls._manifest_cache = resp.json()
        return cls._manifest_cache

    @classmethod
    def java_executable_path(cls, component):
        base = cls.RUNTIMES_DIR / component
        if os_name() == "windows":
            return base / "bin" / "javaw.exe"
        if os_name() == "osx":
            candidate = base / "jre.bundle" / "Contents" / "Home" / "bin" / "java"
            return candidate if candidate.exists() else base / "bin" / "java"
        return base / "bin" / "java"

    @classmethod
    def install(cls, component, progress_cb=None):
        """Télécharge le runtime `component` (ex: 'java-runtime-gamma') s'il n'est
        pas déjà installé. Retourne le chemin de l'exécutable java à utiliser."""
        java_exe = cls.java_executable_path(component)
        if java_exe.exists():
            return java_exe

        manifest = cls.get_manifest()
        platform_key = runtime_platform_key()
        entries = manifest.get(platform_key, {}).get(component, [])
        if not entries:
            raise RuntimeError(
                f"Aucun runtime Java officiel '{component}' disponible pour '{platform_key}'. "
                "Utilise le Java installé sur ton système (onglet Paramètres)."
            )
        manifest_info = entries[0]["manifest"]
        resp = _session.get(manifest_info["url"], timeout=15)
        resp.raise_for_status()
        files_manifest = resp.json().get("files", {})

        base_dir = cls.RUNTIMES_DIR / component
        items = [(rel, info) for rel, info in files_manifest.items() if info.get("type") == "file"]

        if progress_cb:
            progress_cb(f"Téléchargement du runtime Java ({component})...", 0, len(items) or 1)

        def _get_one(item):
            rel, info = item
            dest = base_dir / rel
            raw = info["downloads"]["raw"]
            download_file(raw["url"], dest)
            if info.get("executable") and os_name() != "windows":
                try:
                    os.chmod(dest, 0o755)
                except OSError:
                    pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_get_one, item): item for item in items}
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if progress_cb:
                    progress_cb(f"Téléchargement du runtime Java ({component})...", done, len(items) or 1)

        return cls.java_executable_path(component)


class MojangAPI:
    MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

    _manifest_cache = None

    @classmethod
    def get_manifest(cls):
        if cls._manifest_cache is None:
            resp = _session.get(cls.MANIFEST_URL, timeout=15)
            resp.raise_for_status()
            cls._manifest_cache = resp.json()
        return cls._manifest_cache

    @classmethod
    def get_version_entry(cls, version_id):
        for v in cls.get_manifest()["versions"]:
            if v["id"] == version_id:
                return v
        raise ValueError(f"Version inconnue : {version_id}")

    @classmethod
    def get_version_json(cls, version_id):
        cached = VERSIONS_DIR / version_id / f"{version_id}.json"
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        entry = cls.get_version_entry(version_id)
        resp = _session.get(entry["url"], timeout=15)
        resp.raise_for_status()
        data = resp.json()
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data), encoding="utf-8")
        return data

    @classmethod
    def install_version(cls, version_id, progress_cb=None):
        """Installe le jar client, les libraries, les natives et les assets.
        Partagé entre toutes les instances utilisant cette version."""
        vjson = cls.get_version_json(version_id)
        vdir = VERSIONS_DIR / version_id
        vdir.mkdir(parents=True, exist_ok=True)

        # 1. Client jar
        client_jar = vdir / f"{version_id}.jar"
        if progress_cb:
            progress_cb("Téléchargement du client Minecraft...", 0, 1)
        download_file(vjson["downloads"]["client"]["url"], client_jar)

        # 2. Libraries (+ natives)
        natives_dir = vdir / "natives"
        natives_dir.mkdir(exist_ok=True)
        libs_to_get = []
        for lib in vjson.get("libraries", []):
            if not rule_allows(lib.get("rules")):
                continue
            downloads = lib.get("downloads", {})
            artifact = downloads.get("artifact")
            if artifact:
                path = LIBRARIES_DIR / artifact["path"]
                libs_to_get.append((artifact["url"], path, None))
            classifiers = downloads.get("classifiers")
            if classifiers:
                natives_key = None
                natives_map = lib.get("natives", {})
                if natives_map:
                    key = natives_map.get(os_name())
                    if key:
                        natives_key = key.replace("${arch}", os_arch())
                if natives_key and natives_key in classifiers:
                    art = classifiers[natives_key]
                    path = LIBRARIES_DIR / art["path"]
                    libs_to_get.append((art["url"], path, lib.get("extract", {})))

        def _get_lib(item):
            url, path, extract_rule = item
            download_file(url, path)
            if extract_rule is not None:
                exclude = extract_rule.get("exclude", [])
                with zipfile.ZipFile(path) as zf:
                    for member in zf.namelist():
                        if any(member.startswith(ex) for ex in exclude):
                            continue
                        zf.extract(member, natives_dir)

        if progress_cb:
            progress_cb("Téléchargement des librairies...", 0, len(libs_to_get) or 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_get_lib, item): item for item in libs_to_get}
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if progress_cb:
                    progress_cb("Téléchargement des librairies...", done, len(libs_to_get) or 1)

        # 3. Assets
        asset_index = vjson["assetIndex"]
        index_path = ASSETS_DIR / "indexes" / f"{asset_index['id']}.json"
        download_file(asset_index["url"], index_path)
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        objects = index_data.get("objects", {})

        def _get_asset(item):
            name, info = item
            h = info["hash"]
            sub = h[:2]
            dest = ASSETS_DIR / "objects" / sub / h
            if dest.exists() and dest.stat().st_size == info.get("size", -1):
                return
            url = f"https://resources.download.minecraft.net/{sub}/{h}"
            download_file(url, dest)

        items = list(objects.items())
        if progress_cb:
            progress_cb("Téléchargement des assets (sons/textures)...", 0, len(items) or 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_get_asset, item): item for item in items}
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if progress_cb and done % 25 == 0:
                    progress_cb("Téléchargement des assets (sons/textures)...", done, len(items) or 1)
        if progress_cb:
            progress_cb("Téléchargement des assets (sons/textures)...", len(items), len(items) or 1)

        return vjson

    @classmethod
    def release_versions(cls):
        return [v for v in cls.get_manifest()["versions"] if v["type"] == "release"]

    @classmethod
    def all_versions(cls):
        return cls.get_manifest()["versions"]


# ---------------------------------------------------------------------------
# API Fabric (mod loader)
# ---------------------------------------------------------------------------

class FabricAPI:
    META = "https://meta.fabricmc.net/v2/versions"

    @classmethod
    def loader_versions(cls, mc_version):
        resp = _session.get(f"{cls.META}/loader/{mc_version}", timeout=15)
        resp.raise_for_status()
        return resp.json()  # liste de {"loader": {"version": ...}, ...}

    @classmethod
    def install(cls, mc_version, loader_version, progress_cb=None):
        """Retourne un dict fusionné : mainClass + libraries additionnelles Fabric."""
        url = f"{cls.META}/loader/{mc_version}/{loader_version}/profile/json"
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
        profile = resp.json()

        libs_to_get = []
        for lib in profile.get("libraries", []):
            name = lib["name"]  # groupId:artifactId:version
            group, artifact, version = name.split(":")
            rel_path = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.jar"
            base_url = lib.get("url", "https://maven.fabricmc.net/").rstrip("/") + "/"
            full_url = base_url + rel_path
            path = LIBRARIES_DIR / rel_path
            libs_to_get.append((full_url, path))

        if progress_cb:
            progress_cb("Installation de Fabric...", 0, len(libs_to_get) or 1)

        def _get(item):
            url, path = item
            download_file(url, path)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_get, item): item for item in libs_to_get}
            done = 0
            for fut in as_completed(futures):
                fut.result()
                done += 1
                if progress_cb:
                    progress_cb("Installation de Fabric...", done, len(libs_to_get) or 1)

        return {
            "mainClass": profile.get("mainClass", "net.fabricmc.loader.impl.launch.knot.KnotClient"),
            "libraries": [LIBRARIES_DIR / p for _, p in libs_to_get],
        }


# ---------------------------------------------------------------------------
# API Forge (mod loader) via portablemc
# ---------------------------------------------------------------------------

def install_forge(mc_version, instance_dir, progress_cb=None):
    """
    Installe Forge pour la version Minecraft donnée dans l'instance.
    Utilise portablemc pour gérer toute la complexité.
    """
    try:
        from portablemc.forge import find_forge_version, install_forge_version
        
        if progress_cb:
            progress_cb("Recherche de la version Forge compatible...", 0, 1)
        
        # Trouver la meilleure version de Forge pour cette version de Minecraft
        forge_versions = find_forge_version(mc_version)
        if not forge_versions:
            if progress_cb:
                progress_cb("Aucune version de Forge disponible pour cette version de Minecraft.", 0, 1)
            return False
        
        # Prendre la version recommandée (la plus récente)
        forge_version = forge_versions[-1]  # la dernière est la plus récente
        if progress_cb:
            progress_cb(f"Forge {forge_version} trouvé.", 0, 1)
        
        # Dossier Forge dans l'instance
        forge_dir = instance_dir / "forge"
        forge_dir.mkdir(parents=True, exist_ok=True)
        
        if progress_cb:
            progress_cb("Téléchargement et installation de Forge...", 0, 1)
        
        # Installer Forge (télécharge et installe tout)
        install_forge_version(
            mc_version=mc_version,
            forge_version=forge_version,
            path=str(forge_dir),
            progress_callback=progress_cb
        )
        
        if progress_cb:
            progress_cb(f"Forge installé avec succès !", 1, 1)
        
        return forge_version
        
    except ImportError:
        if progress_cb:
            progress_cb("portablemc n'est pas installé. Exécute : pip install portablemc", 0, 1)
        return False
    except Exception as e:
        if progress_cb:
            progress_cb(f"Erreur Forge : {e}", 0, 1)
        return False


def get_forge_versions(mc_version):
    """Récupère la liste des versions Forge disponibles pour une version Minecraft donnée."""
    try:
        from portablemc.forge import find_forge_version
        return find_forge_version(mc_version)
    except ImportError:
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# API Modrinth (mods)
# ---------------------------------------------------------------------------

class ModrinthAPI:
    BASE = "https://api.modrinth.com/v2"

    @classmethod
    def search(cls, query, mc_version=None, loader=None, limit=30, project_type="mod"):
        facets = [[f"project_type:{project_type}"]]
        if mc_version:
            facets.append([f"versions:{mc_version}"])
        if loader and loader != "vanilla":
            facets.append([f"categories:{loader}"])
        params = {"query": query, "facets": json.dumps(facets), "limit": limit}
        resp = _session.get(f"{cls.BASE}/search", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("hits", [])

    @classmethod
    def project_versions(cls, project_id, mc_version=None, loader=None):
        params = {}
        if mc_version:
            params["game_versions"] = json.dumps([mc_version])
        if loader and loader != "vanilla":
            params["loaders"] = json.dumps([loader])
        resp = _session.get(f"{cls.BASE}/project/{project_id}/version", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def download_mod_file(cls, file_info, dest_dir: Path, progress_cb=None):
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / file_info["filename"]
        download_file(file_info["url"], dest, progress_cb, label=file_info["filename"])
        return dest


# ---------------------------------------------------------------------------
# Lancement du jeu
# ---------------------------------------------------------------------------

class LaunchManager:

    @staticmethod
    def _classpath(vjson, extra_libs=None):
        parts = []
        for lib in vjson.get("libraries", []):
            if not rule_allows(lib.get("rules")):
                continue
            artifact = lib.get("downloads", {}).get("artifact")
            if artifact:
                parts.append(str(LIBRARIES_DIR / artifact["path"]))
        if extra_libs:
            parts.extend(str(p) for p in extra_libs)
        version_id = vjson["id"]
        parts.append(str(VERSIONS_DIR / version_id / f"{version_id}.jar"))
        sep = ";" if os_name() == "windows" else ":"
        return sep.join(parts)

    @staticmethod
    def _substitute(template, mapping):
        for key, val in mapping.items():
            template = template.replace("${" + key + "}", str(val))
        return template

    @classmethod
    def build_command(cls, instance, account, java_path, min_ram, max_ram):
        version_id = instance["version"]
        vjson = MojangAPI.get_version_json(version_id)
        main_class = vjson.get("mainClass", "net.minecraft.client.main.Main")
        extra_libs = []
        inst_dir = Path(instance["dir"])

        # --- Fabric ---
        if instance.get("loader") == "fabric" and instance.get("fabric_info"):
            main_class = instance["fabric_info"]["mainClass"]
            extra_libs = instance["fabric_info"]["libraries"]

        # --- Forge ---
        if instance.get("loader") == "forge":
            forge_dir = inst_dir / "forge"
            # Chercher le jar Forge client
            forge_jars = list(forge_dir.glob("forge-*-client.jar"))
            if forge_jars:
                # Ajouter le jar Forge au classpath
                extra_libs.append(str(forge_jars[0]))
                # mainClass reste le même que vanilla
            else:
                # Fallback : chercher dans versions
                forge_versions_dir = APP_DIR / "versions" / f"{version_id}-forge"
                if forge_versions_dir.exists():
                    forge_jars = list(forge_versions_dir.glob("*.jar"))
                    if forge_jars:
                        extra_libs.append(str(forge_jars[0]))

        inst_dir.mkdir(parents=True, exist_ok=True)
        (inst_dir / "mods").mkdir(exist_ok=True)

        natives_dir = VERSIONS_DIR / version_id / "natives"
        classpath = cls._classpath(vjson, extra_libs)

        mapping = {
            "auth_player_name": account["username"],
            "version_name": version_id,
            "game_directory": str(inst_dir),
            "assets_root": str(ASSETS_DIR),
            "assets_index_name": vjson["assetIndex"]["id"],
            "auth_uuid": account["uuid"],
            "auth_access_token": "0",
            "user_type": "legacy",
            "version_type": vjson.get("type", "release"),
            "natives_directory": str(natives_dir),
            "classpath": classpath,
            "launcher_name": "PyMCLauncher",
            "launcher_version": "1.0",
            "clientid": "-",
            "auth_xuid": "-",
        }

        game_args = []
        jvm_args = [f"-Xms{min_ram}G", f"-Xmx{max_ram}G", f"-Djava.library.path={natives_dir}"]

        if "arguments" in vjson:
            for a in vjson["arguments"].get("jvm", []):
                if isinstance(a, str):
                    jvm_args.append(cls._substitute(a, mapping))
                elif rule_allows(a.get("rules")):
                    val = a["value"]
                    vals = val if isinstance(val, list) else [val]
                    jvm_args.extend(cls._substitute(v, mapping) for v in vals)
            for a in vjson["arguments"].get("game", []):
                if isinstance(a, str):
                    game_args.append(cls._substitute(a, mapping))
                # arguments conditionnées par des "features" (résolution custom, demo...)
                # sont ignorées volontairement (valeurs par défaut).
        else:
            legacy = vjson.get("minecraftArguments", "")
            game_args = [cls._substitute(tok, mapping) for tok in legacy.split(" ") if tok]

        cmd = [java_path] + jvm_args + ["-cp", classpath, main_class] + game_args
        return cmd

    @classmethod
    def launch(cls, instance, account, java_path, min_ram, max_ram, log_cb=None):
        cmd = cls.build_command(instance, account, java_path, min_ram, max_ram)
        inst_dir = Path(instance["dir"])
        if log_cb:
            log_cb("=== Commande de lancement ===")
            log_cb(" ".join(cmd))
            log_cb("==============================")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(inst_dir),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError as e:
            if log_cb:
                log_cb(f"Impossible de démarrer Java ({java_path}) : {e}")
            raise RuntimeError(
                f"Impossible de trouver l'exécutable Java : '{java_path}'. "
                "Vérifie le chemin dans l'onglet Paramètres."
            ) from e
        if log_cb:
            for line in proc.stdout:
                log_cb(line.rstrip())
        proc.wait()
        if log_cb:
            log_cb(f"=== Minecraft/Java terminé (code retour : {proc.returncode}) ===")
        if proc.returncode not in (0, None) and proc.returncode != 0:
            # Code retour non nul dès le début = échec probable au démarrage
            # (mauvaise JVM, RAM invalide, java 32 bits, etc.) plutôt qu'une
            # fermeture normale du jeu.
            pass
        return proc


# ---------------------------------------------------------------------------
# Hébergement de serveurs locaux
# ---------------------------------------------------------------------------

def get_local_ip():
    """Adresse IP locale (LAN) de la machine, pour la partager avec des amis."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


DEFAULT_SERVER_PROPERTIES = {
    "server-port": "25565",
    "gamemode": "survival",
    "difficulty": "normal",
    "max-players": "10",
    "online-mode": "false",   # pas d'auth Microsoft dans ce launcher -> désactivé par défaut
    "motd": "Serveur PyMC Launcher",
    "level-name": "world",
    "pvp": "true",
    "spawn-protection": "16",
    "white-list": "false",
    "enable-command-block": "false",
}


class ServerManager:

    @staticmethod
    def install(version_id, server_dir: Path, properties: dict, progress_cb=None):
        """Télécharge le .jar serveur officiel + le runtime Java adapté, écrit
        eula.txt (acceptation explicite requise en amont côté UI) et
        server.properties (uniquement s'il n'existe pas déjà, pour ne pas
        écraser une config existante)."""
        vjson = MojangAPI.get_version_json(version_id)
        server_download = vjson.get("downloads", {}).get("server")
        if not server_download:
            raise RuntimeError(
                f"Aucun .jar serveur officiel publié par Mojang pour la version {version_id}."
            )
        server_dir.mkdir(parents=True, exist_ok=True)
        jar_path = server_dir / "server.jar"
        if progress_cb:
            progress_cb("Téléchargement du serveur Minecraft...", 0, 1)
        download_file(server_download["url"], jar_path)

        eula_path = server_dir / "eula.txt"
        if not eula_path.exists():
            eula_path.write_text("eula=true\n", encoding="utf-8")

        props_path = server_dir / "server.properties"
        if not props_path.exists():
            merged = dict(DEFAULT_SERVER_PROPERTIES)
            merged.update({k: str(v) for k, v in properties.items()})
            lines = [f"{k}={v}" for k, v in merged.items()]
            props_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        java_path = None
        component = vjson.get("javaVersion", {}).get("component")
        if component:
            try:
                java_path = str(JavaRuntimeAPI.install(component, progress_cb=progress_cb))
            except Exception:
                java_path = None
        return java_path

    @staticmethod
    def start(server_dir: Path, java_path, min_ram, max_ram, log_cb=None):
        java_path = java_path or "java"
        cmd = [java_path, f"-Xms{min_ram}G", f"-Xmx{max_ram}G", "-jar", "server.jar", "nogui"]
        if log_cb:
            log_cb("=== Démarrage du serveur ===")
            log_cb(" ".join(cmd))
        proc = subprocess.Popen(
            cmd, cwd=str(server_dir),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        return proc

    @staticmethod
    def send_command(proc, command: str):
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write(command.strip() + "\n")
                proc.stdin.flush()
            except OSError:
                pass

    @staticmethod
    def stop(proc, timeout=20):
        if proc and proc.poll() is None:
            ServerManager.send_command(proc, "stop")
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()


# ---------------------------------------------------------------------------
# Discord Rich Presence (simple et automatique)
# ---------------------------------------------------------------------------

try:
    from pypresence import Presence
    import time
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    print("⚠️ pip install pypresence pour la présence Discord")

class DiscordPresence:
    CLIENT_ID = "1524081185893126335"  # TON ID ICI !
    
    _instance = None
    _running = False
    _start_time = None
    _status = "idle"  # idle, playing, hosting
    
    @classmethod
    def _init(cls):
        if cls._instance is None and DISCORD_AVAILABLE:
            try:
                cls._instance = Presence(cls.CLIENT_ID)
                cls._instance.connect()
                cls._running = True
                cls._start_time = int(time.time())
                cls._status = "idle"
                cls._update_presence()
            except Exception as e:
                print(f"⚠️ Discord : {e}")
                cls._running = False
    
    @classmethod
    def _update_presence(cls):
        if not DISCORD_AVAILABLE or not cls._running:
            return
        try:
            if cls._status == "idle":
                cls._instance.update(
                    state="Dans le launcher",
                    details="PyMC Launcher",
                    large_image="pymc_icon",
                    large_text="PyMC Launcher",
                    start=cls._start_time
                )
            elif cls._status == "playing":
                cls._instance.update(
                    state="Joue à Minecraft",
                    details="via PyMC Launcher",
                    large_image="pymc_icon",
                    large_text="PyMC Launcher",
                    start=cls._start_time
                )
            elif cls._status == "hosting":
                cls._instance.update(
                    state="Héberge un serveur",
                    details="via PyMC Launcher",
                    large_image="pymc_icon",
                    large_text="PyMC Launcher",
                    start=cls._start_time
                )
        except Exception as e:
            print(f"⚠️ Discord update : {e}")
            cls._running = False
    
    @classmethod
    def set_idle(cls):
        cls._init()
        cls._status = "idle"
        cls._update_presence()
    
    @classmethod
    def set_playing(cls):
        cls._init()
        cls._status = "playing"
        cls._update_presence()
    
    @classmethod
    def set_hosting(cls):
        cls._init()
        cls._status = "hosting"
        cls._update_presence()
    
    @classmethod
    def clear(cls):
        if cls._instance:
            try:
                cls._instance.clear()
            except Exception:
                pass
            cls._instance = None
            cls._running = False


# ---------------------------------------------------------------------------
# Notifications système (Windows / macOS / Linux)
# ---------------------------------------------------------------------------

def notify(title: str, message: str, timeout: int = 6):
    """Affiche une notification système (toast Windows, notification macOS/Linux).
    Échoue silencieusement si `plyer` n'est pas installé ou si le système
    ne supporte pas les notifications (ex: certains environnements headless) —
    ce n'est jamais bloquant pour le launcher."""
    try:
        from plyer import notification
        icon_path = Path(__file__).resolve().parent / "pymc_icon.ico"
        notification.notify(
            title=title,
            message=message,
            app_name="PyMC Launcher",
            app_icon=str(icon_path) if os_name() == "windows" and icon_path.exists() else "",
            timeout=timeout,
        )
    except Exception:
        pass

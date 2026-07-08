"""
updater.py — Système de mise à jour automatique pour PyMC Launcher.
Vérifie la version en ligne et met à jour les fichiers si nécessaire.
"""

import os
import sys
import json
import shutil
import tempfile
import zipfile
import requests
import subprocess
from pathlib import Path
from tkinter import messagebox

# Version actuelle du launcher (à incrémenter manuellement à chaque release)
CURRENT_VERSION = "1.2.0"

# URL du fichier de version en ligne (sur GitHub)
VERSION_URL = "https://raw.githubusercontent.com/herobrinepft-dev/PyMC-Launcher/main/version.json"
DOWNLOAD_URL = "https://github.com/herobrinepft-dev/PyMC-Launcher/archive/refs/heads/main.zip"

# Fichiers à exclure de la mise à jour (pour ne pas perdre les données)
EXCLUDE_FILES = [".pymc_launcher", "config.json", "launcher.py"]  # launcher.py sera mis à jour mais on le gère spécialement
EXCLUDE_DIRS = [".pymc_launcher"]


def get_latest_version():
    """Récupère la dernière version disponible en ligne."""
    try:
        response = requests.get(VERSION_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Impossible de vérifier les mises à jour : {e}")
        return None


def check_update():
    """Vérifie si une mise à jour est disponible."""
    online_data = get_latest_version()
    if not online_data:
        return None

    online_version = online_data.get("version", "0.0.0")
    force_update = online_data.get("force_update", False)

    # Comparer les versions (simple comparaison de chaînes)
    if online_version == CURRENT_VERSION and not force_update:
        return None  # Pas de mise à jour

    return online_data


def download_update(progress_cb=None):
    """Télécharge la mise à jour depuis GitHub."""
    temp_dir = tempfile.mkdtemp()
    zip_path = Path(temp_dir) / "update.zip"

    if progress_cb:
        progress_cb("Téléchargement de la mise à jour...", 0)

    try:
        # Télécharger le zip
        response = requests.get(DOWNLOAD_URL, stream=True, timeout=30)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))

        with open(zip_path, "wb") as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total_size:
                    progress_cb("Téléchargement de la mise à jour...", downloaded / total_size * 100)

        # Extraire le zip
        if progress_cb:
            progress_cb("Extraction des fichiers...", 50)

        extract_dir = Path(temp_dir) / "extracted"
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Le zip contient un dossier du type "PyMC-Launcher-main"
        extracted_root = list(extract_dir.glob("PyMC-Launcher*"))[0]

        if progress_cb:
            progress_cb("Installation de la mise à jour...", 75)

        return extracted_root

    except Exception as e:
        raise RuntimeError(f"Erreur lors du téléchargement de la mise à jour : {e}")


def apply_update(extracted_root, progress_cb=None):
    """Applique la mise à jour en remplaçant les fichiers."""
    current_dir = Path(__file__).parent

    if progress_cb:
        progress_cb("Application de la mise à jour...", 80)

    # Copier les nouveaux fichiers (sauf les dossiers exclus)
    for src_file in extracted_root.rglob("*"):
        if src_file.is_dir():
            continue

        # Chemin relatif par rapport au dossier extrait
        rel_path = src_file.relative_to(extracted_root)
        dest_path = current_dir / rel_path

        # Vérifier si le fichier doit être exclu
        should_exclude = False
        for exclude_dir in EXCLUDE_DIRS:
            if exclude_dir in str(rel_path):
                should_exclude = True
                break
        for exclude_file in EXCLUDE_FILES:
            if rel_path.name == exclude_file:
                should_exclude = True
                break

        if should_exclude:
            continue

        # Créer le dossier parent si nécessaire
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Copier le fichier
        try:
            shutil.copy2(src_file, dest_path)
        except Exception as e:
            print(f"Erreur lors de la copie de {rel_path} : {e}")

    if progress_cb:
        progress_cb("Mise à jour terminée, redémarrage...", 100)


def run_updater():
    """Fonction principale du système de mise à jour."""
    try:
        # Vérifier les mises à jour
        update_data = check_update()

        if not update_data:
            return False  # Pas de mise à jour disponible

        # Afficher un message à l'utilisateur
        version = update_data.get("version", "inconnue")
        changelog = update_data.get("changelog", ["Mise à jour disponible."])
        changelog_text = "\n".join(f"• {item}" for item in changelog)

        # Boîte de dialogue personnalisée (ou on utilise messagebox simple)
        response = messagebox.askyesno(
            "Mise à jour disponible",
            f"Une nouvelle version de PyMC Launcher est disponible !\n\n"
            f"Version : {version}\n\n"
            f"Changements :\n{changelog_text}\n\n"
            f"Voulez-vous installer la mise à jour maintenant ?"
        )

        if not response:
            return False

        # Télécharger la mise à jour
        extracted_root = download_update()

        # Appliquer la mise à jour
        apply_update(extracted_root)

        # Nettoyer les fichiers temporaires
        if extracted_root.parent.parent.exists():
            shutil.rmtree(extracted_root.parent.parent, ignore_errors=True)

        messagebox.showinfo(
            "Mise à jour terminée",
            "La mise à jour a été installée avec succès.\n\n"
            "Le launcher va redémarrer."
        )

        return True

    except Exception as e:
        messagebox.showerror("Erreur de mise à jour", str(e))
        return False


def restart_launcher():
    """Redémarre le launcher après une mise à jour."""
    try:
        # Lancer le nouveau launcher
        python = sys.executable
        launcher_path = Path(__file__).parent / "launcher.py"
        subprocess.Popen([python, str(launcher_path)], shell=True)
        sys.exit(0)
    except Exception as e:
        print(f"Erreur lors du redémarrage : {e}")
        sys.exit(1)


def check_and_update_if_needed():
    """Vérifie les mises à jour et les installe si nécessaire."""
    try:
        update_data = check_update()
        if update_data and messagebox.askyesno(
            "Mise à jour disponible",
            f"Une nouvelle version ({update_data.get('version')}) est disponible. Voulez-vous l'installer ?"
        ):
            if run_updater():
                restart_launcher()
                return True
    except Exception as e:
        print(f"Erreur de mise à jour : {e}")
    return False


if __name__ == "__main__":
    # Mode standalone : exécute la mise à jour
    run_updater()

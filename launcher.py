#!/usr/bin/env python3
"""Point d'entrée : lance l'interface graphique du launcher."""

import sys
import os

def main():
    # <--- AJOUT : Définir l'icône pour Windows
    if sys.platform == "win32":
        import ctypes
        try:
            # Changer l'icône dans la barre des tâches
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PyMCLauncher")
        except Exception:
            pass

    if len(sys.argv) > 1 and sys.argv[1] == "--skip-update":
        from gui import main as gui_main
        gui_main()
        return

    try:
        import updater
        if updater.check_and_update_if_needed():
            return
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ Erreur de mise à jour : {e}")

    from gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()

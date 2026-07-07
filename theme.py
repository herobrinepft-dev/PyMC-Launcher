"""
theme.py — Thème visuel sombre façon launcher moderne (Lunar/Feather-like)
+ quelques widgets réutilisables (bouton arrondi, carte, liste défilante).

Tkinter ne fait pas de vrai flou/ombres, mais avec une palette sombre cohérente,
des coins arrondis dessinés à la main sur Canvas, une sidebar de navigation et
des "cartes" pour les listes, on se rapproche fortement de ce look.
"""

import tkinter as tk
from tkinter import ttk

# ----------------------------------------------------------------- Palette
BG_DARKEST = "#0d0d11"      # sidebar
BG_DARK = "#16161d"         # fond général du contenu
BG_CARD = "#1e1e28"         # cartes (instances, mods)
BG_CARD_HOVER = "#272733"
BG_INPUT = "#20202a"

ACCENT = "#7c5cff"          # violet accent (façon Lunar/Feather)
ACCENT_HOVER = "#8f72ff"
ACCENT_DARK = "#5a3fd6"

SUCCESS = "#3ddc84"
DANGER = "#ff5c72"
WARNING = "#ffb84d"

TEXT_PRIMARY = "#f2f2f6"
TEXT_SECONDARY = "#9a9aab"
TEXT_MUTED = "#65656f"
BORDER = "#2a2a36"

FONT_FAMILY = "Segoe UI"    # fallback géré par tkinter si absent


def font(size=10, weight="normal"):
    return (FONT_FAMILY, size, weight)


def apply_global_theme(root: tk.Tk):
    root.configure(bg=BG_DARK)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("TFrame", background=BG_DARK)
    style.configure("Card.TFrame", background=BG_CARD)
    style.configure("Sidebar.TFrame", background=BG_DARKEST)

    style.configure("TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=font(10))
    style.configure("Secondary.TLabel", background=BG_DARK, foreground=TEXT_SECONDARY, font=font(9))
    style.configure("Title.TLabel", background=BG_DARK, foreground=TEXT_PRIMARY, font=font(18, "bold"))
    style.configure("CardTitle.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=font(11, "bold"))
    style.configure("CardSub.TLabel", background=BG_CARD, foreground=TEXT_SECONDARY, font=font(9))
    style.configure("Sidebar.TLabel", background=BG_DARKEST, foreground=TEXT_PRIMARY, font=font(10))

    style.configure("TEntry", fieldbackground=BG_INPUT, foreground=TEXT_PRIMARY,
                     insertcolor=TEXT_PRIMARY, borderwidth=0, relief="flat")
    style.map("TEntry", fieldbackground=[("focus", BG_INPUT)])

    style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_INPUT,
                     foreground=TEXT_PRIMARY, arrowcolor=TEXT_PRIMARY, borderwidth=0)
    style.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)],
              foreground=[("readonly", TEXT_PRIMARY)])

    style.configure("TCheckbutton", background=BG_DARK, foreground=TEXT_PRIMARY)
    style.configure("TSpinbox", fieldbackground=BG_INPUT, foreground=TEXT_PRIMARY, borderwidth=0)

    style.configure("TNotebook", background=BG_DARK, borderwidth=0)
    style.configure("TNotebook.Tab", background=BG_DARKEST, foreground=TEXT_SECONDARY,
                     padding=(14, 8), font=font(10, "bold"))
    style.map("TNotebook.Tab", background=[("selected", BG_DARK)],
              foreground=[("selected", TEXT_PRIMARY)])

    style.configure("Accent.Horizontal.TProgressbar", troughcolor=BG_CARD,
                     background=ACCENT, borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)

    style.configure("Vertical.TScrollbar", background=BG_CARD, troughcolor=BG_DARK,
                     arrowcolor=TEXT_SECONDARY, borderwidth=0)
    return style


# ------------------------------------------------------------ Rounded rect
def _rounded_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


class RoundedButton(tk.Canvas):
    """Bouton avec coins arrondis dessiné sur Canvas (ttk ne gère pas ça)."""

    def __init__(self, parent, text, command=None, bg=ACCENT, hover_bg=ACCENT_HOVER,
                 fg=TEXT_PRIMARY, width=200, height=42, radius=12, font_size=11,
                 font_weight="bold", disabled_bg="#3a3a45"):
        super().__init__(parent, width=width, height=height, bg=parent["bg"] if "bg" in parent.keys() else BG_DARK,
                          highlightthickness=0, bd=0)
        self.command = command
        self.bg_color = bg
        self.hover_color = hover_bg
        self.disabled_bg = disabled_bg
        self.enabled = True
        self.btn_width, self.btn_height, self.btn_radius = width, height, radius

        self.rect = self.create_polygon(_rounded_points(1, 1, width - 1, height - 1, radius),
                                         smooth=True, fill=bg, outline="")
        self.label = self.create_text(width // 2, height // 2, text=text, fill=fg,
                                       font=(FONT_FAMILY, font_size, font_weight))

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _e):
        if self.enabled:
            self.itemconfig(self.rect, fill=self.hover_color)
            self.config(cursor="hand2")

    def _on_leave(self, _e):
        if self.enabled:
            self.itemconfig(self.rect, fill=self.bg_color)

    def _on_click(self, _e):
        if self.enabled and self.command:
            self.command()

    def set_text(self, text):
        self.itemconfig(self.label, text=text)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.itemconfig(self.rect, fill=self.bg_color if enabled else self.disabled_bg)
        self.config(cursor="hand2" if enabled else "arrow")


class Badge(tk.Canvas):
    """Petite pastille arrondie (ex: 'fabric', 'actif')."""

    def __init__(self, parent, text, bg=ACCENT, fg="#0d0d11", padding=8, height=22, font_size=8):
        width = len(text) * 7 + padding * 2
        super().__init__(parent, width=width, height=height, bg=parent["bg"] if "bg" in parent.keys() else BG_CARD,
                          highlightthickness=0, bd=0)
        self.create_polygon(_rounded_points(1, 1, width - 1, height - 1, height // 2),
                             smooth=True, fill=bg, outline="")
        self.create_text(width // 2, height // 2, text=text.upper(), fill=fg,
                          font=(FONT_FAMILY, font_size, "bold"))


class ScrollableFrame(ttk.Frame):
    """Zone défilante (verticale) contenant self.inner comme conteneur de cartes."""

    def __init__(self, parent, bg=BG_DARK):
        super().__init__(parent, style="TFrame")
        canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = tk.Frame(canvas, bg=bg)

        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)

        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _wheel(event):
            delta = -1 if event.num == 5 or event.delta < 0 else 1
            canvas.yview_scroll(-delta, "units")

        def _bind_wheel(_e):
            canvas.bind_all("<MouseWheel>", lambda e: _wheel(e))
            canvas.bind_all("<Button-4>", _wheel)
            canvas.bind_all("<Button-5>", _wheel)

        def _unbind_wheel(_e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)


class Avatar(tk.Canvas):
    """Cercle coloré avec l'initiale du pseudo, façon avatar de profil."""

    def __init__(self, parent, letter, size=36, bg=ACCENT, fg="#0d0d11"):
        super().__init__(parent, width=size, height=size, bg=parent["bg"] if "bg" in parent.keys() else BG_DARK,
                          highlightthickness=0, bd=0)
        self.create_oval(1, 1, size - 1, size - 1, fill=bg, outline="")
        self.create_text(size // 2, size // 2, text=letter.upper(), fill=fg,
                          font=(FONT_FAMILY, int(size * 0.4), "bold"))

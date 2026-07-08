# PyMC Launcher

Un launcher Minecraft "maison" en Python/Tkinter, avec une interface sombre
inspirée des launchers premium (sidebar de navigation, cartes pour les
instances/mods, gros bouton JOUER arrondi, avatars de profil), et :

- **Gestion d'instances** : chaque instance a sa propre version de Minecraft,
  son propre dossier de sauvegardes/mods/resourcepacks, et peut utiliser
  Minecraft vanilla ou **Fabric**.
- **Installation automatique** du client, des librairies, des natives et des
  assets, directement depuis l'API officielle et publique de Mojang
  (`piston-meta.mojang.com`) — comme le font les launchers open source connus.
- **Installation de Fabric** via l'API publique `meta.fabricmc.net`.
- **Navigateur de mods intégré** utilisant l'API publique et gratuite de
  **Modrinth** (`api.modrinth.com`), filtré automatiquement par la version de
  Minecraft et le loader de l'instance sélectionnée, avec téléchargement direct
  dans le dossier `mods/` de l'instance.
- **Serveurs locaux** : héberge un vrai serveur Minecraft sur ton PC (comme la
  fonctionnalité "server hosting" de Feather Client). Le launcher télécharge
  le `.jar` serveur officiel de Mojang, écrit `eula.txt`/`server.properties`,
  et te fournit une console en direct avec envoi de commandes, plus l'adresse
  IP locale à partager avec tes amis sur le même réseau.
- **Comptes hors-ligne** (offline/"cracked-style") : pseudo + UUID généré
  localement (identique à l'algorithme officiel `UUID.nameUUIDFromBytes`).
- **Paramètres** : chemin Java personnalisé, RAM min/max.
- **Onglet Logs** affichant la sortie du jeu en direct.

## Installation

```bash
pip install -r requirements.txt
python launcher.py
```

Prérequis : **Java** doit être installé sur la machine (Java 17+ recommandé
pour les versions récentes de Minecraft, Java 8 pour les très anciennes
versions). Le launcher tente de détecter `java`/`javaw` automatiquement,
sinon indique le chemin complet dans l'onglet **Paramètres**.

## Utilisation rapide

1. Onglet **Comptes** → ajoute un pseudo (compte hors-ligne).
2. Onglet **Jouer** → **+ Nouvelle instance** → choisis une version de
   Minecraft et, si tu veux des mods, le loader **fabric**.
3. Clique sur **Installer / Vérifier les fichiers** (télécharge le jeu, les
   librairies et les assets — peut prendre plusieurs minutes la première fois).
4. Onglet **Mods** → choisis l'instance cible, recherche un mod, sélectionne
   une version compatible, **Télécharger dans l'instance**.
5. Retour onglet **Jouer** → **▶ JOUER**.

## À propos de la chaleur pendant l'installation

La première installation d'une version télécharge des dizaines de milliers de
petits fichiers (assets). Un pic de charge CPU et de bruit de ventilateurs
pendant cette phase est normal. Une session HTTP partagée (réutilisation des
connexions) et un nombre de téléchargements parallèles raisonnable (8) sont
utilisés pour limiter ce pic. Si ta machine chauffe beaucoup pendant cette
phase, tu peux réduire encore `max_workers` dans `core.py`
(`install_version` et `FabricAPI.install`) à 4, au prix d'une installation un
peu plus lente.

## Limites connues / notes légales

- **Pas d'authentification Microsoft/Xbox Live.** Jouer sur les serveurs
  multijoueurs officiels premium nécessiterait un flux OAuth complet avec une
  application Azure enregistrée (identifiants propres à chaque développeur).
  Ce launcher se limite volontairement à un mode **hors-ligne**, utilisable en
  solo ou sur des serveurs communautaires configurés en `online-mode=false`.
  Utilise-le uniquement avec un exemplaire de Minecraft que tu possèdes
  légalement — cela reste soumis à l'EULA de Mojang.
- Les arguments de lancement liés à des "features" optionnelles (résolution
  personnalisée, mode démo, etc.) ne sont pas gérés — valeurs par défaut
  utilisées.
- Les très vieilles versions (pré-1.6) peuvent nécessiter des ajustements
  spécifiques non couverts ici.
- Le premier téléchargement d'une version peut représenter plusieurs centaines
  de Mo (assets inclus) : c'est normal, c'est mis en cache pour les fois
  suivantes.

## Architecture des fichiers

```
mc_launcher/
├── launcher.py     # point d'entrée
├── core.py         # API Mojang / Fabric / Modrinth + logique de lancement
├── theme.py        # palette de couleurs + widgets stylés (sidebar, cartes, boutons arrondis)
├── gui.py          # interface Tkinter
└── requirements.txt
```

## ⚠️ Windows Defender / Antivirus

PyMC-Launcher peut parfois être détecté comme un faux positif par certains
antivirus. C'est un problème classique avec les exécutables créés avec PyInstaller.

**Rassure-toi :** Le code source est entièrement ouvert et vérifiable sur GitHub.

Si tu as un message d'erreur, ajoute le dossier du launcher dans les exclusions
de Windows Defender :

1. Paramètres → Sécurité Windows → Protection contre les virus et menaces
2. Gérer les paramètres → Exclusions
3. Ajouter une exclusion → Dossier du launcher

**Résultat VirusTotal :** 5/68 (seuls 5 antivirus sur 68 détectent, aucun des majeurs)

Les données persistantes (config, versions, librairies, assets, instances)
sont stockées dans `~/.pymc_launcher/`.

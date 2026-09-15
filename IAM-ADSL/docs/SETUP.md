# Installation locale (Windows)

## Prérequis

Installez Python 3.10 ou plus récent, en cochant **Add Python to PATH**.
Chrome et l'accès réseau à WimTech sont aussi nécessaires pour lancer les
automatisations Selenium.

## Créer `.venv`

Depuis la racine du dépôt :

```powershell
.\scripts\setup.ps1
```

Le script crée `.venv`, met `pip` à jour et installe le projet ainsi que les
outils de test. Le dossier est ignoré par Git.

Pour démarrer l'application après l'installation :

```powershell
.\scripts\setup.ps1 -Run
```

Ou directement :

```powershell
.\.venv\Scripts\python.exe app.py
```

Pour exécuter les tests :

```powershell
.\.venv\Scripts\python.exe -m pytest
```

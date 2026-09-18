# Couverture FTTH — service indépendant

Carte partagée sur le réseau local, sans modification ni dépendance au projet `/VULA`.
Les visiteurs utilisent leur navigateur, sans installation Python sur leurs PC.

## Démarrage

Sur le **PC serveur Windows**, installer Python 3.10+ puis choisir :

- **Portail complet en réseau** : lancer `..\run-lan.bat`, puis partager
  `http://IP_DU_PC/Coverage/` (port du portail : 80 par défaut, configurable avec `GATEWAY_PORT`).
  La page d'accueil propose les quatre services. Ce mode partage aussi les autres services.
- **Portail local habituel** : `..\run.bat`, puis `http://127.0.0.1/Coverage/`.
- **Carte seule en réseau** : `start.bat`, puis partager `http://IP_DU_PC:5060/`.
  Ne pas lancer simultanément la carte seule et le portail : ils utilisent le même port interne 5060.

Le premier lancement installe les dépendances (Internet requis) et demande de créer un
mot de passe administrateur de 12 caractères minimum dans la console du serveur.
Il n'y a aucun mot de passe par défaut. L'administration est à `/Coverage/admin`
via le portail, ou `/admin` en mode indépendant. Les visiteurs n'ont pas besoin de compte.

Trouver l'adresse IPv4 du serveur avec `ipconfig`. Les PC doivent pouvoir se joindre
sur le réseau local. Si Windows bloque l'accès, faire autoriser le port choisi par
le responsable réseau, uniquement sur le profil privé et le sous-réseau local.
Le programme ne modifie pas le pare-feu. Le PC serveur doit rester allumé.

## Administration et imports

- Zones **IAM bleu**, **INWI violet**, **ORANGE orange** : un import par opérateur,
  en KML/KMZ/GeoJSON WGS84. Polygones, multipolygones et trous sont pris en charge.
- Points PCO : KML/KMZ/GeoJSON, avec un nom de point correspondant à la colonne PCO.
- Occupation : `.xlsx` (première feuille) ou CSV avec `PCO,NBRE_OCCUPE,NBRE_PORT`.
- Clients : `.xlsx` (première feuille) ou CSV avec `ODF,Login,Série ONT,Nom Client,Adresse Client,NE,PCO,OLT`.
  PCO est requis ; les autres champs absents sont laissés vides. Les colonnes inconnues sont ignorées.
- CSV UTF-8 ou Windows-1252, séparateur virgule, point-virgule ou tabulation.
  Convertir les anciens fichiers `.xls` en `.xlsx` avant import.
- Maximum 20 Mo par fichier et 100 000 objets/lignes. Conserver les identifiants sous
  forme de texte dans Excel pour préserver les zéros initiaux.

Chaque import **remplace uniquement le jeu sélectionné**, après validation complète.
Regrouper les zones d'un opérateur dans un fichier pour les conserver toutes.
Une erreur laisse les anciennes données intactes. Le bouton Vider demande confirmation ;
la restauration consiste à réimporter le fichier source. Aucun dessin manuel de polygone
n'est prévu dans cette première version.

Les points PCO apparaissent sur la carte. La recherche de zone PCO filtre le **préfixe/nom**,
pas un nouveau polygone de desserte. L'occupation est associée aux points par leur nom
(insensible aux accents, espaces et ponctuation) : vérifier la cohérence des noms importés.
Les PCO sont triés par ports libres décroissants, les occupations inconnues en dernier.
Les 100 premiers résultats sont affichés ; préciser le filtre pour trouver les autres.

## Visibilité et confidentialité

L'admin active/désactive chaque opérateur, les PCO, leur occupation et la base clients.
Les restrictions sont appliquées **côté serveur**, y compris aux résultats GPS et aux API.
La base clients est **désactivée par défaut**. L'activer autorise tout visiteur du service
à rechercher des clients : aucune gestion de permissions individuelles n'est incluse.
L'occupation n'est affichée qu'avec les points PCO publiés.

La page recharge les données toutes les 60 secondes lorsqu'elle est visible ; un bouton
permet de le faire immédiatement. Masquer une couche empêche les prochains téléchargements,
mais ne peut pas effacer une information déjà reçue ou copiée par un utilisateur.
Les cases sur la carte règlent seulement l'affichage personnel, pas les permissions admin.

Le serveur utilise HTTP sur le réseau local : le mot de passe et les données ne sont pas
chiffrés en transit. Utiliser exclusivement un LAN de confiance. **Ne pas exposer ce
service ou le portail directement sur Internet.** Pour un réseau non fiable, faire
installer HTTPS et une authentification utilisateur par le responsable informatique.
`run-lan.bat` expose aussi Cuiver, FO et VULA avec leurs protections existantes.

## Données, carte et sauvegarde

Tout est centralisé dans `data/coverage.sqlite3` sur le serveur (données, réglages,
secret de session et mot de passe haché). Le dossier `data/` est exclu de Git.
Pour sauvegarder/restaurer, arrêter le service puis copier/restaurer ce dossier.
Les vrais fichiers opérationnels et les données clients ne doivent jamais être ajoutés à Git.

Leaflet 1.9.4 est livré dans `static/vendor/` avec sa licence : les zones et le calcul
GPS restent utilisables sans CDN ni Internet après installation.
Le fond routier OpenStreetMap nécessite Internet sur les PC utilisateurs ; les requêtes
de tuiles communiquent au fournisseur la zone géographique affichée, pas les fichiers importés.
Aucun géocodage externe n'est utilisé. En cas de fond indisponible, les zones restent affichées.
Respecter la [politique des tuiles OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).

La recherche GPS accepte `34.035175, -4.987058`, `34.035175 -4.987058`,
ou `34,035175 / -4,987058`. Une limite de polygone est considérée couverte ;
l'intérieur d'un trou ne l'est pas. Les zones superposées affichent plusieurs opérateurs.
Le résultat exprime une couverture déclarée, pas une garantie de raccordement.

## Maintenance

Changer ou réinitialiser le mot de passe depuis le PC serveur :

```powershell
.\.venv\Scripts\python.exe app.py --reset-admin
```

Les anciennes sessions admin sont alors révoquées. Les variables facultatives sont
`COVERAGE_HOST` (défaut `0.0.0.0`), `COVERAGE_PORT` (5060), `COVERAGE_DATA_DIR`.
`COVERAGE_PREFIX` est réservé à l'intégration du portail, qui le fixe à `/Coverage`
et limite l'écoute du service interne à `127.0.0.1`.

Tests (données synthétiques, aucun fichier métier requis) :

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Un test navigateur optionnel est fourni dans `tests/browser_smoke.py` : l'exécuter
avec un interpréteur disposant de Selenium et Chrome installé. Il utilise uniquement
des données fictives, un serveur temporaire local et ferme ses processus à la fin.

Références : [Leaflet](https://leafletjs.com/examples/quick-start/),
[Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/runner.html),
[Shapely covers](https://shapely.readthedocs.io/en/stable/reference/shapely.covers.html).

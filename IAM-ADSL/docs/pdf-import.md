# Import PDF - CMD Cuivre

La zone texte reste disponible dans les deux écrans. Le bouton PDF remplit
simplement cette zone et ne démarre jamais Selenium automatiquement, ce qui
permet de vérifier ou modifier les CMD avant de lancer le Bulk.

## Bulk Auto Etude

Une ligne est retenue quand :

- `Ccna` est vide ;
- `etat` vaut `EI`, `IR` ou `EE` ;
- `Dde Wiam` commence par `D` (Cuivre dégroupage ADSL) ou est décimal
  (Cuivre IAM ADSL) ;
- `dde sara` est décimal. Cette valeur devient le CMD.

## Bulk Ré-Étude VA

Une ligne est retenue quand :

- `Ccna` est vide ;
- `etat` vaut `VA` ;
- `Dde Wiam` commence par `D` (Cuivre dégroupage) ou est décimal
  (Cuivre IAM ADSL) ;
- `dde sara` est décimal. Cette valeur devient le CMD.

Toute ligne dont `Ccna` contient `FO` ou une autre valeur est ignorée. Les
doublons sont supprimés en conservant l'ordre du PDF.

## Installation

```powershell
.\\scripts\\setup.ps1
.\\.venv\\Scripts\\python.exe app.py
```

## Réutiliser l'extracteur ailleurs

Le fichier `cmd_pdf_extractor.py` ne dépend ni de Flask ni de Selenium.

```python
from iam_adsl.services.pdf_extractor import extract_cmds_from_pdf

etude = extract_cmds_from_pdf("cmd.pdf", mode="etude")
print(etude["commands"])

va = extract_cmds_from_pdf("cmd.pdf", mode="va")
print(va["commands"])
```

Pour une ligne provenant déjà d'un Excel, CSV ou d'une base de données :

```python
from iam_adsl.services.pdf_extractor import classify_cuivre_row

cmd, classification, ignored_reason = classify_cuivre_row(
    ccna="",
    etat="VA",
    dde_wiam="DTLI71989161",
    dde_sara="139702926",
    mode="va",
)
```

Utilisation directe :

```powershell
.\\.venv\\Scripts\\python.exe -m iam_adsl.services.pdf_extractor cmd.pdf --mode etude
.\\.venv\\Scripts\\python.exe -m iam_adsl.services.pdf_extractor cmd.pdf --mode va
.\\.venv\\Scripts\\python.exe -m iam_adsl.services.pdf_extractor cmd.pdf --mode va --json
```

Le PDF doit être un PDF texte contenant les colonnes `Ccna`, `etat`,
`Dde Wiam` et `dde sara`. Un document scanné comme image nécessite un OCR.

## Règles d'automatisation conservées

- En Ré-Étude VA hors zone RADIAN, tous les chemins transport sont testés dans
  l'ordre `MSAN`, puis `TT`, puis `TTR`, directement dans la même page WimTech.
  Le TETE déjà développé reste ouvert : aucun bouton Back et aucun onglet
  temporaire ne sont utilisés. L'application développe ensuite le TETE suivant.
  Un premier passage cherche `PAIRE-Libre`; si aucune n'existe, un deuxième
  passage complet cherche `PAIRE-En cours decon`. Le statut manuel apparaît
  seulement après les deux passages sur tous les chemins éligibles.
- En Semi-Auto Étude, un Quartier ou une Voie inconnu ne ferme pas la session :
  la recherche Excel affiche ses candidats et l'opérateur choisit manuellement
  la Constitution avec « Apply Étude ».
- En Bulk Auto Étude, la même adresse inconnue arrête uniquement le CMD courant
  avant la recherche Excel et l'étude, ferme sa session, affiche
  « Should verify manual », puis passe au CMD suivant.

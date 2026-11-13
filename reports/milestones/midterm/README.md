# Rapport de mi-parcours

Le rapport suit les cinq sections essentielles du gabarit fourni et comprend
trois preuves visuelles réelles, dans cinq pages A4 annexes comprises.

- Source modifiable : `rapport_miparcours.tex`.
- Livrable : `Rapport_MiParcours_TrackX_ResilientInspectAI.pdf`.
- Figures copiées sans modifier les pixels : `figures/`.
- Audit et valeurs exactes : `audit/`.
- Rendus et fichiers intermédiaires : `build/` (ne pas joindre à la remise).

Les noms et courriels du gabarit ont été confirmés par le binôme. Restent à
compléter : code officiel du track, identifiant du groupe, rôles individuels,
attributions RACI et date finale de soutenance. TrackX est volontairement
temporaire. Le taux global de 50 % et ses pondérations sont une proposition
explicite de planification, pas un résultat scientifique ni une note.

Les résultats B0 et A1 sur les trois catégories sont présents et recopiés sans
arrondir leurs valeurs archivées. Les anciennes mentions « A1 en attente » dans
la documentation historique n'ont pas été reprises comme état courant. Les
trois smoke transfert ne sont pas des entraînements complets T0/T1/T2.

La capture `6_runs_mlflow.png` montre seulement trois B0 full et un smoke ; sa
légende l'indique. Aucune capture A1 ou des tests n'était disponible. Nous
n'avons fabriqué aucune capture. Les preuves A1 viennent des checkpoints,
historiques, résultats et bases SQLite, et la preuve des tests du JSON de
vérification. Les trois annexes visuelles privilégient la capture réelle,
une courbe réelle et un résultat B0 réel, comme demandé.

## Compiler et vérifier

Depuis ce dossier, avec les outils LaTeX existants dans le PATH :

```powershell
.\compile_report.ps1 -Render
& C:\Users\nouhe\resilientinspect-ai\.venv\Scripts\python.exe -B .\verify_report.py
```

Le script exécute deux passes de `pdflatex`, avec `--disable-installer` : aucun
paquet système ou LaTeX n'est installé automatiquement. Il copie le PDF final
dans ce dossier puis exécute les outils Poppler existants. La compilation a
été vérifiée avec MiKTeX 25.12. `microtype` n'étant pas installé, le rapport ne
le requiert pas. `latexmk` n'est pas nécessaire.

Commandes directes équivalentes :

```powershell
pdflatex --disable-installer -interaction=nonstopmode -halt-on-error -file-line-error -output-directory=build -jobname=Rapport_MiParcours_TrackX_ResilientInspectAI rapport_miparcours.tex
pdflatex --disable-installer -interaction=nonstopmode -halt-on-error -file-line-error -output-directory=build -jobname=Rapport_MiParcours_TrackX_ResilientInspectAI rapport_miparcours.tex
Copy-Item -LiteralPath build/Rapport_MiParcours_TrackX_ResilientInspectAI.pdf -Destination Rapport_MiParcours_TrackX_ResilientInspectAI.pdf
pdfinfo Rapport_MiParcours_TrackX_ResilientInspectAI.pdf
pdftoppm -r 140 -png Rapport_MiParcours_TrackX_ResilientInspectAI.pdf build/final-page
```

Ne joindre que le PDF pour la remise ; conserver le source et les figures pour
les modifications. L'audit n'a relancé aucun entraînement, smoke, test du
projet ou évaluation officielle. Aucune modification des configurations,
modèles, résultats ou manifestes n'était nécessaire.

# Finalisation ONNX — 20 novembre 2026

Application vérifiée sur **http://localhost:18080**. Backend et frontend Docker
healthy, ports locaux 8001 et 18080. Oracle et le port 8080 ne sont pas modifiés.
La phase s’arrête ici, avant DVC, MLflow Registry et CI/CD.

## Reprise sans recalcul

Les quinze exports et les validations antérieures sont conservés. L’audit a
vérifié les SHA256 des graphes, métadonnées et preuves Windows/Linux, ainsi
que leur correspondance exacte avec `code_hashes()` du code final. Le backend
servi confirme cette admission : **15 PyTorch, 14 ONNX Runtime**.

Les six benchmarks B0/T2 sont complets : 2 700 mesures brutes, 100 par groupe
moteur/condition et 20 warm-ups déclarés par condition dans le programme.
Les moyennes, médianes, p95 et écarts-types ont été recalculés depuis le CSV et
comparés aux valeurs JSON. Les six agrégats publics du frontend correspondent
exactement au benchmark source. Aucun export, benchmark ni validation numérique
réussi n’a été relancé pendant cette reprise.

## Disponibilité et parité

| Variante | PyTorch | ONNX Runtime |
| --- | --- | --- |
| B0 | bottle, hazelnut, leather | bottle, hazelnut, leather |
| A1 | bottle, hazelnut, leather | bottle, hazelnut, leather |
| T0 | bottle, hazelnut, leather | bottle, hazelnut, leather |
| T1 | bottle, hazelnut, leather | hazelnut, leather ; bottle refusé |
| T2 | bottle, hazelnut, leather | bottle, hazelnut, leather |

PyTorch Windows/Linux : 850 comparaisons réussies, FP32 explicitement identifié,
écart maximal 1,1920928955078125e-6 et cinq basculements proches des seuils.
Les anciennes preuves sont archivées localement dans le dossier pre-onnx-9bb2c8d.

ONNX Windows et Linux : 1 870 exemples par runtime, validation normale et
recettes synthétiques figées, aucune image test. Quatorze modèles passent.
Sous Linux, huit basculements proches des seuils respectent la politique
préalable ; aucun changement de décision injustifié. Le détail par modèle
est dans le [rapport scientifique](../../reports/experiments/onnx_benchmark.md).

T1/bottle échoue sur le normal val `bottle/train/good/201.png` et sa recette
synthétique normale identique. Écart maximal de score : 3,4153461e-5 sous Windows,
3,4511089e-5 sous Linux. Les logits respectent leur tolérance distincte ; le
score sigmoid dépasse sa propre limite. Aucun changement de décision, aucun
élargissement de tolérance et aucun nouveau seuil. L’origine algorithmique
exacte de la différence entre kernels n’a pas été isolée.

Le test HTTP demande réellement ce modèle avec ONNX et obtient **503
`onnx_unavailable`**, sans repli vers PyTorch. Ce refus est attendu et n’est
jamais compté comme une prédiction réussie.

## Mesures conservées — score complet

AMD Ryzen 5 5500U, Linux WSL2 x86_64, FP32, batch 1, deux threads.
Temps en ms ; facteur = moyenne PyTorch / moyenne ONNX, pas ratio des médianes.

| Modèle | PT p50 | ORT p50 | PT p95 | ORT p95 | Facteur moyen |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0/bottle | 29,593 | 14,180 | 86,241 | 26,953 | 2,419× |
| B0/hazelnut | 20,547 | 13,433 | 40,345 | 24,455 | 1,633× |
| B0/leather | 18,886 | 12,566 | 35,266 | 21,916 | 1,480× |
| T2/bottle | 64,050 | 27,388 | 134,372 | 67,127 | 2,292× |
| T2/hazelnut | 74,578 | 31,739 | 237,305 | 171,577 | 1,676× |
| T2/leather | 67,650 | 29,337 | 277,306 | 161,044 | 2,064× |

| Famille mesurée | Checkpoint entraînement Mo | State dict inférence Mo | Graphe ONNX Mo |
| --- | ---: | ---: | ---: |
| B0, chacune des trois catégories | 2,378 | 0,798 | 0,785 |
| T2, chacune des trois catégories | 41,630 | 16,328 | 16,025 |

Les tailles décimales détaillées, le forward seul, le débit, l’écart-type,
les chargements et RSS sont dans le rapport scientifique et ses JSON/CSV.
Grad-CAM PyTorch est mesuré séparément : p50 101,556 / 106,714 / 96,188 ms
pour bottle / hazelnut / leather. Aucun coût Grad-CAM n’entre dans le facteur
d’accélération ci-dessus. Aucun gain n’est attribué à A1/T0/T1 non chronométrés.

## Contrôles exécutés pendant la finalisation

| Contrôle | Résultat |
| --- | --- |
| Audit des preuves et des statistiques CSV | 6 benchmarks complets ; preuves liées au code final |
| Tests backend/ONNX/portabilité/Compose | **69 réussis**, dont neuf ONNX |
| Tests frontend | **70 réussis**, onze fichiers |
| Build TypeScript/Vite | Réussi ; bundle identique aux sources applicatives servies |
| Compose config et build frontend | Réussis ; backend validé conservé |
| check_onnx_api.py, sans argument | **8 HTTP 200** B0/T2 × deux moteurs × prédiction/visualisation |
| Moteur inconnu | HTTP 422 structuré |
| T1/bottle ONNX | HTTP 503 onnx_unavailable attendu |
| onnx-qa.mjs | passed=true, aucune erreur JavaScript |
| browser-qa.mjs | passed=true, 24 rendus : 3 tailles × 2 thèmes × 4 pages |
| Contrôle fichiers scientifiques | 273 entrées inchangées |
| Montages backend normal | 275 binds en lecture seule, zéro dataset monté |

Le test de navigation jsdom échouait pendant la transformation à froid du
module Analytics différé. Il précharge désormais ce module avant le test,
sans retirer les assertions de navigation ni modifier le code applicatif.
Le véritable chargement à froid reste testé par Playwright sur le build.
Cette seule modification de test n’invalide aucune preuve numérique.

Playwright ONNX vérifie Smart Inspection B0/T2 avec ONNX, l’identité du moteur
d’explication (ORT pour B0, PyTorch pour Grad-CAM T2), la cohérence du score
associé, la comparaison technique séquentielle des moteurs, les graphiques
p50/p95/débit et System Monitor. La suite responsive vérifie aussi l’historique
sans images persistées et le parcours d’architecture B0/T2.

Preuves de tests : [HTTP](onnx-http.json),
[navigateur ONNX](../../frontend/reports/onnx-browser-verification.json),
[régression responsive](../../frontend/reports/browser-verification.json).
Captures locales sous `frontend/reports/screenshots/` : onnx-B0.png,
onnx-T2.png, onnx-performance.png et les rendus responsive. Elles restent
exclues de Git car certaines contiennent une image MVTec autorisée localement.

## Publication GitHub

La [liste exacte des fichiers candidats](onnx-publish-files.txt) contient les
sources, tests, dépendances, configurations, documentation, figures de benchmark,
agrégats frontend et rapports de vérification. Aucun commit ni push n’est fait.

Ne pas publier : `artifacts/onnx/`, checkpoints, données MVTec, archives locales
de preuves, captures contenant les images et dossiers de mesures brutes.
Les règles `.gitignore` excluent ces dossiers. Aucun fichier ONNX/PT/PTH/CKPT
n’est actuellement suivi par Git. Les rapports numériques PyTorch déjà suivis
restent mis à jour avec leurs empreintes réellement mesurées.

## Commandes PowerShell de contrôle

Depuis la racine du dépôt :

```powershell
docker compose config --quiet
docker compose up -d --wait --wait-timeout 300
Invoke-RestMethod http://localhost:18080/api/health
& .\.venv\Scripts\python.exe scripts/check_onnx_api.py
node frontend/scripts/onnx-qa.mjs
node frontend/scripts/browser-qa.mjs
& .\.venv\Scripts\python.exe -m pytest tests/test_onnx_export.py tests/test_backend_api.py tests/test_deployment_portability.py tests/test_compose_deployment.py -q
npm.cmd --prefix frontend test -- --maxWorkers=1
npm.cmd --prefix frontend run build
# Arrêt du projet lorsque souhaité :
docker compose down
```

Les dépendances et artefacts locaux doivent rester présents. Pour reconstruire
après un changement applicatif, suivre deployment/README.md : tout changement
Python couvert impose d’abord une vérification des preuves, puis une nouvelle
mesure uniquement si elles sont obsolètes. Le script HTTP n’accepte actuellement
aucun argument et cible localhost:18080 ; Playwright accepte UI_TEST_URL.

## Limites conservées

- T1/bottle ONNX reste volontairement refusé.
- Benchmark limité à B0/T2 dans les trois catégories ; machine partagée avec
  bruit et valeurs extrêmes observés, particulièrement dans les p95 T2.
- Frontières de chargement différentes et explicitement nommées ; aucun
  facteur de chargement ou allocation mémoire par moteur n’est revendiqué.
- RSS du processus avec les deux moteurs, pas consommation exclusive.
- Grad-CAM exige encore PyTorch ; les graphes ONNX ne produisent pas de segmentation.
- Tests navigateur Chromium, pas une certification exhaustive multi-navigateurs.
- Pas de nouvelle évaluation sur le test officiel ni de mesure de généralisation.

Les deux services restent démarrés et sains pour la démonstration.

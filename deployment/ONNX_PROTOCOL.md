# Protocole ONNX FP32 CPU — fixé avant les mesures

Référence : checkpoint full PyTorch, eval, FP32, entrée batch 1 RGB 256×256.
Le graphe AE retourne la reconstruction ; le classifieur retourne le logit.
La normalisation ImageNet reste extérieure au graphe de transfert, exactement
comme dans l’API. L’erreur L1 RGB moyenne et son top 1 % valide sont inchangés.
OpSet 18, entrée `images` float32 [1,3,256,256], sortie `reconstruction`
float32 [1,3,256,256] ou `logits` float32 [1]. Export statique, sans INT8.

Tolérances fixées avant toute nouvelle mesure :

- Tenseurs reconstruction/logits : atol=1e-4, rtol=1e-4, élément par élément.
- Cartes L1 AE : atol=1e-5, rtol=1e-4, élément par élément.
- Score : atol=1e-5, rtol=1e-4 relativement au score PyTorch.
- Un basculement de décision est justifié seulement si les DEUX scores sont
  à distance <=1e-5 du seuil original. Aucun arrondi ni marge dans la décision.
- Formes identiques, sortie FP32 et toutes les valeurs finies requises.

Validation : tous les 170 normaux originaux val, chaque modèle sur sa catégorie,
avec SHA256. Pour le transfert, toute la validation synthétique du plan figé
est ajoutée (normaux et anomalies) ; aucune image test n’est utilisée. Pas de
recalibration ni de sélection d’un export en fonction du test. Toute erreur
hors tolérance rend l’export non admissible, sans élargissement postérieur.

Benchmark séparé, séquentiel et sans autre tâche intensive lancée par l’agent :
2 threads, FP32, batch 1, 20 warm-ups et 100 mesures par moteur/condition.
Même cycle d’images val. Forward seul et entrée préparée→score sont distincts ;
chargement et Grad-CAM sont mesurés séparément. Le décodage image est exclu
du benchmark local ; un temps HTTP éventuellement mesuré est nommé séparément.
Débit séquentiel = 1000 / moyenne_ms. p95 = quantile NumPy linéaire. RSS
du processus est un instantané avec deux réseaux chargés, pas une allocation
attribuable exclusivement à un moteur. Taille checkpoint d’entraînement,
poids state_dict sérialisés et graphe d’inférence sont séparées.

Les preuves Windows/Linux PyTorch sont renouvelées APRES finalisation des
sources, par les vraies 850 comparaisons du protocole existant. Les preuves
ONNX sont distinctes, liées au graphe, checkpoint, calibration, code, manifeste
et environnement effectif, puis produites séparément sur Linux servi.

Sources techniques : [export PyTorch 2.15](https://docs.pytorch.org/docs/2.15/onnx.html),
[API ORT](https://onnxruntime.ai/docs/api/python/api_summary.html),
[threads ORT](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).

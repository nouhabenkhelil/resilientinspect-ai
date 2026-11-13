# 📊 Rapport d'Avancement de Mi-Parcours — Projet Deep Learning Avancé
> **Cycle Ingénieur en IA & Data Science — 3ème Année**  
> **Module :** Deep Learning 2 / Deep Learning Avancé  
> **Enseignant :** Haythem Ghazouani  
> **Année Universitaire :** 2026–2027  

---

## 📌 Section 1 : Fiche d'Identité et État Global du Projet

| Champ | Informations du Groupe |
| :--- | :--- |
| **Intitulé du Sujet** |ResilientInspect AI — Détection et localisation d'anomalies industrielles par autoencodeurs convolutionnels et Transfer Learning 
| **Track Métier** | Vision industrielle — CNN & Transfer Learning
| **Identifiant du Groupe** | [N&N]ResilientInspect AI
| **URL du Dépôt Git** | `https://github.com/nouhabenkhelil/resilientinspect-ai  |
| **Workspace MLflow / W&B** | http://127.0.0.1:5000/#/experiments/1/runs
| **Pourcentage d'Avancement Global** | 45 %
Données auditées et préparées ; B0 et A1 entraînés sur trois catégories ; évaluation B0 disponible localement ; T0/T1/T2 implémentés mais entraînements complets et industrialisation restants.



### Membres de l'Équipe & Rôles
1. Nouha ben khelil ( nouhebenkhelil@gmail.com )
2. Nouha briki      ( brikinouha2@gmail.com )

## 🛠️ Section 2 : Travail Déjà Réalisé (Fait & Validé)



### 2.1. Données & Versioning (DVC)
* **Dataset source :** [dataset industriel MVTec AD, (https://www.mvtec.com/research-teaching/datasets/mvtec-ad)]*
* **Volume :** Nous avons audité 1 162 images et 225 masques de défauts. Les images normales officielles d'entraînement ont été divisées en 675 images train et 170 images validation, avec une graine aléatoire fixée à 42. Les 317 images du test officiel ont été conservées sans modification.
* **Pipeline de prétraitement :** prétraitement PyTorch applique une conversion RGB, un redimensionnement avec préservation des proportions (letterbox) à 256 × 256 et une mise à l'échelle des pixels dans [0,1]. Les masques sont redimensionnés par interpolation au plus proche voisin. Des contrôles d'intégrité et de séparation des ensembles limitent le risque de fuite de données.
* **Preuve DVC :DVC non encore configuré. Les manifestes, les configurations et leurs empreintes SHA256 assurent actuellement la traçabilité des données. L'intégration DVC est programmée pour la suite.



### 2.2. Modélisation & Entraînement Deep Learning (Baseline)
Élément	     | B0      |	A1
Architecture	| Autoencodeur CNN  |	Autoencodeur CNN résiduel avec skips limités
Paramètres	| 195 107	|  2 754 371
Perte d'entraînement	| L1	  | 0,8 L1 + 0,2 DSSIM
Augmentation | 	Aucune	 |  Luminosité/contraste sur train
Optimiseur| 	Adam	    |  Adam
Learning rate|	   0,001	   |  0,001
Batch size|  	16	  |  16
Budget maximal|	20 époques	  | 20 époques
Early stopping|	 Patience 5	  |  Patience 5
Exécution |	3 entraînements complets	| 3 entraînements complets

Nous avons développé une baseline B0 pour disposer d'un modèle de référence simple et reproductible. Nous avons ensuite implémenté A1 pour étudier l'apport des blocs résiduels, des connexions de saut contrôlées et d'une perte combinant erreur pixel et similarité structurelle. Nous avons conservé les mêmes catégories, ensembles de données et principaux hyperparamètres afin de rendre les expériences comparables. Les entraînements complets ont été réalisés avec Kaggle, en raison de l'absence de GPU NVIDIA CUDA sur notre machine locale.



category,image_auroc,image_ap,image_f1,pixel_auroc,pixel_ap,dice_micro,iou_micro
bottle,0.711111111111111,0.9083742437626401,0.6666666666666666,0.7524252739997918,0.14552464697702774,0.07864995275731841,0.04093473381916456
hazelnut,0.9317857142857143,0.9622706873152496,0.7387387387387387,0.9341740761964867,0.5054197137876925,0.504390485859768,0.3372474439959166
leather,0.7479619565217392,0.9142280025396583,0.8465116279069768,0.8329733750269519,0.2013103350338791,0.13959787852455577,0.07503640041747736




### 2.3. Traçabilité MLOps (MLflow / Weights & Biases)
* Nombre total d'expériences / runs enregistrés : **`6 runs`**
Nous avons intégré MLflow pour assurer le suivi et la reproductibilité des entraînements B0 et A1. Six entraînements complets ont été réalisés sur les trois catégories. Les hyperparamètres, courbes d'apprentissage, métriques de perte et checkpoints sont enregistrés. Des captures réelles de l'interface MLflow ont été ajoutées aux annexes du rapport.

### 2.4. Services Logiciels (FastAPI & Interface Utilisateur)
Backend FastAPI :

GET /health : Non implémenté — prévu pour vérifier l'état du service.

POST /predict : Non implémenté — intégration prévue du meilleur modèle Deep Learning.

Validation des entrées/sorties via Pydantic : Non implémentée — prévue lors du développement de l'API.

Frontend (React ou Angular) :

Structure de l'interface : Non initialisée.

Composant Drag & Drop : Non développé.

Visualisation des résultats : Prévue pour afficher l'image originale, le score d'anomalie et la heatmap de localisation.

État actuel : Nous avons donné la priorité aux expérimentations Deep Learning (B0, A1 et préparation du Transfer Learning). Le développement des services logiciels est planifié après la comparaison des modèles.

---

## 📊 Tableau Synthétique d'Avancement par Composant

Composant|	Avancement estimé| Travail réalisé|	Prochaine action
Dataset & DVC|	70 %	|Audit de 1 162 images, préparation des 3 catégories, splits et manifestes SHA256 |	Configurer DVC
Modélisation DL|	80 %	B0 et A1 entraînés sur Kaggle ; T0/T1/T2 implémentés et testés	Évaluer A1 et entraîner T0/T1/T2
MLflow|	80 %	Tracking B0/A1, sauvegarde des runs, courbes, checkpoints et captures d'interface |	Consolider les comparaisons
API FastAPI|	0 %	|Architecture prévue	|Développer /health et /predict
Frontend|	0 %	|Fonctionnalités définies	|Créer l'interface de prédiction
Docker & CI/CD|	0 %	|Prévu pour la phase finale	|Dockeriser et automatiser les tests
---

## ⚠️ Section 3 : Difficultés Rencontrées, Verrous & Solutions Envisagées

Difficulté |      	Impact	|       Solution
Absence de GPU NVIDIA local|	Entraînements lents| 	Utilisation de Kaggle GPU
Compatibilité des dépendances Kaggle|	Risques d'erreurs PyTorch/CUDA|	Vérification des versions
Défauts| très petits sur leather	Localisation difficile|	Analyse EDA, métriques Dice/IoU
Risque de fuite des données|	Évaluation biaisée|	Split reproductible, test conservé
Comparaison B0/A1|	Fonctions de perte différentes|	Utilisation de métriques communes

---

## 🎯 Section 4 : Travail Restant à Accomplir (Ce qu'il reste à faire)

Nous devons finaliser l'évaluation quantitative de A1 et sa comparaison avec B0, lancer les entraînements complets des modèles Transfer Learning T0/T1/T2 sur Kaggle, puis analyser les performances sur les trois catégories industrielles. Ensuite, nous intégrerons DVC, développerons l'API FastAPI et l'interface utilisateur, avant de terminer la conteneurisation Docker et les tests finaux.



---

## 📅 Section 5 : Planning Prévisionnel Ajusté & Répartition des Tâches

### Planning Gantt Hebdomadaire (Jusqu'à la Soutenance Finale)

Semaine	Travail prévu
S+1	   Évaluation A1 et comparaison B0/A1
S+2	   Entraînement et évaluation T0/T1/T2
S+3	   DVC, FastAPI et frontend
S+4	   Docker, CI/CD, tests et démonstration



---

## Annexes : Captures d'écran et preuves d'exécution

**Annexe 1 — Suivi des expériences MLflow**

Capture réelle de l'interface MLflow montrant les entraînements B0 et A1, les hyperparamètres et les courbes de perte d'entraînement et de validation.

**Annexe 2 — Résultats de détection d'anomalies avec B0**

Visualisation d'une image MVTec AD, de sa reconstruction par l'autoencodeur B0, de la carte d'anomalie et du masque de référence.

**Annexe 3 — État actuel du développement logiciel**

Capture du code d'implémentation du Transfer Learning T0/T1/T2 ou des tests PyTorch. Les services FastAPI et frontend seront développés après finalisation des évaluations Deep Learning.
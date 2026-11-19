# Protocole fixé avant les mesures Windows/Linux

Les mesures de déploiement utilisent tous les fichiers `split=val` du manifeste
figé, normaux issus de `source_split=train`, vérifiés par SHA256. Aucun fichier
test n'intervient. Chaque checkpoint full est comparé sur toute sa catégorie,
par le même chemin d'inférence que FastAPI (batch 1, FP32 CPU, deux threads).

Politique `deployment_windows_linux_fp32_v1` : erreur de score autorisée
`1e-5 + 1e-4 * abs(score_windows)`. Un changement de décision n'est admissible
que si les deux scores sont à distance <= `1e-5` du seuil original. Ces
tolérances sont fixées avant les mesures, sans ajustement après observation.
Les seuils restent lus dans les calibrations originales, jamais recalculés.

Les rapports `deployment/reports/portability/windows.json` et `linux.json`
sont distincts des archives officielles. L'admission Linux exige le SHA256 du
rapport, de la référence Windows, de tous les codes Python scientifiques et
backend, les versions et paramètres exacts du runtime, les SHA256 des poids
et calibrations, ainsi qu'une mesure réussie pour chaque modèle. Les champs
platform/machine sont conservés comme provenance et ne remplacent pas une
preuve numérique. Sans rapport valide, le backend refuse le chargement.

Cette comparaison couvre les images normales de validation disponibles,
pas l'ensemble des entrées possibles ni une nouvelle mesure de performance
sur test. Les validations synthétiques de transfert archivées restent
vérifiées avec leurs empreintes, provenance et politique d'origine.

## R?sultat de la mesure

Les 850 comparaisons des 15 checkpoints full passent la politique pr?alable.
?cart maximal : 1.1920928955078125e-6 (T1/hazelnut). Cinq basculements de
d?cision sont observ?s ? proximit? imm?diate des seuils originaux. Ils sont
explicitement consign?s dans `linux.json`, avec les deux scores, le seuil
par mod?le et la d?cision. Aucun arrondi, marge de d?cision ou changement de
seuil n?est ajout? pour les masquer. Les scores Windows B0/A1 reproduisent
exactement les scores de validation archiv?s (?cart maximal nul).

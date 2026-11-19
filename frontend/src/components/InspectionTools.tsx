import { Wine, Nut, Layers3, Check, LoaderCircle } from 'lucide-react';
import type { Category, ModelMetadata, ModelName } from '../api/contracts';

export const architectures: Record<ModelName, { name: string; description: string }> = {
  B0: {
    name: 'Autoencodeur de référence',
    description: 'Reconstruction RGB · erreur L1 · top 1 % des pixels valides',
  },
  A1: {
    name: 'Autoencodeur amélioré',
    description: 'Reconstruction RGB · architecture enrichie · seuil val figé',
  },
  T0: {
    name: 'EfficientNet · T0',
    description: 'Transfer Learning · configuration T0 · logit anomalie',
  },
  T1: {
    name: 'EfficientNet · T1',
    description: 'Transfer Learning · configuration T1 · logit anomalie',
  },
  T2: { name: 'EfficientNet · T2', description: 'Transfer Learning · configuration T2 · Grad-CAM' },
};
export const categoryIcons = { bottle: Wine, hazelnut: Nut, leather: Layers3 };
export const categoryLabels = { bottle: 'Bouteille', hazelnut: 'Noisette', leather: 'Cuir' };
export function CategoryCards({
  selected,
  disabled,
  onSelect,
}: {
  selected: Category;
  disabled: boolean;
  onSelect: (category: Category) => void;
}) {
  return (
    <div className="inspection-categories" aria-label="Catégories visuelles">
      {(['bottle', 'hazelnut', 'leather'] as const).map((category) => {
        const Glyph = categoryIcons[category];
        return (
          <button
            key={category}
            disabled={disabled}
            aria-pressed={selected === category}
            onClick={() => onSelect(category)}
          >
            <Glyph size={26} strokeWidth={1.4} />
            <span>{categoryLabels[category]}</span>
          </button>
        );
      })}
    </div>
  );
}
export function ModelCards({
  available,
  selected,
  disabled,
  onSelect,
}: {
  category: Category;
  available: ModelMetadata[];
  selected?: string;
  disabled: boolean;
  onSelect: (model: ModelName) => void;
}) {
  return (
    <div className="model-cards" aria-label="Architectures disponibles">
      {(Object.keys(architectures) as ModelName[]).map((name) => {
        const model = available.find((m) => m.model === name);
        return (
          <button
            type="button"
            key={name}
            disabled={disabled || !model}
            aria-pressed={selected === name}
            title={architectures[name].description}
            onClick={() => onSelect(name)}
          >
            <span className="model-symbol">{name}</span>
            <span>
              {name.startsWith('T') ? 'EfficientNet-B0' : 'Autoencodeur'}
              <small>{model ? 'Disponible' : 'Indisponible'}</small>
            </span>
            {selected === name && <Check size={16} />}
          </button>
        );
      })}
    </div>
  );
}
export function Pipeline({
  validating,
  ready,
  stage,
  received,
  explained,
}: {
  validating: boolean;
  ready: boolean;
  stage: string;
  received: boolean;
  explained: boolean;
}) {
  const completed = [ready, ready, received, received, explained];
  const active = validating ? 0 : stage === 'predict' ? 2 : stage === 'visualize' ? 4 : -1;
  return (
    <ol className="pipeline" aria-label="Événements de l’inspection">
      {[
        'Validation locale',
        'Image prête à envoyer',
        'Requête d’inférence',
        'Résultat reçu',
        'Explication reçue',
      ].map((label, index) => (
        <li
          key={label}
          className={completed[index] ? 'complete' : active === index ? 'active' : ''}
        >
          {completed[index] ? (
            <Check size={15} />
          ) : active === index ? (
            <LoaderCircle className="spinner-icon" size={15} />
          ) : (
            <span className="pipeline-dot" />
          )}
          <span>{label}</span>
        </li>
      ))}
    </ol>
  );
}

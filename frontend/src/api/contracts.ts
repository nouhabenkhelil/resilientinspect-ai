// Contrats de backend/app/schemas.py. Les noms restent ceux de FastAPI.
export const CATEGORIES = ['bottle', 'hazelnut', 'leather'] as const;
export const MODEL_NAMES = ['B0', 'A1', 'T0', 'T1', 'T2'] as const;
export type Category = (typeof CATEGORIES)[number];
export type ModelName = (typeof MODEL_NAMES)[number];

export interface Health {
  status: 'ok' | 'degraded';
  version: string;
  device: 'cpu';
  ready_models: number;
  expected_models: number;
  request_id: string;
}
export interface ModelMetadata {
  model: ModelName;
  category: Category;
  version: string;
  checkpoint_sha256: string;
  calibration_sha256: string;
  threshold: number;
  seed: number | null;
  input_size: number[];
  normalization: string;
  score: string;
  decision_rule: 'score > threshold';
  explanation: 'reconstruction_error' | 'gradcam';
  training_environment: Record<string, unknown> | null;
  serving_environment: Record<string, unknown>;
  compatibility_report_sha256: string | null;
}
export interface Metadata {
  models: ModelMetadata[];
  unavailable: { model: ModelName; category: Category; reason: string }[];
  request_id: string;
}
export interface Prediction {
  category: Category;
  model: ModelName;
  version: string;
  anomaly_score: number;
  threshold: number;
  decision: 'normal' | 'anomaly';
  inference_time_ms: number;
  request_id: string;
}
export interface Visualization {
  kind: 'reconstruction_error' | 'gradcam';
  description: string;
  width: number;
  height: number;
  coordinate_space: 'letterbox_256';
  padding_top_bottom_left_right: number[];
  original_height_width: number[];
  scale: string;
  is_segmentation: boolean;
  image_png_base64: string;
  heatmap_png_base64: string;
  overlay_png_base64: string;
}
export interface VisualizedPrediction extends Prediction {
  visualization: Visualization;
}
export interface InspectionInput {
  file: File;
  category: Category;
  model: ModelName;
}

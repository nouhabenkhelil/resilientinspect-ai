import {
  CATEGORIES,
  MODEL_NAMES,
  type ModelMetadata,
  type Prediction,
  type VisualizedPrediction,
} from '../api/contracts';

export const requestId = 'fb01fe44-e566-4616-af79-e7ca169de81b';
export const models: ModelMetadata[] = CATEGORIES.flatMap((category) =>
  MODEL_NAMES.map((model) => ({
    model,
    category,
    version: 'a'.repeat(64),
    checkpoint_sha256: 'a'.repeat(64),
    calibration_sha256: 'b'.repeat(64),
    threshold: 0.0134567,
    seed: model.startsWith('T') ? 42 : null,
    input_size: [256, 256],
    normalization: 'RGB [0,1]',
    score: model.startsWith('T')
      ? 'sigmoid_anomaly_logit'
      : 'rgb_mean_absolute_error_top_1_percent_valid_pixels',
    decision_rule: 'score > threshold',
    explanation: model.startsWith('T') ? 'gradcam' : 'reconstruction_error',
    training_environment: null,
    serving_environment: {},
    compatibility_report_sha256: null,
  })),
);
export const health = {
  status: 'ok',
  version: '0.1.0',
  device: 'cpu',
  ready_models: 15,
  expected_models: 15,
  request_id: requestId,
};
export const metadata = { models, unavailable: [], request_id: requestId };
export const prediction: Prediction = {
  category: 'bottle',
  model: 'B0',
  version: 'a'.repeat(64),
  anomaly_score: 0.0345678,
  threshold: 0.0134567,
  decision: 'anomaly',
  inference_time_ms: 42.7,
  request_id: requestId,
};
const png =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jM1sAAAAASUVORK5CYII=';
export function visualization(result: Prediction = prediction): VisualizedPrediction {
  return {
    ...result,
    request_id: 'c8367d36-7831-4e92-9159-a9b559975841',
    visualization: {
      kind: result.model.startsWith('T') ? 'gradcam' : 'reconstruction_error',
      description: 'Explication de test',
      width: 256,
      height: 256,
      coordinate_space: 'letterbox_256',
      padding_top_bottom_left_right: [0, 0, 64, 64],
      original_height_width: [512, 256],
      scale: result.model.startsWith('T') ? 'relative_per_image_0_1' : 'absolute_l1_0_1',
      is_segmentation: false,
      image_png_base64: png,
      heatmap_png_base64: png,
      overlay_png_base64: png,
    },
  };
}

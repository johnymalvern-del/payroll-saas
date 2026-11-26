/**
 * Face embedding via face-api.js.
 *
 * The model runs in the browser and produces a 128-float descriptor. Only that
 * descriptor is sent to the server -- the image never leaves the device. That
 * is deliberate and is the strongest privacy property in this whole feature:
 * policy section 1 forbids retaining facial photographs, and the architecture
 * means there is nothing to retain.
 *
 * What this does NOT do: liveness. A photograph of a face yields a valid
 * descriptor and will match. Documented rather than hidden.
 *
 * Model files must be served from public/models. Install:
 *
 *     npm install @vladmandic/face-api
 *     # then copy the model weights, see MODEL_SETUP below
 */
import * as faceapi from "@vladmandic/face-api";

export const VENDOR = "face-embedding";
export const TEMPLATE_VERSION = "face-api-128-v1";
export const EMBEDDING_DIMS = 128;

const MODEL_BASE = "/models";

let loadPromise: Promise<void> | null = null;

/**
 * Load the three networks, once per page.
 *
 * Cached as a promise rather than a boolean so concurrent calls wait on the
 * same download instead of each starting their own.
 */
export function loadModels(): Promise<void> {
  if (loadPromise) return loadPromise;
  loadPromise = (async () => {
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_BASE),
      faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_BASE),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_BASE),
    ]);
  })();
  // A failed load must not be cached forever, or a flaky network would break
  // the page until reload.
  loadPromise.catch(() => {
    loadPromise = null;
  });
  return loadPromise;
}

export type CaptureResult =
  | { ok: true; descriptor: Float32Array }
  | { ok: false; reason: "no_face" | "multiple_faces" | "model_error" };

/**
 * Detect one face and compute its descriptor.
 *
 * Returns a result rather than throwing: "no face in frame" is a normal state
 * an employee will hit constantly while positioning themselves, not an error.
 */
export async function captureEmbedding(
  video: HTMLVideoElement,
): Promise<CaptureResult> {
  try {
    await loadModels();
    const results = await faceapi
      .detectAllFaces(video, new faceapi.TinyFaceDetectorOptions())
      .withFaceLandmarks()
      .withFaceDescriptors();

    if (results.length === 0) return { ok: false, reason: "no_face" };
    if (results.length > 1) return { ok: false, reason: "multiple_faces" };

    return { ok: true, descriptor: results[0].descriptor };
  } catch {
    return { ok: false, reason: "model_error" };
  }
}

/**
 * Float32Array to base64 for JSON transport, little-endian.
 *
 * A Float32Array's buffer is platform-endian. The server unpacks "<128f", so on
 * a big-endian host this would produce garbage scores rather than an error.
 * No current browser is big-endian, but writing through a DataView makes the
 * contract explicit instead of relying on that.
 */
export function embeddingToBase64(descriptor: Float32Array): string {
  const view = new DataView(new ArrayBuffer(descriptor.length * 4));
  for (let i = 0; i < descriptor.length; i++) {
    view.setFloat32(i * 4, descriptor[i], true);
  }
  const bytes = new Uint8Array(view.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function embeddingByteLength(): number {
  return EMBEDDING_DIMS * 4;
}

/**
 * MODEL_SETUP
 *
 * face-api.js needs weight files at /public/models. Fetch them with:
 *
 *   cd frontend/public
 *   mkdir models && cd models
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/tiny_face_detector_model-weights_manifest.json
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/tiny_face_detector_model-shard1
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/face_landmark_68_model-weights_manifest.json
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/face_landmark_68_model-shard1
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/face_recognition_model-weights_manifest.json
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/face_recognition_model-shard1
 *   curl -O https://raw.githubusercontent.com/vladmandic/face-api/master/model/face_recognition_model-shard2
 */
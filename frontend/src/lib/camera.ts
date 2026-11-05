export type CameraHandle = {
  stop: () => void;
  captureJpegBase64: (quality?: number) => string;
};

export async function startCamera(
  video: HTMLVideoElement,
): Promise<CameraHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: 640, height: 480 },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();
  const canvas = document.createElement("canvas");
  return {
    stop() {
      stream.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
    },
    captureJpegBase64(quality = 0.7) {
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("canvas_unsupported");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", quality);
      const idx = dataUrl.indexOf(",");
      return idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl;
    },
  };
}

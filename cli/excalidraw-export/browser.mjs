import { exportToCanvas } from "@excalidraw/excalidraw";

window.renderScene = async ({ scene, region, scale, maxPixels }) => {
  let bounds;
  const canvas = await exportToCanvas({
    elements: scene.elements,
    files: scene.files ?? {},
    appState: { ...scene.appState, exportBackground: true, exportEmbedScene: false },
    exportPadding: 0,
    getDimensions(width, height) {
      const pixelWidth = Math.ceil(width * scale);
      const pixelHeight = Math.ceil(height * scale);
      if (pixelWidth > 32767 || pixelHeight > 32767 || pixelWidth * pixelHeight > maxPixels) {
        throw new Error(`Scene canvas ${pixelWidth}x${pixelHeight} exceeds the configured limit. Reduce --scale or use a smaller scene.`);
      }
      bounds = { width, height };
      return { width: pixelWidth, height: pixelHeight, scale };
    },
  });
  await document.fonts.ready;
  const failedFonts = [...document.fonts].filter(font => font.status === "error");
  if (failedFonts.length) throw new Error(`Font loading failed: ${failedFonts.map(font => font.family).join(", ")}`);
  let output = canvas;
  if (region) {
    // Region coordinates are relative to the exported scene's top-left, not the viewport.
    output = document.createElement("canvas");
    output.width = Math.ceil(region.width * scale);
    output.height = Math.ceil(region.height * scale);
    const context = output.getContext("2d");
    context.fillStyle = scene.appState?.viewBackgroundColor ?? "#ffffff";
    context.fillRect(0, 0, output.width, output.height);
    context.drawImage(canvas, -region.x * scale, -region.y * scale);
  }
  const blob = await new Promise(resolve => output.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Chromium could not encode this canvas as PNG");
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
  return {
    data,
    width: output.width,
    height: output.height,
    sceneWidth: bounds.width,
    sceneHeight: bounds.height,
    fonts: [...document.fonts].filter(font => font.status === "loaded").map(font => font.family),
  };
};

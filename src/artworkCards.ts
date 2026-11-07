import type { ArtworkRole } from "./backend";

export const artworkSlots: Record<ArtworkRole, [number, number, number]> = {
  portrait: [0, 600, 900], hero: [1, 1920, 620], logo: [2, 960, 320], landscape: [3, 920, 430],
};

export function iconHue(icon: HTMLImageElement) {
  const sample = document.createElement("canvas");
  sample.width = sample.height = 24;
  const context = sample.getContext("2d", { willReadFrequently: true });
  if (!context) return 215;
  context.drawImage(icon, 0, 0, 24, 24);
  const pixels = context.getImageData(0, 0, 24, 24).data;
  const hues = Array<number>(12).fill(0);
  for (let i = 0; i < pixels.length; i += 4) {
    const [r, g, b, alpha] = pixels.subarray(i, i + 4);
    const max = Math.max(r, g, b);
    const chroma = max - Math.min(r, g, b);
    if (alpha < 192 || max < 52 || chroma < 32) continue;
    const hue = max === r ? (g - b) / chroma : max === g ? 2 + (b - r) / chroma : 4 + (r - g) / chroma;
    hues[Math.floor((hue * 2 + 12) % 12)] += chroma;
  }
  const weight = Math.max(...hues);
  return weight ? hues.indexOf(weight) * 30 + 15 : 215;
}

function drawIcon(context: CanvasRenderingContext2D, icon: HTMLImageElement, x: number, y: number, size: number) {
  context.save();
  context.beginPath();
  context.roundRect(x, y, size, size, size * 0.22);
  context.fillStyle = "#141c29";
  context.fill();
  context.clip();
  const padding = size * 0.08;
  const ratio = (size - padding * 2) / Math.max(icon.naturalWidth, icon.naturalHeight);
  const w = icon.naturalWidth * ratio;
  const h = icon.naturalHeight * ratio;
  context.drawImage(icon, x + (size - w) / 2, y + (size - h) / 2, w, h);
  context.restore();
  context.strokeStyle = "#ffffff33";
  context.lineWidth = 2;
  context.stroke();
}

function drawTitle(context: CanvasRenderingContext2D, name: string, x: number, y: number, width: number, size: number, align: CanvasTextAlign) {
  context.font = `bold ${size}px system-ui, sans-serif`;
  context.textAlign = align;
  context.textBaseline = "middle";
  context.fillStyle = "#f7f9ff";
  context.shadowColor = "#050810bb";
  context.shadowBlur = size * 0.12;
  const text = name.trim().replace(/\s+/g, " ").slice(0, 256);
  const fits = (line: string) => context.measureText(line).width <= width;
  if (fits(text)) {
    context.fillText(text, x, y);
    return;
  }
  const words = text.split(" ");
  let first = words.shift() || "";
  while (words.length && fits(first + " " + words[0])) first += " " + words.shift();
  const ellipsis = (line: string) => {
    if (fits(line)) return line;
    const characters = Array.from(line);
    while (characters.length && !fits(characters.join("") + "…")) characters.pop();
    return characters.join("").trimEnd() + "…";
  };
  const second = words.join(" ");
  context.fillText(ellipsis(first), x, second ? y - size * 0.58 : y);
  if (second) context.fillText(ellipsis(second), x, y + size * 0.58);
}

export function renderArtwork(role: ArtworkRole, name: string, icon: HTMLImageElement, hue: number) {
  const [, width, height] = artworkSlots[role];
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Artwork canvas is unavailable");
  if (role === "logo") {
    drawTitle(context, name, 24, height / 2, width - 48, 112, "left");
  } else {
    const portrait = role === "portrait";
    const hero = role === "hero";
    const size = portrait ? 258 : hero ? 306 : 184;
    const x = portrait ? (width - size) / 2 : hero ? width * 0.72 : 68;
    const y = portrait ? 206 : (height - size) / 2;
    const base = context.createLinearGradient(0, 0, width, height);
    base.addColorStop(0, `hsl(${hue} 34% 18%)`);
    base.addColorStop(1, "#0c111e");
    context.fillStyle = base;
    context.fillRect(0, 0, width, height);
    const light = context.createRadialGradient(x + size / 2, y + size / 2, 0, x + size / 2, y + size / 2, size * 1.8);
    light.addColorStop(0, `hsl(${hue} 72% 57% / 0.58)`);
    light.addColorStop(1, `hsl(${hue} 72% 57% / 0)`);
    context.fillStyle = light;
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "#ffffff20";
    context.lineWidth = 2;
    context.beginPath();
    context.roundRect(20, 20, width - 40, height - 40, 28);
    context.stroke();
    drawIcon(context, icon, x, y, size);
    if (portrait) drawTitle(context, name, width / 2, 570, width - 100, 53, "center");
    if (role === "landscape") drawTitle(context, name, 300, height / 2, width - 368, 54, "left");
  }
  return canvas.toDataURL("image/png").split(",")[1];
}

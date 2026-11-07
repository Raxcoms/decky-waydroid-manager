import type { ArtworkRole } from "./backend";

export const artworkSlots: Record<ArtworkRole, [number, number, number]> = {
  portrait: [0, 600, 900], hero: [1, 1920, 620], landscape: [3, 920, 430],
};

export function iconBackground(icon: HTMLImageElement): [string, string] {
  const sample = document.createElement("canvas");
  sample.width = sample.height = 32;
  const context = sample.getContext("2d", { willReadFrequently: true });
  if (!context) return ["#292929", "#171717"];
  context.drawImage(icon, 0, 0, sample.width, sample.height);
  const pixels = context.getImageData(0, 0, sample.width, sample.height).data;
  const colors = new Map<number, { count: number; red: number; green: number; blue: number }>();
  let dominant = { count: 0, red: 0, green: 0, blue: 0 };
  for (let i = 0; i < pixels.length; i += 4) {
    const [r, g, b, alpha] = pixels.subarray(i, i + 4);
    if (alpha < 192) continue;
    // Group nearby colors so antialiasing does not split the dominant color.
    const key = ((r >> 5) * 8 + (g >> 5)) * 8 + (b >> 5);
    const color = colors.get(key) ?? { count: 0, red: 0, green: 0, blue: 0 };
    color.count++;
    color.red += r;
    color.green += g;
    color.blue += b;
    colors.set(key, color);
    if (color.count > dominant.count) dominant = color;
  }
  if (!dominant.count) return ["#292929", "#171717"];

  const scale = dominant.count * 255;
  const red = dominant.red / scale;
  const green = dominant.green / scale;
  const blue = dominant.blue / scale;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const chroma = max - min;
  const lightness = (max + min) / 2;
  const hue = chroma === 0 ? 0 : max === red ? (green - blue) / chroma : max === green ? 2 + (blue - red) / chroma : 4 + (red - green) / chroma;
  const saturation = chroma ? Math.min(100, 100 * chroma / (1 - Math.abs(2 * lightness - 1)) + 8) : 0;
  const top = Math.max(6, Math.min(22, lightness * 38));
  const bottom = top * 0.66;
  return [`hsl(${hue * 60} ${saturation}% ${top}%)`, `hsl(${hue * 60} ${saturation}% ${bottom}%)`];
}

function drawIcon(context: CanvasRenderingContext2D, icon: HTMLImageElement, x: number, y: number, size: number) {
  context.save();
  context.beginPath();
  context.roundRect(x, y, size, size, size * 0.22);
  context.fillStyle = "#00000026";
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

export function renderArtwork(role: ArtworkRole, name: string, icon: HTMLImageElement, background: [string, string]) {
  const [, width, height] = artworkSlots[role];
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Artwork canvas is unavailable");
  const portrait = role === "portrait";
  const hero = role === "hero";
  const size = portrait ? 258 : hero ? 306 : 184;
  const x = portrait ? (width - size) / 2 : hero ? width * 0.72 : 68;
  const y = portrait ? 206 : (height - size) / 2;
  const base = context.createLinearGradient(0, 0, width, height);
  base.addColorStop(0, background[0]);
  base.addColorStop(1, background[1]);
  context.fillStyle = base;
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "#ffffff20";
  context.lineWidth = 2;
  context.beginPath();
  context.roundRect(20, 20, width - 40, height - 40, 28);
  context.stroke();
  drawIcon(context, icon, x, y, size);
  if (portrait) drawTitle(context, name, width / 2, 570, width - 100, 53, "center");
  if (role === "landscape") drawTitle(context, name, 300, height / 2, width - 368, 54, "left");
  return canvas.toDataURL("image/png").split(",")[1];
}

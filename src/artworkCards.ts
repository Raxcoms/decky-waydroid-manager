import type { ArtworkRole } from "./backend";

export const artworkSlots: Record<ArtworkRole, [number, number, number]> = {
  portrait: [0, 600, 900], hero: [1, 1920, 620], landscape: [3, 920, 430],
};
const artworkScale = 2;

export function iconBackground(icon: HTMLImageElement): [string, string] {
  const sample = document.createElement("canvas");
  sample.width = sample.height = 32;
  const context = sample.getContext("2d", { willReadFrequently: true });
  if (!context) return ["#292929", "#171717"];
  context.drawImage(icon, 0, 0, sample.width, sample.height);
  const pixels = context.getImageData(0, 0, sample.width, sample.height).data;
  const colors = new Map<number, { count: number; red: number; green: number; blue: number }>();
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
  }
  const palette = [...colors.values()];
  const colorful = palette.filter(color =>
    Math.max(color.red, color.green, color.blue) - Math.min(color.red, color.green, color.blue) >= color.count * 24);
  const dominant = (colorful.length ? colorful : palette).reduce((best, color) =>
    color.count > best.count ? color : best, { count: 0, red: 0, green: 0, blue: 0 });
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
  const saturation = chroma ? Math.min(100, Math.max(60, 100 * chroma / (1 - Math.abs(2 * lightness - 1)) + 20)) : 0;
  const top = Math.max(18, Math.min(32, lightness * 48));
  const bottom = top * 0.66;
  return [`hsl(${hue * 60} ${saturation}% ${top}%)`, `hsl(${hue * 60} ${saturation}% ${bottom}%)`];
}

function drawIcon(context: CanvasRenderingContext2D, icon: HTMLImageElement, x: number, y: number, size: number) {
  const padding = size * 0.08;
  const ratio = (size - padding * 2) / Math.max(icon.naturalWidth, icon.naturalHeight);
  const w = icon.naturalWidth * ratio;
  const h = icon.naturalHeight * ratio;
  context.drawImage(icon, x + (size - w) / 2, y + (size - h) / 2, w, h);
}

function titleLines(context: CanvasRenderingContext2D, name: string, width: number) {
  const text = name.trim().replace(/\s+/g, " ").slice(0, 256);
  const fits = (line: string) => context.measureText(line).width <= width;
  if (fits(text)) return [text];
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
  return second ? [ellipsis(first), ellipsis(second)] : [ellipsis(first)];
}

function drawTitle(context: CanvasRenderingContext2D, lines: string[], x: number, y: number, lineHeight: number, align: CanvasTextAlign) {
  context.textAlign = align;
  context.textBaseline = "middle";
  context.fillStyle = "#f7f9ff";
  context.shadowColor = "#050810bb";
  context.shadowBlur = lineHeight * 0.1;
  lines.forEach((line, index) => context.fillText(line, x, y + (index - (lines.length - 1) / 2) * lineHeight));
}

export function renderArtwork(role: ArtworkRole, name: string, icon: HTMLImageElement, background: [string, string]) {
  const [, width, height] = artworkSlots[role];
  const canvas = document.createElement("canvas");
  canvas.width = width * artworkScale;
  canvas.height = height * artworkScale;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Artwork canvas is unavailable");
  context.scale(artworkScale, artworkScale);
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  const base = context.createLinearGradient(0, 0, width, height);
  base.addColorStop(0, background[0]);
  base.addColorStop(1, background[1]);
  context.fillStyle = "#171717";
  context.fillRect(0, 0, width, height);
  context.save();
  const blur = Math.min(width, height) * 0.08;
  const scale = Math.max((width + blur * 6) / icon.naturalWidth, (height + blur * 6) / icon.naturalHeight);
  const backgroundWidth = icon.naturalWidth * scale;
  const backgroundHeight = icon.naturalHeight * scale;
  context.filter = `grayscale(1) blur(${blur * artworkScale}px) brightness(0.5) contrast(0.65)`;
  context.drawImage(icon, (width - backgroundWidth) / 2, (height - backgroundHeight) / 2, backgroundWidth, backgroundHeight);
  context.filter = "none";
  context.globalCompositeOperation = "color";
  context.fillStyle = base;
  context.fillRect(0, 0, width, height);
  context.globalCompositeOperation = "source-over";
  context.globalAlpha = 0.6;
  context.fillRect(0, 0, width, height);
  context.restore();

  if (role === "hero") {
    drawIcon(context, icon, (width - 306) / 2, (height - 306) / 2, 306);
  } else {
    const portrait = role === "portrait";
    const iconSize = portrait ? 258 : 184;
    const fontSize = portrait ? 53 : 54;
    const gap = portrait ? 56 : 36;
    const lineHeight = fontSize * 1.16;
    context.font = `bold ${fontSize}px system-ui, sans-serif`;
    const lines = titleLines(context, name, portrait ? width - 100 : width - iconSize - gap - 136);
    if (portrait) {
      const titleHeight = fontSize + (lines.length - 1) * lineHeight;
      const top = (height - iconSize - gap - titleHeight) / 2;
      drawIcon(context, icon, (width - iconSize) / 2, top, iconSize);
      drawTitle(context, lines, width / 2, top + iconSize + gap + titleHeight / 2, lineHeight, "center");
    } else {
      const titleWidth = Math.max(...lines.map((line) => context.measureText(line).width));
      const left = (width - iconSize - gap - titleWidth) / 2 - 24;
      drawIcon(context, icon, left, (height - iconSize) / 2, iconSize);
      drawTitle(context, lines, left + iconSize + gap, height / 2, lineHeight, "left");
    }
  }
  return canvas.toDataURL("image/png").split(",")[1];
}

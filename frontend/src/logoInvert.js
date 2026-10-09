// Decides whether a logo should be colour-inverted on the dark theme. Pure (pixels in, boolean out) so it can be tested.
//
// Inversion exists for ONE kind of logo: dark, neutral line-art on a transparent background (black ink that would
// vanish on a dark page). It wrecks anything else: a full-colour badge with a black ring (red turns pink, white turns
// black) is "mostly dark" too, but it is colourful. So both must hold: mostly dark AND almost no colour.
export const DARK_MEAN_LUMA = 100;     // average brightness of the visible pixels, 0-255
export const MAX_COLOUR_SHARE = 0.1;   // share of visible pixels that are clearly coloured
const CHROMA = 50;                     // max(r,g,b) - min(r,g,b) above this counts as "coloured"

/** @param {ArrayLike<number>} data RGBA bytes, e.g. ImageData.data */
export function logoNeedsInvertFromPixels(data) {
  let total = 0, count = 0, coloured = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 10) continue;                       // skip transparent pixels
    const r = data[i], g = data[i + 1], b = data[i + 2];
    total += 0.299 * r + 0.587 * g + 0.114 * b;
    if (Math.max(r, g, b) - Math.min(r, g, b) > CHROMA) coloured++;
    count++;
  }
  if (!count) return false;
  return total / count < DARK_MEAN_LUMA && coloured / count < MAX_COLOUR_SHARE;
}

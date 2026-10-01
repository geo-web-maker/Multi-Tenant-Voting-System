// Shrinks big phone photos before upload (WP-6d). Any failure returns the ORIGINAL file: resizing is an
// optimisation and must never block an application.
const MIN_BYTES = 1024 * 1024;   // under 1 MB: leave it alone
const RESIZABLE = new Set(['image/jpeg', 'image/png', 'image/webp']);   // GIF would lose its animation

/** Scale (w, h) down so the longest side is at most `max`. Never scales up. */
export function fitWithin(w, h, max) {
  if (!(w > 0) || !(h > 0) || !(max > 0)) return { width: Math.max(1, Math.round(w) || 1), height: Math.max(1, Math.round(h) || 1) };
  const longest = Math.max(w, h);
  if (longest <= max) return { width: Math.round(w), height: Math.round(h) };
  const k = max / longest;
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) };
}

export async function resizeImage(file, { maxSide = 1600, quality = 0.8 } = {}) {
  try {
    if (!file || !RESIZABLE.has(file.type) || file.size < MIN_BYTES) return file;
    const bitmap = await createImageBitmap(file);
    try {
      const { width, height } = fitWithin(bitmap.width, bitmap.height, maxSide);
      const canvas = document.createElement('canvas');
      canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';            // JPEG has no transparency
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(bitmap, 0, 0, width, height);
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', quality));
      if (!blob || blob.size >= file.size) return file;   // no gain: keep the original
      const name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
      return new File([blob], name, { type: 'image/jpeg', lastModified: file.lastModified });
    } finally {
      bitmap.close?.();
    }
  } catch {
    return file;
  }
}

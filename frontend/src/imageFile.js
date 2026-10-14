// Client-side check for uploaded images (guide 4.4 gaps 1-2). The backend accepts only JPEG, PNG, WEBP and GIF up
// to 5 MB; checking here means a bad file fails instantly instead of after a long upload on a slow connection.
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const ACCEPT_IMAGES = 'image/jpeg,image/png,image/webp,image/gif';
const ALLOWED_TYPES = new Set(ACCEPT_IMAGES.split(','));
const ALLOWED_EXT = /\.(jpe?g|png|webp|gif)$/i;

/** @returns {string} an error message for the voter, or '' when the file is fine */
export function validateImageFile(file) {
  if (!file) return '';
  // Some Android browsers report an empty type; fall back to the extension in that case only.
  const typeOk = file.type ? ALLOWED_TYPES.has(file.type) : ALLOWED_EXT.test(file.name || '');
  if (!typeOk) return 'That file type is not supported. Use a JPEG, PNG, WEBP or GIF image (PDF and HEIC are not accepted).';
  if (file.size > MAX_IMAGE_BYTES) {
    return `That image is ${(file.size / 1048576).toFixed(1)} MB. The limit is 5 MB. Take the photo again at a lower quality, or use a smaller screenshot.`;
  }
  return '';
}

/** Copy a picked file into memory right away. On Android a picked file is only a handle to the original, which can go
 *  dead after the browser is backgrounded (camera, WhatsApp, mobile-money app) and then every upload fails with no
 *  response. An in-memory copy keeps name, type, size and lastModified, so fileKey() and the upload cache still match.
 *  @returns {Promise<File|null>} null when the file cannot be read; the original when this browser cannot read files at all */
const readBytes = (file) => {
  if (typeof file.arrayBuffer === 'function') return file.arrayBuffer();
  if (typeof FileReader === 'undefined') return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsArrayBuffer(file);
  });
};
export async function snapshotFile(file) {
  try {
    const buf = await readBytes(file);
    if (!buf) return file;
    if (!buf.byteLength && file.size) return null;
    return new File([buf], file.name, { type: file.type, lastModified: file.lastModified });
  } catch {
    return null;
  }
}

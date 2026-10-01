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

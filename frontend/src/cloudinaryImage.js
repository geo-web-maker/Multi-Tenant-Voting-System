// Face-aware cropping for candidate/applicant photos.
//
// People upload photos framed all sorts of ways — off-center, half-body,
// landscape — and a plain CSS `object-fit: cover` crops from the geometric
// center, which regularly cuts off foreheads or chins. Cloudinary (already
// used for every photo upload in this app — see /apply/upload-image and
// /admin/upload-image) can detect the face server-side and crop around it
// instead, with no extra ML/AI code of our own to write or maintain.
//
// This only rewrites the delivery URL — no re-upload, no backend change.
// `g_face` centers on the detected face; `z` (zoom) controls how tight that
// crop is: 1.0 fills the frame with just the face, lower values pull back
// to include more head-room/shoulders. We default to a headshot-with-some-
// margin look rather than an all-face crop.
//
// width/height are the CSS pixel size the image will actually render at;
// we request 2x that from Cloudinary for retina screens.

const FACE_ZOOM_DEFAULT = 0.75; // <1 = don't fill the frame with just the face

/**
 * Build a face-centered, cropped Cloudinary URL for a given display size.
 * Falls back to the original URL untouched for anything that isn't a
 * Cloudinary delivery URL (e.g. a local blob: preview before upload, or a
 * missing/empty image_url) so it's always safe to call.
 */
export function faceCropUrl(url, width, height, { zoom = FACE_ZOOM_DEFAULT } = {}) {
  if (!url || typeof url !== 'string') return url;
  const marker = '/upload/';
  const idx = url.indexOf(marker);
  if (idx === -1) return url; // not a Cloudinary delivery URL — leave it alone

  const w = Math.round(width * 2);
  const h = Math.round(height * 2);
  const transform = `c_fill,g_face,z_${zoom},w_${w},h_${h},q_auto,f_auto`;
  const insertAt = idx + marker.length;
  return url.slice(0, insertAt) + transform + '/' + url.slice(insertAt);
}

# Lane B — B1 + B2 + B3 + B4 (done in one pass, one file)
status: done
branch: improvements/B-all (cut from improvements/A1)
tests added: src/applyErrors.test.js (19), src/imageResize.test.js (7), src/components/ApplicantPortal.apply.test.jsx (15)
results: backend 293 passed · frontend 254 passed (213 + 41) · lint 0 · vite build OK (ApplicantPortal chunk 22.4 KB)
B1: `applyErrors.js` (`mapApplyError`, `missingFields`, block reasons); one validation pass listing every missing field, `aria-invalid` + red border, focus/scroll to the first; registration number trimmed + uppercased before sending. Tests A1, A2, A3, A5.
B2: step labels (n/4, or n/3 with no photo), upload percent via `onUploadProgress`, `beforeunload` while busy, slow-connection note, Cancel via `AbortController`, fields inert (`fieldset disabled`), button `aria-busy`. Tests A4, A7 + percent, beforeunload, slow, cancel.
B3: `uploadedRef` keyed by name+size+lastModified, so a retry skips files already uploaded; "Re-attach your receipt" when a draft is restored. Tests A6, A8.
B4: `imageResize.js` (`fitWithin`, `resizeImage`), one call site in the upload helper; any failure returns the original.
mutation-checked: removing the upload cache, the busy guard, the fieldset, the uppercase, the abort signal, or the click guard each makes tests fail.
deviations: see deviations/B-all.md (message table missing from zip; submit_blocked reasons not recorded yet; api:slow not emitted).
HUMAN: real Android Chrome incl. HEIC/AVIF phones (B4); the ~96 px bottom padding for the Help `?` on the apply container is still not added (noted in A2); wording of the error messages vs the guide's §4.4 table; Cancel and the percent on a throttled 3G connection.

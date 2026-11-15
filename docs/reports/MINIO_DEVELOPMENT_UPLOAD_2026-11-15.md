# Current MinIO development upload verification

The user requested uploads on the existing MinIO deployment. Added an explicit
`S3_SERVER_SIDE_ENCRYPTION` setting and enabled `none` in the private local
development `.env`. The endpoints, bucket, credentials, and server license were
retained. Original and processed image objects are stored without application-
requested server-side encryption in this mode. AES256 is the default, and
staging/production configuration rejects `none`; there is no automatic fallback.

The API was reloaded and the idle ARQ worker restarted to apply the same mode.

## Live checks

- Browser upload CORS preflight: HTTP 204.
- Public presigned PNG PUT: HTTP 200; internal readback matched exact bytes.
- Worker-style processed JPEG write/read: exact byte match.
- Public signed JPEG GET: HTTP 200; exact byte match.
- Both temporary diagnostic object paths were cleaned up.
- Uploaded the generated `healthy-01.png` through the running web/API flow:
  upload returned HTTP 200 and completion returned HTTP 202.
- Verification scan `30e3cab9-79de-4989-92c0-43403aed8947` reached the worker,
  which saved a normalized JPEG (267,764 bytes) in the same MinIO bucket.
  Its final status was `rejected` by the AI image gate, with a diagnosis record
  and no storage failure. Successful storage does not establish that a synthetic
  image is suitable for diagnosis. This diagnostic scan was retained as evidence.

## Checks

115 API tests passed, including both storage modes, browser header consistency,
processed-image writes, the secure default, and rejection of unencrypted mode
outside local development/test. Ruff, strict mypy for the changed application
modules, and whitespace checks passed.

The standalone connectivity runner still probes explicit AES256 support as well
as basic storage. On the current Free setup, that explicit encryption capability
probe can fail while configured development-mode uploads succeed.

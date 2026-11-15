export async function uploadScanImage(
  uploadUrl: string,
  requiredHeaders: Record<string, string>,
  file: File,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: requiredHeaders,
    body: file,
  });
  if (response.ok) return;

  const body = await response.text().catch(() => "");
  const document = new DOMParser().parseFromString(body, "application/xml");
  const code = document.getElementsByTagName("Code").item(0)?.textContent?.trim();

  if (code === "XMinioPaidTierLicenseRequired") {
    throw new Error(
      "Image storage cannot accept encrypted uploads with its current license. " +
        "Ask your administrator to enable encrypted image storage.",
    );
  }
  if (code === "SignatureDoesNotMatch" || code === "RequestExpired") {
    throw new Error(
      "Image storage rejected the upload link. Please retry the upload. " +
        "If this continues, contact your administrator.",
    );
  }
  throw new Error(
    `Image upload failed (HTTP ${response.status}). Please retry or contact your administrator.`,
  );
}

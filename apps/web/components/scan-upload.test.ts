import { afterEach, describe, expect, it, vi } from "vitest";

import { uploadScanImage } from "@/lib/scan-upload";

const url = "https://storage.example/agriverse/test.png?signature=test";
const headers = { "Content-Type": "image/png", "x-amz-server-side-encryption": "AES256" };
const file = new File(["test"], "test.png", { type: "image/png" });

afterEach(() => vi.unstubAllGlobals());

describe("scan image uploads", () => {
  it("sends the signed PUT with all required headers and the original file", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await expect(uploadScanImage(url, headers, file)).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(url, { method: "PUT", headers, body: file });
  });

  it("explains the MinIO encryption license rejection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      '<Error><Code>XMinioPaidTierLicenseRequired</Code><Message>License required</Message></Error>',
      { status: 405 },
    )));
    await expect(uploadScanImage(url, headers, file)).rejects.toThrow(
      "Image storage cannot accept encrypted uploads with its current license.",
    );
  });

  it.each(["SignatureDoesNotMatch", "RequestExpired"])("explains %s", async (code) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      `<Error><Code>${code}</Code></Error>`, { status: 403 },
    )));
    await expect(uploadScanImage(url, headers, file)).rejects.toThrow(
      "Image storage rejected the upload link.",
    );
  });

  it("handles a proxy's non-XML error without displaying its response body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      '<html><body>private upstream diagnostic</body></html>', { status: 502 },
    )));
    await expect(uploadScanImage(url, headers, file)).rejects.toThrow(
      "Image upload failed (HTTP 502). Please retry or contact your administrator.",
    );
  });
});

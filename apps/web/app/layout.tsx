import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AgriVerse — Field intelligence for every farmer",
    template: "%s · AgriVerse",
  },
  description:
    "Field-aware soil, weather, crop and plant-health guidance backed by deterministic agronomy and cited evidence.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#103d2a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      {/* Extensions such as Grammarly may add body attributes before hydration. */}
      <body suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

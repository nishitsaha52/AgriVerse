import type { Metadata } from "next";

import { ReviewClient } from "@/components/review-client";

export const metadata: Metadata = { title: "Agronomist review queue" };

export default function ReviewsPage() {
  return <ReviewClient />;
}

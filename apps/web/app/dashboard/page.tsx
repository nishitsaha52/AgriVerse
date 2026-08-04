import type { Metadata } from "next";
import { cookies } from "next/headers";

import { DashboardClient } from "@/components/dashboard-client";

export const metadata: Metadata = { title: "Field dashboard" };

export default async function DashboardPage() {
  const store = await cookies();
  const role = store.get("agriverse_role")?.value ?? "farmer";
  return <DashboardClient role={role} />;
}

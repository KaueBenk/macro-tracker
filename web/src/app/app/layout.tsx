import { redirect } from "next/navigation";

import { AppNav } from "@/components/app-nav";
import { UnauthorizedError, getSession } from "@/lib/api";

export default async function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  try {
    await getSession();
  } catch (error) {
    if (error instanceof UnauthorizedError) {
      redirect("/");
    }
    throw error;
  }

  return (
    <div className="min-h-screen bg-background">
      <AppNav />
      <main className="min-h-screen pb-20 md:ml-64 md:pb-0">{children}</main>
    </div>
  );
}

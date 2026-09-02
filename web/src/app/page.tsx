import Link from "next/link";
import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UnauthorizedError, getSession } from "@/lib/api";

export default async function HomePage() {
  try {
    await getSession();
    redirect("/app");
  } catch (error) {
    if (!(error instanceof UnauthorizedError)) {
      throw error;
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Macro Tracker</CardTitle>
          <CardDescription>
            Acompanhe calorias e macronutrientes com simplicidade.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <Link href="/web/login?next=/app">Entrar com Google</Link>
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}

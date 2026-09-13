import { ActionForm } from "@/components/action-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getSession } from "@/lib/api";
import type { SessionRead } from "@/lib/types";

import { updateTimezone } from "./actions";

const sourceAttributions = [
  ["TACO", "Tabela Brasileira de Composição de Alimentos (TACO), 4ª edição, NEPA/UNICAMP."],
  ["TBCA", "Tabela Brasileira de Composição de Alimentos (TBCA), Universidade de São Paulo (USP)."],
  ["Open Food Facts", "Open Food Facts contributors, openfoodfacts.org (ODbL)."],
  ["USDA", "USDA FoodData Central, 2019. Dados sob licença CC0."],
  ["FatSecret", "FatSecret Platform API; resultados sujeitos aos termos da plataforma."],
];

export default async function AccountPage() {
  const session: SessionRead = await getSession();
  const timezones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [session.user.timezone];
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <header><p className="text-sm font-medium text-primary">Preferências</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Minha conta</h1></header>
      <Card>
        <CardHeader><CardTitle>Dados da conta</CardTitle><CardDescription>Seu e-mail é gerenciado pelo provedor de login.</CardDescription></CardHeader>
        <CardContent className="space-y-6">
          <p><strong>E-mail</strong><br />{session.user.email}</p>
          <ActionForm action={updateTimezone} submitLabel="Salvar preferências">
            <label className="space-y-1 text-sm"><span>Fuso horário (IANA)</span><Input name="timezone" list="timezones" defaultValue={session.user.timezone} required /></label>
            <datalist id="timezones">{timezones.map((timezone) => <option key={timezone} value={timezone} />)}</datalist>
          </ActionForm>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Atribuições das fontes</CardTitle><CardDescription>Alimentos externos exibem sua fonte junto aos resultados.</CardDescription></CardHeader>
        <CardContent className="space-y-4">{sourceAttributions.map(([name, text]) => <div key={name}><h3 className="font-medium">{name}</h3><p className="text-sm text-muted-foreground">{text}</p></div>)}</CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Sessão</CardTitle></CardHeader>
        <CardContent>
          <form method="post" action="/web/logout">
            <input type="hidden" name="csrf_token" value={session.csrf_token ?? ""} />
            <button type="submit" className="inline-flex min-h-10 items-center rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground">Sair</button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

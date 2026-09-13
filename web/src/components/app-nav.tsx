"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays,
  ClipboardList,
  History,
  Home,
  LogOut,
  Settings,
  Utensils,
} from "lucide-react";

import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const links = [
  { href: "/app", label: "Hoje", icon: Home },
  { href: "/app/adicionar", label: "Registrar", icon: ClipboardList },
  { href: "/app/alimentos", label: "Alimentos", icon: Utensils },
  { href: "/app/metas", label: "Metas", icon: Settings },
  { href: "/app/historico", label: "Histórico", icon: History },
  { href: "/app/conta", label: "Conta", icon: CalendarDays },
];

function isActive(pathname: string, href: string) {
  return href === "/app" ? pathname === href : pathname.startsWith(href);
}

function NavigationLink({
  href,
  label,
  icon: Icon,
  pathname,
}: (typeof links)[number] & { pathname: string }) {
  const active = isActive(pathname, href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
        active && "bg-accent font-medium text-accent-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}

export function AppNav() {
  const pathname = usePathname();
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r bg-card/80 px-4 py-6 backdrop-blur md:block">
        <Link href="/app" className="mb-8 block px-3 text-lg font-semibold tracking-tight">
          Macro Tracker
        </Link>
        <Separator className="mb-4" />
        <nav className="space-y-1" aria-label="Navegação principal">
          {links.map((link) => (
            <NavigationLink key={link.href} {...link} pathname={pathname} />
          ))}
        </nav>
        <div className="absolute inset-x-4 bottom-6 flex items-center gap-2 px-3 text-xs text-muted-foreground">
          <LogOut className="size-3.5" aria-hidden="true" />
          <span>Sessão protegida</span>
        </div>
      </aside>

      <nav
        className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-6 border-t bg-card/95 p-1 backdrop-blur md:hidden"
        aria-label="Navegação móvel"
      >
        {links.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-md px-0.5 text-[10px] text-muted-foreground transition-colors",
                active && "bg-accent font-medium text-accent-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              <span className="max-w-full truncate">{label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

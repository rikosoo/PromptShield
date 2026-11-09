"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { contractNotice } from "@/lib/contract";
import { licenseNotice } from "@/lib/license";
import { ROLE_LABEL } from "@/lib/labels";
import { SessionProvider, useSession } from "./session";

/** As cinco áreas do console. Cada página existente fica no grupo a que pertence. */
const NAV_GROUPS = [
  { title: "Visão geral", items: [{ href: "/", label: "Visão geral" }, { href: "/prompts", label: "Análise de prompts" }, { href: "/reports", label: "Relatórios" }] },
  { title: "Incidentes", items: [{ href: "/incidents", label: "Incidentes" }, { href: "/alerts", label: "Alertas e SIEM" }, { href: "/history", label: "Todos os prompts" }, { href: "/quality", label: "Qualidade da detecção" }] },
  { title: "Usuários e grupos", items: [{ href: "/users", label: "Usuários" }, { href: "/risk", label: "Risco por usuário" }, { href: "/groups", label: "Grupos" }] },
  { title: "Políticas", items: [{ href: "/policies", label: "Políticas" }, { href: "/exceptions", label: "Exceções" }, { href: "/allowlist", label: "Domínios permitidos" }, { href: "/keywords", label: "Palavras-chave" }] },
  { title: "Administração", items: [{ href: "/sensors", label: "Sensores" }, { href: "/devices", label: "Dispositivos" }, { href: "/license", label: "Licença" }, { href: "/privacy", label: "Privacidade e segurança" }, { href: "/inference-hooks", label: "Inference hooks" }, { href: "/pilot", label: "Piloto" }] },
];

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("ps-theme");
      if (saved === "dark") { document.documentElement.dataset.theme = "dark"; setDark(true); }
    } catch { /* sem armazenamento: segue claro */ }
  }, []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    try { localStorage.setItem("ps-theme", next ? "dark" : "light"); } catch { /* ok */ }
  };
  return <button type="button" className="btn" onClick={toggle} aria-pressed={dark}>Tema escuro</button>;
}

const NAV_KEY = "ps-nav-closed";

/** Seções do menu que o usuário recolheu (guardado só neste navegador; sem armazenamento, tudo aberto). */
function useClosedSections(keepOpen?: string): [string[], (title: string) => void] {
  const [closed, setClosed] = useState<string[]>([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    try { const v = JSON.parse(localStorage.getItem(NAV_KEY) ?? "[]"); if (Array.isArray(v)) setClosed(v.filter((x): x is string => typeof x === "string" && x !== keepOpen)); } catch { /* sem armazenamento: tudo aberto */ }
  }, []);
  const toggle = (title: string) => setClosed((c) => {
    const next = c.includes(title) ? c.filter((x) => x !== title) : [...c, title];
    try { localStorage.setItem(NAV_KEY, JSON.stringify(next)); } catch { /* ok */ }
    return next;
  });
  return [closed, toggle];
}

function Frame({ children }: { children: ReactNode }) {
  const path = usePathname();
  const activeTitle = NAV_GROUPS.find((g) => g.items.some((n) => (n.href === "/" ? path === "/" : path.startsWith(n.href))))?.title;
  const [closed, toggleSection] = useClosedSections(activeTitle);
  // ao ir para uma página, a seção dela reabre (só na troca de página: recolher depois continua funcionando)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (activeTitle && closed.includes(activeTitle)) toggleSection(activeTitle); }, [path]);
  const { me, tenant, license } = useSession();
  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST", headers: { "X-Requested-With": "promptshield" } });
    location.assign("/login");
  };
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[14rem_minmax(0,1fr)]">
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-panel focus:px-3 focus:py-2">Pular para o conteúdo</a>
      <nav aria-label="Principal" className="bg-nav px-3 py-3 text-nav-fg lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:py-4">
        <div className="mb-2 px-2 text-base font-bold text-white lg:mb-4">PromptShield</div>
        <div className="flex flex-wrap gap-x-4 lg:block">
          {NAV_GROUPS.map((g, gi) => {
            const open = !closed.includes(g.title);
            return (
              <div key={g.title} className="lg:mb-2">
                <button type="button" onClick={() => toggleSection(g.title)} aria-expanded={open} aria-controls={`nav-sec-${gi}`}
                  className="hidden w-full items-center justify-between rounded px-3 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-nav-fg hover:text-white lg:flex">
                  <span>{g.title}</span><span aria-hidden="true" className="font-mono">{open ? "−" : "+"}</span>
                </button>
                <ul id={`nav-sec-${gi}`} className={`flex-wrap gap-1 lg:flex-col ${open ? "flex" : "flex lg:hidden"}`}>
                  {g.items.map((n) => {
                    const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
                    return (
                      <li key={n.href}>
                        <Link href={n.href} aria-current={active ? "page" : undefined}
                          className={`block rounded-md px-3 py-1.5 text-sm hover:bg-nav-act hover:text-white ${active ? "bg-nav-act font-semibold text-white" : ""}`}>{n.label}</Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </nav>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel px-4 py-3 md:px-6">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold" data-testid="tenant-name">{tenant.name}</span>
            <span data-testid="passive-badge" title="O PromptShield só observa, analisa, registra e alerta. Nunca bloqueia, altera ou interrompe um prompt."
              className="rounded-full border border-line px-2 py-0.5 font-mono text-xs text-muted">monitoramento passivo</span>
            {tenant.is_demo && (
              <span data-testid="demo-badge" className="rounded-full border border-med bg-med-bg px-2 py-0.5 font-mono text-xs text-med">dados de exemplo</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted" data-testid="who">{me.email} · {me.role ? ROLE_LABEL[me.role] : ""}</span>
            <ThemeToggle />
            <button type="button" className="btn" onClick={logout}>Sair</button>
          </div>
        </header>
        {(() => {
          const l = licenseNotice(license);
          return l && (
            <div role={l.level === "crit" ? "alert" : "status"} data-testid="license-notice"
              className={`border-b px-4 py-2 text-sm md:px-6 ${l.level === "crit" ? "border-crit bg-crit-bg text-crit" : "border-med bg-med-bg text-med"}`}>
              <strong>{l.title}.</strong> {l.text} <Link href={l.href} className="underline">Ver a licença</Link>
            </div>
          );
        })()}
        {(() => {
          const n = contractNotice(tenant.contract);
          return n && (
            <div role={n.level === "crit" ? "alert" : "status"} data-testid="contract-notice"
              className={`border-b px-4 py-2 text-sm md:px-6 ${n.level === "crit" ? "border-crit bg-crit-bg text-crit" : "border-med bg-med-bg text-med"}`}>
              <strong>{n.title}.</strong> {n.text}
            </div>
          );
        })()}
        <main id="conteudo" className="px-4 py-5 md:px-6">{children}</main>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return <SessionProvider>{() => <Frame>{children}</Frame>}</SessionProvider>;
}

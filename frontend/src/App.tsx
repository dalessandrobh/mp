import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";

import LoginPage from "./features/auth/LoginPage";
import CampaignsPage from "./features/campaigns/CampaignsPage";
import FinancialPage from "./features/financial/FinancialPage";
import IntelligencePage from "./features/intelligence/IntelligencePage";
import OverviewPage from "./features/overview/OverviewPage";
import PortfolioPage from "./features/portfolio/PortfolioPage";
import { signOut } from "./lib/auth";
import { useSession } from "./lib/useSession";

// Telas fora das 4 visões da Fase 7 aparecem desabilitadas — mais honesto do que esconder
// o roadmap ou linkar para uma página vazia.
const NAV = [
  { to: "/", label: "Visão geral", ready: true },
  { to: "/financial", label: "Financeiro", ready: true },
  { to: "/portfolio", label: "Portfólio", ready: true },
  { to: "/intelligence", label: "Inteligência", ready: true },
  { to: "/campaigns", label: "Campanhas", ready: true },
  { to: "/config", label: "Parâmetros", phase: "Depois" },
] as const;

export default function App() {
  const session = useSession();
  const queryClient = useQueryClient();

  // Sem sessão não há o que mostrar: todas as leituras exigem JWT.
  if (!session) return <LoginPage />;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-6">
          <div className="text-sm font-semibold tracking-tight text-slate-100">MP</div>
          <div className="text-xs text-slate-500">Affiliate Intelligence</div>
        </div>

        <nav className="space-y-1">
          {NAV.map((item) =>
            "ready" in item ? (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `block rounded px-3 py-2 text-sm transition ${
                    isActive
                      ? "bg-slate-800 text-slate-100"
                      : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ) : (
              <div
                key={item.to}
                className="flex items-center justify-between rounded px-3 py-2 text-sm text-slate-600"
                title="Fora do escopo desta fase"
              >
                <span>{item.label}</span>
                <span className="text-[10px] uppercase tracking-wide">{item.phase}</span>
              </div>
            ),
          )}
        </nav>

        <div className="mt-auto border-t border-slate-800 pt-4 text-xs">
          <div className="truncate text-slate-500" title={session.email}>
            {session.email}
          </div>
          <button
            onClick={() => {
              queryClient.clear(); // não deixa dado do usuário anterior no cache
              signOut();
            }}
            className="mt-1 text-slate-400 underline hover:text-slate-200"
          >
            Sair
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 p-8">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/financial" element={<FinancialPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/intelligence" element={<IntelligencePage />} />
          <Route path="/campaigns" element={<CampaignsPage />} />
          <Route path="*" element={<OverviewPage />} />
        </Routes>
      </main>
    </div>
  );
}

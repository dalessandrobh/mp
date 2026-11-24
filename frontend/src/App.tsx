import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";

import LinksPage from "./features/links/LinksPage";
import LoginPage from "./features/auth/LoginPage";
import CampaignsPage from "./features/campaigns/CampaignsPage";
import FinancialPage from "./features/financial/FinancialPage";
import IntelligencePage from "./features/intelligence/IntelligencePage";
import OverviewPage from "./features/overview/OverviewPage";
import ParametersPage from "./features/parameters/ParametersPage";
import PortfolioPage from "./features/portfolio/PortfolioPage";
import PublishingPage from "./features/publishing/PublishingPage";
import ProductsPage from "./features/products/ProductsPage";
import { signOut } from "./lib/auth";
import { useSession } from "./lib/useSession";

const NAV = [
  { to: "/", label: "Visão geral" },
  { to: "/financial", label: "Financeiro" },
  { to: "/products", label: "Produtos" },
  { to: "/portfolio", label: "Portfólio" },
  { to: "/intelligence", label: "Inteligência" },
  { to: "/publicacao", label: "Publicação" },
  { to: "/links", label: "Links" },
  { to: "/campaigns", label: "Campanhas" },
  { to: "/config", label: "Parâmetros" },
];

export default function App() {
  const session = useSession();
  const queryClient = useQueryClient();

  // Sem sessão não há o que mostrar: todas as leituras exigem JWT.
  if (!session) return <LoginPage />;

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col overflow-y-auto border-r border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-6">
          <div className="text-sm font-semibold tracking-tight text-slate-100">MP</div>
          <div className="text-xs text-slate-500">Affiliate Intelligence</div>
        </div>

        <nav className="space-y-1">
          {NAV.map((item) => (
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
          ))}
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
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/intelligence" element={<IntelligencePage />} />
          <Route path="/publicacao" element={<PublishingPage />} />
          <Route path="/links" element={<LinksPage />} />
          <Route path="/config" element={<ParametersPage />} />
          <Route path="/campaigns" element={<CampaignsPage />} />
          <Route path="*" element={<OverviewPage />} />
        </Routes>
      </main>
    </div>
  );
}

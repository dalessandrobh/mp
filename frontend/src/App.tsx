import { NavLink, Route, Routes } from "react-router-dom";

import OverviewPage from "./features/overview/OverviewPage";

// Telas ainda não construídas aparecem desabilitadas com a fase que as libera —
// é mais honesto do que esconder o roadmap ou linkar para uma página vazia.
const NAV = [
  { to: "/", label: "Visão geral", ready: true },
  { to: "/financial", label: "Financeiro", phase: "Fase 5" },
  { to: "/portfolio", label: "Portfólio", phase: "Fase 2" },
  { to: "/intelligence", label: "Inteligência", phase: "Fase 6" },
  { to: "/campaigns", label: "Campanhas", phase: "Fase 4" },
  { to: "/config", label: "Parâmetros", phase: "Fase 7" },
] as const;

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-800 bg-slate-900/50 p-4">
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
                title={`Disponível na ${item.phase}`}
              >
                <span>{item.label}</span>
                <span className="text-[10px] uppercase tracking-wide">{item.phase}</span>
              </div>
            ),
          )}
        </nav>
      </aside>

      <main className="flex-1 p-8">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="*" element={<OverviewPage />} />
        </Routes>
      </main>
    </div>
  );
}

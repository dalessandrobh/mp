import { useState } from "react";

import { authConfigured, signIn } from "../../lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha no login.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-800 bg-slate-900/50 p-6"
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-100">MP</h1>
          <p className="text-sm text-slate-500">Affiliate Intelligence — acesso restrito</p>
        </div>

        {!authConfigured && (
          <p className="rounded border border-amber-800/60 bg-amber-950/30 p-3 text-sm text-amber-300">
            Este build não tem <code>VITE_SUPABASE_URL</code> / <code>VITE_SUPABASE_ANON_KEY</code>.
            Defina-os e refaça o build da imagem.
          </p>
        )}

        <label className="block text-sm text-slate-400">
          E-mail
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-sky-600"
          />
        </label>
        <label className="block text-sm text-slate-400">
          Senha
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-sky-600"
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || !authConfigured}
          className="w-full rounded bg-sky-700 px-3 py-2 text-sm font-medium text-white transition hover:bg-sky-600 disabled:opacity-50"
        >
          {busy ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}

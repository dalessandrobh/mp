// Login do dashboard via Supabase Auth (GoTrue), sem supabase-js: são duas chamadas REST.
//
// O backend valida esse mesmo JWT (HS256, segredo do Supabase) e ainda confere o e-mail
// contra DASHBOARD_ALLOWED_EMAILS — estar no Supabase não basta para entrar.
//
// A sessão fica em sessionStorage: some ao fechar a aba. Um token em storage é legível
// por qualquer XSS, e para um painel que aprova decisões de dinheiro, pedir login de novo
// é um custo menor que um token de longa duração esquecido no navegador.

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL ?? "").replace(/\/$/, "");
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";
const STORAGE_KEY = "mp.session";
const REFRESH_MARGIN_S = 60;

export type Session = {
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // epoch em segundos
  email: string;
};

export const authConfigured = Boolean(SUPABASE_URL && ANON_KEY);

type GoTrueToken = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user?: { email?: string };
};

function toSession(token: GoTrueToken, fallbackEmail = ""): Session {
  return {
    accessToken: token.access_token,
    refreshToken: token.refresh_token,
    expiresAt: Math.floor(Date.now() / 1000) + token.expires_in,
    email: token.user?.email ?? fallbackEmail,
  };
}

function read(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null; // storage bloqueado: segue sem sessão persistida
  }
}

function write(session: Session | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // sem storage: a sessão vive só em memória até recarregar
  }
  listeners.forEach((fn) => fn(session));
}

const listeners = new Set<(s: Session | null) => void>();

export function subscribe(fn: (s: Session | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const currentSession = read;

async function tokenRequest(grant: "password" | "refresh_token", body: object): Promise<Session> {
  const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=${grant}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", apikey: ANON_KEY },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(
      response.status === 400 || response.status === 401
        ? "E-mail ou senha incorretos."
        : `Falha no login (${response.status}).`,
    );
  }
  return toSession((await response.json()) as GoTrueToken);
}

export async function signIn(email: string, password: string): Promise<void> {
  if (!authConfigured) throw new Error("Login não configurado neste build.");
  write(await tokenRequest("password", { email, password }));
}

export function signOut() {
  write(null);
}

let refreshing: Promise<Session | null> | null = null;

async function refresh(session: Session): Promise<Session | null> {
  // Várias requisições em paralelo com o token vencido compartilham UM refresh: o
  // refresh token do Supabase é de uso único, o segundo refresh invalidaria o primeiro.
  refreshing ??= tokenRequest("refresh_token", { refresh_token: session.refreshToken })
    .then((next) => {
      write(next);
      return next;
    })
    .catch(() => {
      write(null);
      return null;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function getAccessToken(): Promise<string | null> {
  const session = read();
  if (!session) return null;
  if (session.expiresAt - Math.floor(Date.now() / 1000) > REFRESH_MARGIN_S) {
    return session.accessToken;
  }
  return (await refresh(session))?.accessToken ?? null;
}

import { useSyncExternalStore } from "react";

import { currentSession, subscribe, type Session } from "./auth";

// Snapshot estável: useSyncExternalStore exige o MESMO objeto enquanto nada mudou.
let cache: { raw: string | null; value: Session | null } = { raw: null, value: null };

function snapshot(): Session | null {
  const value = currentSession();
  const raw = value ? JSON.stringify(value) : null;
  if (raw !== cache.raw) cache = { raw, value };
  return cache.value;
}

export function useSession(): Session | null {
  return useSyncExternalStore(subscribe, snapshot, () => null);
}

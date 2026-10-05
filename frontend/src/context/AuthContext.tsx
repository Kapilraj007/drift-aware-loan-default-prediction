import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, apiClient } from "../api/client";
import type { ApiUser, Permission } from "../types";
import { ROLE_PERMISSION_FALLBACK } from "../types";

const storageKey = "drift-loan-session";

interface StoredSession {
  token: string;
  user: ApiUser;
}

interface AuthContextValue {
  user: ApiUser | null;
  permissions: readonly Permission[];
  loading: boolean;
  databaseWaking: boolean;
  sessionNotice: string | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
  clearSessionNotice: () => void;
  hasPermission: (permission: Permission | readonly Permission[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredSession(): StoredSession | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    return parsed.token && parsed.user ? parsed as StoredSession : null;
  } catch {
    return null;
  }
}

function persistSession(session: StoredSession | null): void {
  if (session) {
    window.sessionStorage.setItem(storageKey, JSON.stringify(session));
  } else {
    window.sessionStorage.removeItem(storageKey);
  }
}

function permissionsFor(user: ApiUser | null): readonly Permission[] {
  if (!user) return [];
  return user.permissions ?? ROLE_PERMISSION_FALLBACK[user.role] ?? [];
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [databaseWaking, setDatabaseWaking] = useState(false);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  const clearSession = useCallback(() => {
    apiClient.setToken(null);
    persistSession(null);
    setUser(null);
  }, []);

  const signOut = useCallback(() => {
    setSessionNotice(null);
    clearSession();
  }, [clearSession]);

  useEffect(() => {
    apiClient.setUnauthorizedHandler(() => {
      clearSession();
      setSessionNotice("Your session expired. Please sign in again.");
    });
    apiClient.setDatabaseWakeHandler(setDatabaseWaking);
    return () => {
      apiClient.setUnauthorizedHandler(null);
      apiClient.setDatabaseWakeHandler(null);
    };
  }, [clearSession]);

  useEffect(() => {
    const stored = readStoredSession();
    if (!stored) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    apiClient.setToken(stored.token);
    void apiClient.currentUser(controller.signal)
      .then((currentUser) => {
        setUser(currentUser);
        persistSession({ token: stored.token, user: currentUser });
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          clearSession();
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [clearSession]);

  const signIn = useCallback(async (username: string, password: string) => {
    const token = await apiClient.login(username, password);
    apiClient.setToken(token.access_token);
    try {
      const currentUser = await apiClient.currentUser();
      setUser(currentUser);
      setSessionNotice(null);
      persistSession({ token: token.access_token, user: currentUser });
    } catch (error) {
      clearSession();
      if (error instanceof ApiError) throw error;
      throw new Error("The account could not be verified after sign-in.");
    }
  }, [clearSession]);

  const permissions = useMemo(() => permissionsFor(user), [user]);
  const hasPermission = useCallback((permission: Permission | readonly Permission[]) => {
    const required = Array.isArray(permission) ? permission : [permission];
    return required.some((item) => permissions.includes(item));
  }, [permissions]);
  const clearSessionNotice = useCallback(() => setSessionNotice(null), []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    permissions,
    loading,
    databaseWaking,
    sessionNotice,
    signIn,
    signOut,
    clearSessionNotice,
    hasPermission,
  }), [clearSessionNotice, databaseWaking, hasPermission, loading, permissions, sessionNotice, signIn, signOut, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider.");
  return value;
}

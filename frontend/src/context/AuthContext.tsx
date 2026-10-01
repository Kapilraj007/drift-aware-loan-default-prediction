import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, apiClient } from "../api/client";
import type { ApiUser } from "../types";

const storageKey = "drift-loan-auth";

interface StoredSession {
  token: string;
  user: ApiUser;
}

interface AuthContextValue {
  user: ApiUser | null;
  loading: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredSession(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (!parsed.token || !parsed.user) {
      return null;
    }
    return parsed as StoredSession;
  } catch {
    return null;
  }
}

function persistSession(session: StoredSession | null): void {
  if (session) {
    window.localStorage.setItem(storageKey, JSON.stringify(session));
  } else {
    window.localStorage.removeItem(storageKey);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    apiClient.setToken(null);
    persistSession(null);
    setUser(null);
  }, []);

  useEffect(() => {
    const stored = readStoredSession();
    if (!stored) {
      setLoading(false);
      return;
    }
    apiClient.setToken(stored.token);
    void apiClient
      .currentUser()
      .then((currentUser) => {
        setUser(currentUser);
        persistSession({ token: stored.token, user: currentUser });
      })
      .catch(() => signOut())
      .finally(() => setLoading(false));
  }, [signOut]);

  const signIn = useCallback(async (username: string, password: string) => {
    const token = await apiClient.login(username, password);
    apiClient.setToken(token.access_token);
    try {
      const currentUser = await apiClient.currentUser();
      setUser(currentUser);
      persistSession({ token: token.access_token, user: currentUser });
    } catch (error) {
      apiClient.setToken(null);
      if (error instanceof ApiError) {
        throw error;
      }
      throw new Error("The account could not be verified after sign-in.");
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [loading, signIn, signOut, user],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return value;
}

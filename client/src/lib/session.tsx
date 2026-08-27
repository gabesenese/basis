import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, type Account } from "./api";
import { translate, type Key, type Language } from "./i18n";

type Theme = "light" | "dark";

type Session = {
  account: Account | null;
  ready: boolean;
  language: Language;
  timezone: string;
  theme: Theme;
  t: (key: Key) => string;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  setLanguage: (language: Language) => Promise<void>;
  setTheme: (theme: Theme) => void;
};

const SessionContext = createContext<Session | null>(null);
const THEME_KEY = "basis.theme";

function readStoredTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    api
      .get<Account>("/session")
      .then(setAccount)
      .catch((error) => {
        if (!(error instanceof ApiError && error.status === 401)) throw error;
      })
      .finally(() => setReady(true));
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setAccount(await api.post<Account>("/session", { email, password }));
  }, []);

  const signOut = useCallback(async () => {
    await api.remove("/session");
    setAccount(null);
  }, []);

  const setLanguage = useCallback(async (language: Language) => {
    setAccount(await api.patch<Account>("/preferences", { language }));
  }, []);

  const language = account?.language ?? "pt";

  const value = useMemo<Session>(
    () => ({
      account,
      ready,
      language,
      timezone: account?.timezone ?? "UTC",
      theme,
      t: (key: Key) => translate(language, key),
      signIn,
      signOut,
      setLanguage,
      setTheme: setThemeState,
    }),
    [account, ready, language, theme, signIn, signOut, setLanguage],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession used outside SessionProvider");
  return value;
}

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!path) return;
    let live = true;
    setData(null);
    setError(null);

    api
      .get<T>(path)
      .then((body) => live && setData(body))
      .catch((failure) => live && setError(failure));

    return () => {
      live = false;
    };
  }, [path, attempt]);

  return { data, error, reload: () => setAttempt((n) => n + 1) };
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
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

/*
  Declared here rather than relied on from the DOM library, so the build does
  not depend on which TypeScript release first shipped the type.
*/
type Transitioning = Document & {
  startViewTransition?: (change: () => void) => { finished: Promise<void> };
};

/*
  Switching theme changes every colour on the screen at once, and it has to
  look like one change rather than forty.

  Left alone it does not. A nav link and a button carry their own colour
  transition for hover feedback, so they ease across in 150ms; a card, a rule
  and every mark inside a chart carry none, so they snap. The eye reads that as
  the interface coming apart and reassembling.

  So the switch is taken as a single cross-fade of the whole surface, and every
  element level transition is suppressed underneath it for the duration. One
  animation, one duration, one curve, and the chart's thousand candles cost the
  same as the header because it is two composited frames rather than a thousand
  animated nodes.

  React state flips inside the same callback, so the control's own pressed
  state moves with the colours instead of a frame behind them.
*/
function crossFade(root: HTMLElement, change: () => void): void {
  const doc = document as Transitioning;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /*
    Held on both paths, and that is the point rather than an oversight. A reader
    who asked for less motion, or a browser with no view transitions, still gets
    the colours arriving together: without this they get the ragged version with
    nothing fading over the top of it, which is the worse half of the two.

    Two frames before releasing, so the new colours are painted while element
    transitions are still off. Releasing in the same frame lets them start.
  */
  root.dataset.theming = "";

  const release = () =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() => delete root.dataset.theming),
    );

  if (reduced || typeof doc.startViewTransition !== "function") {
    change();
    release();
    return;
  }

  doc.startViewTransition(change).finished.finally(release);
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

  const setTheme = useCallback((next: Theme) => {
    const root = document.documentElement;
    crossFade(root, () => {
      /*
        The attribute goes first, and the order is not cosmetic.

        Anything that paints itself from the stylesheet rather than from a class
        reads the custom properties during its layout effect, and that effect
        runs inside the flush below. Flushing first meant those readers ran
        while the old theme was still on the root, so they painted themselves in
        the theme being left: the chart came back with the gridlines of the
        other mode and kept them until the next switch.
      */
      root.setAttribute("data-theme", next);
      flushSync(() => setThemeState(next));
    });
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
      setTheme,
    }),
    [account, ready, language, theme, signIn, signOut, setLanguage, setTheme],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession used outside SessionProvider");
  return value;
}

/*
  A background read that fails does not become the screen's error. Replacing a
  working reading with a failure card would throw away the last thing we knew,
  and what a reader needs instead is the number plus the fact that it stopped
  moving. That is what `stale` carries, and only the first read of a path is
  allowed to fail loudly, because then there is nothing to keep.

  Refreshing pauses while the tab is hidden and reads once on the way back, so
  returning to the tab costs one request rather than a queue of them, and the
  reading on screen is never older than the moment it was looked at.
*/
export function useResource<T>(path: string | null, everyMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [stale, setStale] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!path) return;
    let live = true;
    setData(null);
    setError(null);
    setStale(false);

    const read = (background: boolean) =>
      api
        .get<T>(path)
        .then((body) => {
          if (!live) return;
          setData(body);
          setError(null);
          setStale(false);
        })
        .catch((failure) => {
          if (!live) return;
          if (background) setStale(true);
          else setError(failure);
        });

    read(false);

    if (!everyMs) {
      return () => {
        live = false;
      };
    }

    const refresh = () => {
      if (document.visibilityState === "visible") read(true);
    };

    const timer = window.setInterval(refresh, everyMs);
    document.addEventListener("visibilitychange", refresh);

    return () => {
      live = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [path, attempt, everyMs]);

  return { data, error, stale, reload: () => setAttempt((n) => n + 1) };
}

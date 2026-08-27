import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useSession } from "../lib/session";
import { clock, zoneLabel } from "../lib/format";
import { Segmented } from "./primitives";
import type { Key } from "../lib/i18n";

const NAV: { to: string; key: Key }[] = [
  { to: "/hoje", key: "today" },
  { to: "/calendario", key: "calendar" },
  { to: "/estudo", key: "study" },
  { to: "/contexto", key: "context" },
];

/*
  Two clocks, always. The anchor is New York because that is where the events
  this engine studies are released, and the second is the reader's own zone.
  A person reading this in São Paulo should never have to do the arithmetic
  between a release time and their own afternoon.
*/
const ANCHOR_ZONE = "America/New_York";

function Clocks({ timezone }: { timezone: string }) {
  const [at, setAt] = useState(() => new Date());

  useEffect(() => {
    const tick = window.setInterval(() => setAt(new Date()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  /*
    The anchor and the reader's own zone always show. UTC is the one that can
    be worked out from either, so it is the one that goes when the window is
    too narrow to carry three.
  */
  const zones =
    timezone === ANCHOR_ZONE
      ? [{ zone: ANCHOR_ZONE, optional: false }, { zone: "UTC", optional: true }]
      : [
          { zone: ANCHOR_ZONE, optional: false },
          { zone: timezone, optional: false },
          { zone: "UTC", optional: true },
        ];

  return (
    <div className="flex items-start gap-4 sm:gap-5">
      {zones.map(({ zone, optional }) => (
        <div key={zone} className={`text-right ${optional ? "hidden sm:block" : ""}`}>
          <div className="num text-[13px] leading-tight text-ink">{clock(zone, at)}</div>
          <div className="eyebrow leading-tight">{zoneLabel(zone)}</div>
        </div>
      ))}
    </div>
  );
}

function Wordmark() {
  return (
    <div className="flex items-baseline gap-1.5">
      <span
        className="prose-read text-[19px] tracking-[0.24em] text-ink"
        style={{ fontWeight: 400 }}
      >
        BASIS
      </span>
      <span
        aria-hidden
        className="mb-0.5 inline-block size-1"
        style={{ background: "var(--measured)" }}
      />
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { account, language, timezone, theme, t, setLanguage, setTheme } = useSession();
  const navigate = useNavigate();
  const { signOut } = useSession();

  /*
    The shell fills the viewport rather than sitting in a fixed column. On a
    wide monitor a centred 1440 leaves two dead bands and pushes the rail into
    the middle of the screen, where a persistent navigation has no business
    being. Reading width is capped per screen instead, on the prose that needs
    it, so extra width goes to more columns and never to longer lines.
  */
  return (
    <div className="lattice min-h-dvh">
      <div className="flex min-h-dvh">
        <aside className="sticky top-0 hidden h-dvh w-[236px] shrink-0 flex-col border-r border-line bg-surface md:flex 2xl:w-[268px]">
          <div className="border-b border-line px-6 py-5">
            <Wordmark />
          </div>

          <nav className="flex-1 py-3">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `block border-l-2 px-6 py-2.5 text-[14px] transition-colors ${
                    isActive
                      ? "border-l-ink bg-sunken text-ink"
                      : "border-l-transparent text-muted hover:text-ink"
                  }`
                }
              >
                {t(item.key)}
              </NavLink>
            ))}

            <p className="mt-6 border-t border-line px-6 pt-4 text-[12px] leading-relaxed text-faint">
              {t("noSignalScreens")}
            </p>
          </nav>

          <div className="border-t border-line px-6 py-4">
            <div className="text-[13px] text-ink">{account?.display_name}</div>
            <div className="num pb-3 text-[11px] text-faint">
              {zoneLabel(timezone)} · {language.toUpperCase()}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Segmented
                label={t("interface")}
                value={language}
                onChange={(next) => void setLanguage(next)}
                options={[
                  { value: "pt", label: "PT" },
                  { value: "en", label: "EN" },
                ]}
              />
              <Segmented
                label={t("theme")}
                value={theme}
                onChange={setTheme}
                options={[
                  { value: "light", label: t("light") },
                  { value: "dark", label: t("dark") },
                ]}
              />
            </div>

            <button
              type="button"
              onClick={() => void signOut().then(() => navigate("/entrar"))}
              className="eyebrow mt-3 text-faint transition-colors hover:text-ink"
            >
              {t("signOut")}
            </button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 border-b border-line bg-surface">
            <div className="mx-auto flex w-full max-w-[1680px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <div className="md:hidden">
                <Wordmark />
              </div>
              <div className="ml-auto">
                <Clocks timezone={timezone} />
              </div>
            </div>

            <nav className="flex gap-4 overflow-x-auto border-t border-line px-4 py-2 sm:px-6 md:hidden">
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `shrink-0 text-[13px] ${isActive ? "text-ink" : "text-muted"}`
                  }
                >
                  {t(item.key)}
                </NavLink>
              ))}
            </nav>
          </header>

          <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 sm:py-7">
            <div className="mx-auto w-full max-w-[1680px]">{children}</div>
          </main>

          <footer className="border-t border-line bg-surface px-4 py-4 sm:px-6 md:hidden">
            <div className="text-[13px] text-ink">{account?.display_name}</div>
            <div className="num pb-3 text-[11px] text-faint">
              {zoneLabel(timezone)} · {language.toUpperCase()}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Segmented
                label={t("interface")}
                value={language}
                onChange={(next) => void setLanguage(next)}
                options={[
                  { value: "pt", label: "PT" },
                  { value: "en", label: "EN" },
                ]}
              />
              <Segmented
                label={t("theme")}
                value={theme}
                onChange={setTheme}
                options={[
                  { value: "light", label: t("light") },
                  { value: "dark", label: t("dark") },
                ]}
              />
              <button
                type="button"
                onClick={() => void signOut().then(() => navigate("/entrar"))}
                className="eyebrow ml-auto text-faint transition-colors hover:text-ink"
              >
                {t("signOut")}
              </button>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}

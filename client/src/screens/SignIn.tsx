import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useSession } from "../lib/session";
import { ApiError } from "../lib/api";
import { Button, Field, Segmented } from "../components/primitives";
import { Rail, RailScale } from "../components/Rail";
import { translate, type Language } from "../lib/i18n";

/*
  The hero is the rail itself, holding a wide interval centred on the coin
  flip. It is not an illustration of the product, it is the product's default
  answer, and it says before anyone signs in that a result here comes with the
  width of its own doubt attached.
*/
export function SignIn() {
  const { account, theme, setTheme } = useSession();
  const { signIn } = useSession();
  const [language, setLanguage] = useState<Language>("pt");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const t = (key: Parameters<typeof translate>[1]) => translate(language, key);

  if (account) return <Navigate to="/hoje" replace />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      await signIn(email, password);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setFailed(true);
      else throw error;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.15fr_1fr]">
      <section className="lattice relative hidden flex-col justify-between border-r border-line px-14 py-12 lg:flex">
        <div className="flex items-baseline gap-1.5">
          <span className="prose-read text-[20px] tracking-[0.24em] text-ink">BASIS</span>
          <span
            aria-hidden
            className="mb-0.5 inline-block size-1"
            style={{ background: "var(--measured)" }}
          />
        </div>

        <div className="max-w-[30rem]">
          <h1 className="prose-read text-[60px] leading-[0.95] tracking-[-0.02em] text-ink">
            {t("heroLead")}
            <br />
            <em className="not-italic" style={{ color: "var(--measured)" }}>
              {t("heroEmphasis")}
            </em>
          </h1>

          <p className="mt-7 max-w-[36ch] text-[14px] leading-relaxed text-muted">
            {t("heroBody")}
          </p>

          <div className="mt-12 max-w-[26rem]">
            <div className="eyebrow pb-2">
              {language === "pt" ? "Como ler um número aqui" : "How to read a number here"}
            </div>
            <Rail
              estimate={-1}
              low={-2.4}
              high={0.9}
              outerLow={-2.1}
              outerHigh={0.7}
              domain={[-4, 4]}
              height={44}
              label={
                language === "pt"
                  ? "Chave da notação: estimativa, intervalo e a régua do zero"
                  : "Key to the notation: estimate, interval and the zero rule"
              }
            />
            <RailScale domain={[-4, 4]} format={(value) => `${value > 0 ? "+" : ""}${value}`} />

            <dl className="mt-4 space-y-1.5 text-[12px] leading-relaxed text-faint">
              {(
                [
                  [
                    language === "pt" ? "Traço cheio" : "Solid tick",
                    language === "pt" ? "a estimativa" : "the estimate",
                  ],
                  [
                    language === "pt" ? "Banda" : "Band",
                    language === "pt" ? "o intervalo de confiança" : "the confidence interval",
                  ],
                  [
                    language === "pt" ? "Régua vertical" : "Vertical rule",
                    language === "pt"
                      ? "o zero, que nunca se move"
                      : "zero, which never moves",
                  ],
                ] as const
              ).map(([term, meaning]) => (
                <div key={term} className="flex gap-2">
                  <dt className="eyebrow shrink-0 pt-[3px]">{term}</dt>
                  <dd>{meaning}</dd>
                </div>
              ))}
            </dl>

            <p className="mt-4 text-[12px] leading-relaxed text-faint">
              {language === "pt"
                ? "Esta é a chave da notação, não uma medição. Toda medição de verdade está do outro lado."
                : "This is a key to the notation, not a measurement. Every real measurement is on the other side."}
            </p>
          </div>
        </div>

        <div />
      </section>

      <section className="flex items-center justify-center px-6 py-14">
        <form onSubmit={submit} className="w-full max-w-[24rem]">
          <h2 className="prose-read text-[30px] leading-tight text-ink">{t("signIn")}</h2>
          <p className="mt-1.5 text-[13px] text-muted">
            {language === "pt"
              ? "Duas contas. Os mesmos números, no seu idioma."
              : "Two accounts. The same numbers, in your own language."}
          </p>

          <div className="mt-8 space-y-5">
            <Field
              label={t("email")}
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Field
              label={t("password")}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          {failed && (
            <p role="alert" className="mt-4 text-[13px]" style={{ color: "var(--modelled)" }}>
              {t("wrongCredentials")}
            </p>
          )}

          <Button type="submit" disabled={busy} className="mt-7 w-full">
            {t("continue")}
          </Button>

          <div className="mt-10 flex items-center justify-between border-t border-line pt-5">
            <span className="eyebrow">{t("interface")}</span>
            <div className="flex gap-2">
              <Segmented
                label={t("interface")}
                value={language}
                onChange={setLanguage}
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
          </div>
        </form>
      </section>
    </div>
  );
}

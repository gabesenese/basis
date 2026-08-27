import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function Card({
  children,
  className = "",
  ruled = false,
}: {
  children: ReactNode;
  className?: string;
  ruled?: boolean;
}) {
  return (
    <section
      className={`border border-line bg-surface ${ruled ? "lattice" : ""} ${className}`}
    >
      {children}
    </section>
  );
}

export function CardHead({
  title,
  aside,
  lead,
}: {
  title: string;
  aside?: ReactNode;
  lead?: string;
}) {
  return (
    <header className="border-b border-line px-5 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-medium tracking-tight text-ink">{title}</h2>
        {aside}
      </div>
      {lead && (
        <p className="prose-read mt-2 max-w-[62ch] text-[14px] leading-relaxed text-muted">
          {lead}
        </p>
      )}
    </header>
  );
}

/*
  Provenance is not decoration and never sits in a tooltip. A number that was
  observed and a number that was derived under an assumption are different
  kinds of claim, and the reader has to be able to tell them apart at a glance
  or the assumption quietly becomes a fact downstream.
*/
export function Provenance({
  kind,
  children,
}: {
  kind: "measured" | "modelled";
  children: ReactNode;
}) {
  const tone =
    kind === "measured"
      ? "border-measured/40 text-measured"
      : "border-modelled/50 text-modelled";

  return (
    <span
      className={`eyebrow inline-flex items-center gap-1.5 border px-1.5 py-0.5 ${tone}`}
      style={{ color: kind === "measured" ? "var(--measured)" : "var(--modelled)" }}
    >
      <span
        aria-hidden
        className="inline-block size-1.5"
        style={{
          background: kind === "measured" ? "var(--measured)" : "var(--modelled)",
          borderRadius: kind === "measured" ? "50%" : 0,
        }}
      />
      {children}
    </span>
  );
}

export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="eyebrow border border-line px-1.5 py-0.5 text-muted">
      {children}
    </span>
  );
}

export function Button({
  variant = "solid",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "solid" | "quiet" }) {
  const look =
    variant === "solid"
      ? "bg-ink text-surface hover:opacity-90"
      : "border border-line text-ink hover:border-line-strong";

  return (
    <button
      className={`h-10 px-4 text-[13px] font-medium transition-opacity disabled:opacity-45 ${look} ${className}`}
      {...rest}
    />
  );
}

export function Field({
  label,
  hint,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className="block">
      <span className="eyebrow block pb-1.5">{label}</span>
      <input
        className="num h-11 w-full border border-line bg-surface px-3 text-[14px] text-ink placeholder:text-faint focus:border-line-strong"
        {...rest}
      />
      {hint && <span className="mt-1 block text-[12px] text-muted">{hint}</span>}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex border border-line">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`eyebrow px-2.5 py-1.5 transition-colors ${
              active ? "bg-ink text-surface" : "text-muted hover:text-ink"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Stat({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: "measured" | "modelled";
}) {
  const color =
    tone === "modelled"
      ? "var(--modelled)"
      : tone === "measured"
        ? "var(--measured)"
        : "var(--ink)";

  return (
    <div>
      <div className="eyebrow pb-1">{label}</div>
      <div className="num flex items-baseline gap-1.5 text-[22px] leading-none" style={{ color }}>
        {value}
        {unit && <span className="text-[11px] text-muted">{unit}</span>}
      </div>
    </div>
  );
}

export function Row({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line px-5 py-3 last:border-b-0">
      <span className="text-[13px] text-muted">{label}</span>
      <span className="num text-[13px] text-ink">{children}</span>
    </div>
  );
}

export function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="px-5 py-14 text-center">
      <p className="prose-read text-[20px] text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-[46ch] text-[13px] leading-relaxed text-muted">
        {body}
      </p>
    </div>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="px-5 py-14 text-center">
      <span className="eyebrow">{label}</span>
    </div>
  );
}

export function Failure({
  label,
  detail,
  onRetry,
  retryLabel,
}: {
  label: string;
  detail: string;
  onRetry: () => void;
  retryLabel: string;
}) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="prose-read text-[18px] text-ink">{label}</p>
      <p className="num mx-auto mt-2 max-w-[52ch] text-[12px] text-muted">{detail}</p>
      <Button variant="quiet" className="mt-4" onClick={onRetry}>
        {retryLabel}
      </Button>
    </div>
  );
}

import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import { TONE_VAR, type Tone } from "../../domain/labels";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANT: Record<Variant, string> = {
  primary: "bg-focus text-[#0b1220] font-semibold hover:brightness-110 disabled:bg-surface-2 disabled:font-medium disabled:text-[#7e8898]",
  secondary: "border border-line bg-surface-2 text-ink hover:border-[#b1bac9] disabled:text-ink-2",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink disabled:text-[#a0a8b4]",
  danger: "border border-[#dfccca] bg-[#f5f0f0] text-[#ff6f54] hover:border-up disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sz = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-9 px-3.5 text-[13px] gap-2";
  return (
    <button
      type="button"
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-[8px] transition-[background,border-color,transform] duration-150 active:translate-y-[1px] disabled:cursor-not-allowed disabled:active:translate-y-0 ${sz} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function IconButton({ label, children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex size-8 items-center justify-center rounded-[8px] text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-40 ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Chip({ tone, children, solid = false, className = "" }: { tone: Tone; children: ReactNode; solid?: boolean; className?: string }) {
  const c = TONE_VAR[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4 ${className}`}
      style={
        solid
          ? { background: c, color: "#0b1220" }
          : { color: c, background: `color-mix(in srgb, ${c} 14%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${c} 38%, transparent)` }
      }
    >
      {children}
    </span>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  label,
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  items: { id: T; label: ReactNode; count?: number }[];
  label: string;
  size?: "sm" | "md";
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const n = (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    onChange(items[n].id);
    refs.current[n]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex items-center gap-0.5 rounded-[8px] bg-bg/60 p-0.5">
      {items.map((it, i) => {
        const active = it.id === value;
        return (
          <button
            key={it.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => onKey(e, i)}
            onClick={() => onChange(it.id)}
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-[6px] font-medium transition-colors ${
              size === "sm" ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs"
            } ${active ? "bg-surface-2 text-ink shadow-[inset_0_0_0_1px_var(--border)]" : "text-ink-2 hover:text-ink"}`}
          >
            {it.label}
            {it.count != null && <span className="num text-[10px] text-ink-2">{it.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Dialog native: focus trap + Esc + trả focus về control đã mở do trình duyệt xử lý. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  width = 560,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      opener.current = document.activeElement as HTMLElement | null;
      d.showModal();
    } else if (!open && d.open) {
      d.close();
      opener.current?.focus?.();
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      aria-label={title}
      className="m-auto max-h-[86vh] w-[calc(100vw-32px)] overflow-hidden rounded-[12px] border border-line bg-surface p-0 text-ink shadow-[0_24px_64px_rgba(250,251,253,0.6)] backdrop:bg-[#f9f9fc]/70"
      style={{ maxWidth: width }}
    >
      {open && (
        <div className="flex max-h-[86vh] flex-col">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 className="text-[15px] font-semibold">{title}</h2>
            <IconButton label="Đóng" onClick={onClose}>
              <X size={16} />
            </IconButton>
          </div>
          <div className="scroll-thin min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
          {footer && <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-8 text-center">
      {icon && <div className="text-ink-2">{icon}</div>}
      <div className="text-[13px] font-semibold text-ink">{title}</div>
      {body && <div className="max-w-[44ch] text-xs text-ink-2">{body}</div>}
      {action}
    </div>
  );
}

export function Kv({ k, v, mono = true }: { k: ReactNode; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-ink-2">{k}</span>
      <span className={`text-right text-xs text-ink ${mono ? "num" : ""}`}>{v}</span>
    </div>
  );
}

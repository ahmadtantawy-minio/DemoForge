/**
 * Toast wrapper — re-exports sonner `toast` with an automatic "Copy" action
 * button on every notification (copies title + description to clipboard).
 * If the caller already provides an `action`, it is preserved as-is.
 */
import { toast as sonnerToast } from "sonner";

type SonnerToast = typeof sonnerToast;
type ToastFn = (message: Parameters<SonnerToast>[0], opts?: Parameters<SonnerToast>[1]) => ReturnType<SonnerToast>;

function withCopy(
  message: Parameters<SonnerToast>[0],
  opts?: Parameters<SonnerToast>[1],
): Parameters<SonnerToast>[1] {
  if (opts?.action) return opts; // caller already added action — don't clobber it
  const title = typeof message === "string" ? message : "";
  const desc = typeof opts?.description === "string" ? opts.description : "";
  const text = [title, desc].filter(Boolean).join("\n");
  if (!text) return opts;
  return {
    ...opts,
    action: {
      label: "Copy",
      onClick: () => navigator.clipboard.writeText(text).catch(() => {}),
    },
  };
}

const wrapped: ToastFn = (message, opts) => sonnerToast(message, withCopy(message, opts));

export const toast = Object.assign(wrapped, {
  success: ((message, opts) => sonnerToast.success(message, withCopy(message, opts))) as SonnerToast["success"],
  error:   ((message, opts) => sonnerToast.error(message, withCopy(message, opts))) as SonnerToast["error"],
  warning: ((message, opts) => sonnerToast.warning(message, withCopy(message, opts))) as SonnerToast["warning"],
  info:    ((message, opts) => sonnerToast.info(message, withCopy(message, opts))) as SonnerToast["info"],
  loading: sonnerToast.loading,
  dismiss: sonnerToast.dismiss,
  promise: sonnerToast.promise,
  custom:  sonnerToast.custom,
  message: sonnerToast.message,
});

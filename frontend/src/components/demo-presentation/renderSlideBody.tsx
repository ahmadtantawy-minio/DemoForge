function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Minimal markdown: newlines + **bold** only; safe for dangerouslySetInnerHTML after escape. */
export function renderSlideBodyHtml(markdown: string): { __html: string } {
  const esc = escapeHtml(markdown);
  const bold = esc.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const br = bold.split("\n").join("<br/>");
  return { __html: br };
}

export function SlideBodyView({ markdown, className }: { markdown: string; className?: string }) {
  return (
    <div
      className={className}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={renderSlideBodyHtml(markdown)}
    />
  );
}

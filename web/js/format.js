const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function int(n) {
  return Math.round(n).toLocaleString("en-US");
}

export function one(n) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function pct(x) {
  return `${(x * 100).toFixed(1)}%`;
}

export function monthLabel(m) {
  const [y, mm] = m.split("-");
  return `${MONTHS[Number(mm) - 1]} ${y}`;
}

export function dateLabel(d) {
  const [y, m, day] = d.split("-").map(Number);
  return `${day} ${MONTHS[m - 1]} ${y}`;
}

export function periodLabel(p) {
  return `${dateLabel(p.start)} to ${dateLabel(p.end)}`;
}

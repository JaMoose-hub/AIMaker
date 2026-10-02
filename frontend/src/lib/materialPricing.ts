// Display-only conversion. BOM and structural catalog prices remain in TWD.
// This is a pinned reference, not a live rate or a supplier's USD quote.
export const MATERIAL_USD_REFERENCE = {
  twdPerUsd: 31.842,
  date: "2026-10-01",
  source: "https://www.cbc.gov.tw/en/lp-700-2.html",
} as const;

const usdNumber = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function materialUsdEstimate(unitPriceTwd: number, quantity = 1): string | null {
  if (!Number.isFinite(unitPriceTwd) || unitPriceTwd < 0 || !Number.isFinite(quantity) || quantity < 0) return null;
  const total = unitPriceTwd * quantity / MATERIAL_USD_REFERENCE.twdPerUsd;
  return Number.isFinite(total) ? `US$${usdNumber.format(total)}` : null;
}

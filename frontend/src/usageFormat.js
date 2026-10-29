// Pure formatting for usage baselines and confidence, shared by every view (and unit-tested in usageFormat.test.js),
// so a number on screen is always the stored value rounded the same way.

/** Money in Indian rupees with Indian digit grouping (₹1,23,456); paise only for small amounts. */
export function inr(v) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  const n = Number(v), a = Math.abs(n)
  const s = a.toLocaleString('en-IN', a < 100 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 })
  return `${n < 0 ? '−' : ''}₹${s}`
}

export const STATE_CLASS = { Safe: 'reuse', 'Approaching limit': 'test', 'Stop use': 'recycle' }
export const RISK_CLASS = { Low: 'reuse', Elevated: 'test', High: 'recycle' }

/** Confidence (0-100, or null when no probability exists) as on-screen text. */
export function confText(conf) {
  if (conf == null || !Number.isFinite(conf)) return 'not available'
  if (conf >= 99.5) return '>99%'          // a model probability is never shown as certainty
  return `${Math.round(Math.min(100, Math.max(0, conf)))}%`
}

/** 0-1 fraction for a confidence bar (null -> 0). */
export function confFrac(conf) {
  if (conf == null || !Number.isFinite(conf)) return 0
  return Math.min(1, Math.max(0, conf / 100))
}

/** "stop by ~P10 cycles (typical P50, range P10–P90)" in cycles, plus months for the application's duty. */
export function stopText(stop) {
  if (!stop) return 'not available'
  if (stop.p10 === 0 && stop.p50 === 0) return 'stop now (at or below the floor)'
  return `${stop.p10.toLocaleString()} cycles (typical ${stop.p50.toLocaleString()}, range ${stop.p10.toLocaleString()}–${stop.p90.toLocaleString()})`
}

export const MAX_MONTHS = 120   // beyond 10 years calendar ageing (not in the cycling data) would dominate

export function monthsText(stop) {
  if (!stop || (stop.p10 === 0 && stop.p50 === 0)) return '0 months'
  if (stop.months_p10 > MAX_MONTHS) return 'over 10 years at that duty (calendar ageing is not modelled)'
  return `≈ ${stop.months_p10} months at that duty (typical ${stop.months_p50})`
}

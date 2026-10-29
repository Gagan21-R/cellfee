// CELLFEE motion layer (Part B) — one import in main.jsx. It never changes layout or content:
//  * finds targets by existing selectors / data-anim attributes as React renders them (MutationObserver),
//  * plays each animation once when its section scrolls into view (IntersectionObserver),
//    and again when that section's "Explain" button is clicked,
//  * animates only transform, opacity and SVG stroke-dashoffset (Web Animations API); count-ups use rAF and always
//    finish on the exact text React rendered,
//  * does nothing under prefers-reduced-motion, pauses while the tab is hidden, and exposes window.__motion.
import './cellfee-motion.css'

export const MOTION = {
  fast: 180, base: 420, slow: 900, long: 1600,           // ms — keep in sync with --m-* in cellfee-motion.css
  easeOut: 'cubic-bezier(.2, .8, .2, 1)', easeInOut: 'cubic-bezier(.65, 0, .35, 1)',
  stagger: 45,
  tickerSpeed: 50,                                       // px/s fallback; CSS --ticker-speed wins
  mobileWidth: 600,                                      // below this the heaviest sequences render their final state
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
let disabled = false
const off = () => disabled || reduced()
const small = () => window.innerWidth < MOTION.mobileWidth
const wait = ms => new Promise(r => setTimeout(r, ms))

function anim(el, frames, opts = {}) {
  if (!el || off() || !el.animate) return null
  return el.animate(frames, { duration: MOTION.base, easing: MOTION.easeOut, fill: 'backwards', ...opts })
}

// ----------------------------------------------------------------------------- count-up (ends on the real text)
const NUM = /-?\$?\d[\d,]*(\.\d+)?/
const FINAL = new WeakMap()   // the real text of a number while it is counting (so overlapping replays end correctly)
function countUp(el, dur = MOTION.slow, delay = 0) {
  if (!el || off()) return
  const finalText = FINAL.get(el) ?? el.textContent
  FINAL.set(el, finalText)
  const m = finalText.match(NUM)
  if (!m) return
  const raw = m[0].replace(/[$,]/g, '')
  const target = parseFloat(raw)
  if (!Number.isFinite(target)) return
  const decimals = (raw.split('.')[1] || '').length
  const commas = m[0].includes(',')
  const dollar = m[0].includes('$')
  const fmt = v => {
    let s = Math.abs(v).toFixed(decimals)
    if (commas) s = Number(s).toLocaleString(finalText.includes('₹') ? 'en-IN' : 'en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    return (v < 0 ? '-' : '') + (dollar ? '$' : '') + s
  }
  let start = null, last = null
  const step = t => {
    if (start === null) start = t + delay
    if (last !== null && el.textContent !== last && el.textContent !== FINAL.get(el)) { FINAL.delete(el); return }  // React re-rendered
    const k = Math.min(1, Math.max(0, (t - start) / dur))
    const e = 1 - Math.pow(1 - k, 3)
    if (k >= 1) { el.textContent = finalText; FINAL.delete(el); return }
    last = finalText.replace(m[0], fmt(target * e))
    if (FINAL.get(el) !== finalText) return                     // a newer run owns this number
    el.textContent = last
    requestAnimationFrame(step)
  }
  // the text only changes once a frame actually runs (a background tab never shows a stray 0) ...
  requestAnimationFrame(t => {
    if (FINAL.get(el) !== finalText) return
    last = finalText.replace(m[0], fmt(0))
    el.textContent = last
    requestAnimationFrame(step)
  })
  // ... and a timer guarantees the exact real value at the end even if frames stop (tab hidden mid-count)
  setTimeout(() => { if (FINAL.get(el) === finalText) { el.textContent = finalText; FINAL.delete(el) } }, delay + dur + 200)
}

// ----------------------------------------------------------------------------- handlers (selector → play)
const growX = (el, delay = 0, dur = MOTION.slow) => anim(el, [{ transform: 'scaleX(0)', transformOrigin: 'left center' }, { transform: 'scaleX(1)', transformOrigin: 'left center' }], { duration: dur, delay })
const riseIn = (el, delay = 0) => anim(el, [{ opacity: 0, transform: 'translateY(14px)' }, { opacity: 1, transform: 'none' }], { delay })
const stamp = (el, delay = 0) => anim(el, [{ opacity: 0, transform: 'scale(1.5) rotate(-6deg)' }, { opacity: 1, transform: 'scale(.94)', offset: .7 }, { opacity: 1, transform: 'none' }], { duration: MOTION.base, delay })
const draw = (el, delay = 0, dur = MOTION.slow) => anim(el, [{ strokeDasharray: '1', strokeDashoffset: 1 }, { strokeDasharray: '1', strokeDashoffset: 0 }], { duration: dur, delay, easing: MOTION.easeInOut })

const H = {}

// Overview — battery grid: the scan sweeps once, each block fills as the scan passes, then a faint idle shimmer
H['.m-cells'] = svg => {
  const scan = svg.querySelector('.scan')
  const vb = svg.viewBox.baseVal
  const W = vb.width
  const sweep = MOTION.long
  anim(scan, [{ transform: 'translateX(0)' }, { transform: `translateX(${W - 8}px)`, offset: .96 }, { transform: `translateX(${W - 8}px)`, opacity: 0 }],
    { duration: sweep, easing: 'linear', fill: 'none' })
  svg.querySelectorAll('g[transform]').forEach(g => {
    const x = parseFloat((g.getAttribute('transform').match(/translate\(([-\d.]+)/) || [])[1] || 0)
    const lvl = g.querySelector('.lvl')
    anim(lvl, [{ transform: 'scaleY(0)', transformOrigin: '50% 100%', transformBox: 'fill-box' }, { transform: 'scaleY(1)', transformOrigin: '50% 100%', transformBox: 'fill-box' }],
      { duration: MOTION.base, delay: (x / W) * sweep })
  })
  if (!off() && scan) setTimeout(() => scan.animate?.([{ opacity: .85 }, { opacity: .5 }, { opacity: .85 }], { duration: 2600, iterations: Infinity, easing: 'ease-in-out', delay: 0 }), sweep + 50)
}
// Overview — outcome cards rise in turn; Screened counts first, then Reuse, Full test, Recycle
H['.outcomes'] = box => {
  box.querySelectorAll('.oc').forEach((c, i) => {
    riseIn(c, i * 120)
    countUp(c.querySelector('.num'), MOTION.slow, i * 260)
    growX(c.querySelector('.bar i'), i * 260 + 200)
  })
}
// Overview — status chips: key-on dots pulse once
H['.chips-row'] = row => row.querySelectorAll('.chip.ok').forEach((c, i) =>
  anim(c, [{ transform: 'scale(1)' }, { transform: 'scale(1.06)' }, { transform: 'scale(1)' }], { duration: MOTION.slow, delay: 300 + i * 150 }))
// Stats / counters anywhere (XGBoost vs AQSVC, Decisions, Environment, Evidence)
H['.stat'] = s => { riseIn(s); countUp(s.querySelector('.value')) }

// Fleet / Passports / Upload tables: the rows of the current (filtered) set slide in, staggered
H['.fleet-table tbody'] = tb => [...tb.children].slice(0, 24).forEach((tr, i) =>
  anim(tr, [{ opacity: 0, transform: 'translateX(-10px)' }, { opacity: 1, transform: 'none' }], { duration: MOTION.base, delay: i * 25 }))

// Passport — the card unfolds, then its history draws in step by step with the connecting line
H['[data-anim="timeline"]'] = ol => {
  if (!off()) ol.animate?.([{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }], { pseudoElement: '::before', duration: MOTION.long, easing: MOTION.easeInOut, fill: 'backwards' })
  ol.querySelectorAll('li').forEach((li, i) => anim(li, [{ opacity: 0, transform: 'translateX(-8px)' }, { opacity: 1, transform: 'none' }], { delay: i * 180 }))
}
H['.drawer'] = d => anim(d, [{ opacity: 0, transform: 'scale(.985) translateY(10px)' }, { opacity: 1, transform: 'none' }], { duration: MOTION.base })

// Usage baseline blocks (A2–A4): stop bar fills, baseline marker slides in, badges stamp, confidence bars grow + count
H['.usage, .pack-usage, .appconf'] = box => {
  box.querySelectorAll('[data-anim="stamp"]').forEach((b, i) => stamp(b, 200 + i * 120))
  box.querySelectorAll('.stopbar .fill').forEach(f => growX(f, 250))
  box.querySelectorAll('.stopbar .band').forEach(f => anim(f, [{ opacity: 0 }, { opacity: 1 }], { duration: MOTION.slow, delay: 500 }))
  box.querySelectorAll('.stopbar .cap').forEach(c => anim(c, [{ opacity: 0, transform: 'translateX(-24px)' }, { opacity: 1, transform: 'none' }], { delay: 700 }))
  box.querySelectorAll('.ac-row').forEach((r, i) => { growX(r.querySelector('.ac-bar i'), 300 + i * 90); countUp(r.querySelector('.ac-pct'), MOTION.slow, 300 + i * 90) })
  box.querySelectorAll('[data-count]').forEach(n => { if (!n.closest('.ac-row')) countUp(n, MOTION.slow, 300) })
}

// Quantum ML — circuit: wires draw, gates appear left to right with a brief highlight, then the measurements;
// a caption overlay walks "Encode features → Run circuit → Measure → Score" and then leaves.
H['[data-anim="circuit"]'] = svg => {
  svg.querySelectorAll('.circuit-line').forEach((l, i) => draw(l, i * 60, MOTION.slow))
  const gates = [...svg.querySelectorAll('.gate')].sort((a, b) => (+a.dataset.x || 0) - (+b.dataset.x || 0))
  const span = 2200
  const xs = gates.map(g => +g.dataset.x || 0), lo = Math.min(...xs), hi = Math.max(...xs)
  gates.forEach(g => anim(g, [{ opacity: 0, transform: 'scale(.7)' }, { opacity: 1, transform: 'scale(1.12)', offset: .6 }, { opacity: 1, transform: 'none' }],
    { duration: MOTION.base, delay: 600 + ((+g.dataset.x - lo) / Math.max(1, hi - lo)) * span }))
  caption(svg.closest('.card'), ['Encode features', 'Run circuit', 'Measure', 'Score'], [0, 900, 2500, 3100], 3800)
}
function caption(card, steps, at, total) {
  if (!card || off()) return
  card.querySelector('.motion-caption')?.remove()
  if (getComputedStyle(card).position === 'static') card.style.position = 'relative'
  const c = document.createElement('div')
  c.className = 'motion-caption'
  c.setAttribute('aria-hidden', 'true')
  c.innerHTML = steps.map(s => `<span>${s}</span>`).join('<span style="border:0;background:none;opacity:1">→</span>')
  card.appendChild(c)
  const spans = [...c.children].filter((_, i) => i % 2 === 0)
  at.forEach((t, i) => setTimeout(() => { spans.forEach(s => s.classList.remove('on')); spans[i]?.classList.add('on') }, t))
  setTimeout(() => { const a = c.animate?.([{ opacity: 1 }, { opacity: 0 }], { duration: MOTION.base }); if (a) a.onfinish = () => c.remove(); else c.remove() }, total)
}
// Quantum ML — measurement histogram: bars grow while the shot counter ticks up to the real shot count
H['[data-anim="histogram"]'] = f => {
  if (small()) return
  f.querySelectorAll('.hist-bar').forEach((b, i) => anim(b, [{ transform: 'scaleY(0)', transformOrigin: '50% 100%', transformBox: 'fill-box' }, { transform: 'scaleY(1)', transformOrigin: '50% 100%', transformBox: 'fill-box' }], { duration: MOTION.long, delay: i * 8 }))
  f.querySelectorAll('[data-count]').forEach(n => countUp(n, MOTION.long))
}

// XGBoost vs AQSVC (and every bar list) — bars grow side by side, values count up
H['[data-anim="growx"]:not(.stopbar i):not(.ac-bar i)'] = (bar) => {
  const row = bar.parentElement?.parentElement
  growX(bar, 0, MOTION.slow)
  const v = row?.querySelector('.mono')
  if (v) countUp(v)
}
// line charts (alignment training, QAOA's real CVaR energy trace): the stored curve draws in
H['[data-anim="drawpath"]'] = p => draw(p, 0, MOTION.long)

// Decisions — batch 1 graph: nodes appear, compatible pairs draw, forbidden pairs flash red, nodes snap into packs
H['[data-anim="optgraph"]'] = async fig => {
  if (off() || small()) return
  const nodes = [...fig.querySelectorAll('.og-node')]
  const cand = [...fig.querySelectorAll('.e-cand')], forb = [...fig.querySelectorAll('.e-forbid')], packE = [...fig.querySelectorAll('.e-pack')]
  nodes.forEach((n, i) => {
    const t = `translate(${n.dataset.dx}px, ${n.dataset.dy}px)`
    n.animate([{ transform: t, opacity: 0 }, { transform: t, opacity: 1, offset: .25 }, { transform: t, opacity: 1, offset: .6 }, { transform: 'none', opacity: 1 }],
      { duration: 3200, delay: i * 12, easing: MOTION.easeInOut, fill: 'backwards' })
  })
  cand.forEach((e, i) => e.animate([{ opacity: 0, strokeDasharray: '1', strokeDashoffset: 1 }, { opacity: .35, strokeDashoffset: 0, offset: .4 }, { opacity: .35, strokeDashoffset: 0, offset: .75 }, { opacity: 0, strokeDashoffset: 0 }],
    { duration: 1900, delay: 350 + (i % 40) * 6, fill: 'none' }))
  forb.forEach(e => e.animate([{ opacity: 0 }, { opacity: 1, offset: .2 }, { opacity: 0, offset: .4 }, { opacity: 1, offset: .6 }, { opacity: 0 }], { duration: 1200, delay: 1100, fill: 'none' }))
  packE.forEach((e, i) => draw(e, 3000 + i * 30, MOTION.base))
  fig.querySelectorAll('.og-label').forEach((l, i) => anim(l, [{ opacity: 0 }, { opacity: 1 }], { delay: 2900 + i * 60 }))
  fig.querySelectorAll('[data-count]').forEach(n => countUp(n, MOTION.slow, 3000))
}

// Assess — needle sweeps to the combined answer, the models' band fades in, the verdict stamps
H['[data-anim="gauge"]'] = svg => {
  const needle = svg.querySelector('.g-needle')
  const a = needle?.style.getPropertyValue('--a')
  if (needle && a) anim(needle, [{ transform: 'rotate(-90deg)' }, { transform: `rotate(${a})` }], { duration: MOTION.slow, easing: 'cubic-bezier(.3, 1.4, .5, 1)' })
  svg.querySelectorAll('.g-band').forEach(b => anim(b, [{ opacity: 0 }, { opacity: 1 }], { duration: MOTION.base, delay: MOTION.slow }))
  const badge = svg.parentElement?.querySelector(':scope > .row [data-anim="stamp"]')
  stamp(badge, MOTION.slow)
}

// Upload — the dropped file flies into the zone; result rows tick in (table handler above)
document.addEventListener('drop', e => {
  const zone = e.target.closest?.('.drop')
  const f = e.dataTransfer?.files?.[0]
  if (!zone || !f || off()) return
  const chip = document.createElement('div')
  chip.className = 'motion-file'
  chip.textContent = f.name
  chip.style.left = `${e.clientX}px`; chip.style.top = `${e.clientY}px`
  document.body.appendChild(chip)
  const r = zone.getBoundingClientRect()
  const a = chip.animate([{ transform: 'translate(-50%, -50%) scale(1)', opacity: 1 },
    { transform: `translate(${r.left + r.width / 2 - e.clientX}px, ${r.top + r.height / 2 - e.clientY}px) translate(-50%, -50%) scale(.6)`, opacity: 0 }],
  { duration: MOTION.slow, easing: MOTION.easeInOut })
  a.onfinish = () => chip.remove()
}, true)

// Marketplace — the link between each matched pack and buyer draws, then the matched attributes tick green
H['[data-anim="matchlinks"]'] = box => box.querySelectorAll('.ml-row').forEach((r, i) => {
  riseIn(r, i * 160)
  draw(r.querySelector('.ml-line line'), i * 160 + 200, MOTION.base)
  r.querySelectorAll('.ml-tick').forEach((t, j) => anim(t, [{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { delay: i * 160 + 500 + j * 110 }))
})

// Evidence log — lines arrive from the top in order; run IDs flash once
H['.card table.small tbody tr.click'] = tr => {
  const i = [...tr.parentElement.children].indexOf(tr)
  if (i > 40) return
  anim(tr, [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }], { duration: MOTION.fast, delay: i * 40 })
  anim(tr.querySelector('.mono'), [{ opacity: 1 }, { opacity: .25 }, { opacity: 1 }], { duration: MOTION.base, delay: i * 40 + MOTION.fast, fill: 'none' })
}

// ----------------------------------------------------------------------------- A1 ticker speed (readable)
function tuneTicker(m) {
  const track = m.querySelector('.marquee-track')
  if (!track) return
  const speed = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ticker-speed')) || MOTION.tickerSpeed
  const half = track.scrollWidth / 2                                   // the track holds the text twice
  track.style.setProperty('--ticker-duration', `${Math.max(10, half / speed).toFixed(1)}s`)
}
const TICKER = '.marquee[data-anim="ticker"]'

// ----------------------------------------------------------------------------- wiring
const seen = new WeakSet()
const io = 'IntersectionObserver' in window ? new IntersectionObserver(entries => entries.forEach(en => {
  if (!en.isIntersecting) return
  io.unobserve(en.target)
  play(en.target)
}), { threshold: 0.15 }) : null

function play(el) {
  if (off()) return
  for (const [sel, fn] of Object.entries(H)) if (el.matches(sel)) { try { fn(el) } catch (err) { console.debug('motion', sel, err) } }
}

function scan(root) {
  if (!(root instanceof Element)) return
  const list = [root, ...root.querySelectorAll('*')]
  for (const el of list) {
    if (el.matches?.(TICKER)) tuneTicker(el)
    if (seen.has(el)) continue
    if (Object.keys(H).some(sel => el.matches?.(sel))) {
      seen.add(el)
      if (io) io.observe(el); else play(el)
    }
  }
}

function crossfade(main) {
  const first = main.firstElementChild
  anim(first, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: MOTION.fast + 60 })
}

function start() {
  const root = document.getElementById('root') || document.body
  if (!reduced()) document.documentElement.classList.add('motion-on')
  // nav: staggered fade-in on load
  setTimeout(() => document.querySelectorAll('.nav button').forEach((b, i) => anim(b, [{ opacity: 0, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'none' }], { duration: MOTION.base, delay: i * 35 })), 60)
  let lastPage = location.hash
  new MutationObserver(muts => {
    for (const m of muts) m.addedNodes.forEach(n => scan(n))
    if (location.hash !== lastPage) { lastPage = location.hash; const main = document.querySelector('main'); if (main) crossfade(main) }
    // rows replaced by a filter / sort / page change re-animate their table
    for (const m of muts) if (m.target.matches?.('.fleet-table tbody') && m.addedNodes.length) play(m.target)
  }).observe(root, { childList: true, subtree: true })
  scan(root)
  // replay a section's animations when its Explain button is pressed
  document.addEventListener('click', e => {
    const b = e.target.closest?.('.explain-btn')
    if (!b) return
    const sec = b.closest('.card, .oc, .page-head, .arch, section, .drawer')
    if (sec) replayIn(sec)
  })
  window.addEventListener('resize', () => document.querySelectorAll(TICKER).forEach(tuneTicker))
  // hidden tab: one-shot animations jump to their real end state (never left half-way); only the idle shimmer pauses
  document.addEventListener('visibilitychange', () => document.getAnimations?.().forEach(a => {
    const infinite = a.effect?.getComputedTiming?.().iterations === Infinity
    if (document.hidden) { if (infinite) a.pause(); else { try { a.finish() } catch { a.cancel() } } } else if (infinite) a.play()
  }))
}

function replayIn(sec) {
  const els = [sec, ...sec.querySelectorAll('*')].filter(el => Object.keys(H).some(s => el.matches?.(s)))
  els.forEach(play)
}

window.__motion = {
  replay(tab) {
    if (tab) location.hash = tab
    setTimeout(() => replayIn(document.querySelector('main') || document.body), tab ? 400 : 0)
  },
  disable() {
    disabled = true
    document.documentElement.classList.remove('motion-on')
    document.getAnimations?.().forEach(a => { try { a.finish() } catch { a.cancel() } })
  },
  enable() { disabled = false; if (!reduced()) document.documentElement.classList.add('motion-on') },
  config: MOTION,
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start()

// Explanatory visuals (Part B). Each one renders its FINAL state from real stored data; cellfee-motion.js only
// animates how it gets there (transform / opacity / stroke-dashoffset), so with motion off the picture is identical.
import { ACTION_COLOR } from './charts.jsx'
import { confText } from './usageFormat.js'

/** Decisions: batch 1 as a graph — compatible pairs, forbidden pairs, then the real packs. */
export function OptGraph({ R }) {
  const ids = R.qml.kernel_ids
  const K = R.qml.fleet_kernel
  const by = Object.fromEntries(R.fleet.filter(b => b.batch === 1).map(b => [b.id, b]))
  const B = ids.map(id => by[id]).filter(Boolean)
  if (B.length !== ids.length) return null
  const W = 640, H = 262, cx = W / 2, cy = 132, r = 104
  const packs = Object.entries(R.packs).filter(([, c]) => by[c[0]])
  const groups = [...packs.map(([name, cells]) => ({ name, ids: cells, kind: 'reuse' })),
    { name: 'TEST', ids: B.filter(b => b.action === 'test').map(b => b.id), kind: 'test' },
    { name: 'RECYCLE', ids: B.filter(b => b.action === 'recycle').map(b => b.id), kind: 'recycle' }].filter(g => g.ids.length)
  const colsOf = g => Math.min(g.kind === 'reuse' ? 2 : 4, g.ids.length)
  const widths = groups.map(g => colsOf(g) * 24 + 26)
  const scale = Math.min(1, (W - 40) / (widths.reduce((a, b) => a + b, 0) + 16 * (groups.length - 1)))
  const final = {}, labels = []
  let x = 20
  groups.forEach((g, gi) => {
    const cols = colsOf(g), w = widths[gi] * scale
    g.ids.forEach((id, k) => { final[id] = [x + 13 * scale + (k % cols) * 24 * scale + 6, 92 + Math.floor(k / cols) * 24] })
    const cap = g.ids.reduce((a, id) => a + by[id].soh * R.assumptions.NOMINAL_CAPACITY_AH, 0)
    labels.push({ x: x + w / 2, name: g.name, cap, kind: g.kind })
    x += w + 16 * scale
  })
  const start = Object.fromEntries(ids.map((id, i) => [id, [cx + r * Math.cos((2 * Math.PI * i) / ids.length), cy + r * Math.sin((2 * Math.PI * i) / ids.length)]]))
  const cand = ids.filter(id => !by[id].reuse_blocked)
  const edges = []
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
    const a = ids[i], b = ids[j]
    if (!cand.includes(a) || !cand.includes(b)) continue
    const forbid = K[i][j] < R.assumptions.KERNEL_FORBID_BELOW || Math.abs(by[a].soh - by[b].soh) > R.assumptions.SOH_SPREAD_FORBID
    const same = by[a].pack && by[a].pack === by[b].pack
    edges.push({ a, b, kind: same ? 'e-pack' : forbid ? 'e-forbid' : 'e-cand' })
  }
  const nForbid = edges.filter(e => e.kind === 'e-forbid').length
  return (
    <figure className="optgraph" data-anim="optgraph" style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
        aria-label={`Batch 1: ${ids.length} batteries, ${edges.length - nForbid} compatible pairs, ${nForbid} forbidden pairs, grouped into ${packs.length} packs, test and recycle`}>
        {edges.map(e => {
          const [p, q] = e.kind === 'e-pack' ? [final[e.a], final[e.b]] : [start[e.a], start[e.b]]
          return <line key={e.a + e.b} className={`og-edge ${e.kind}`} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} pathLength="1" />
        })}
        {ids.map(id => {
          const [fx, fy] = final[id], [sx, sy] = start[id]
          return <circle key={id} className="og-node" cx={fx} cy={fy} r="8" style={{ fill: ACTION_COLOR[by[id].action] }}
            data-dx={(sx - fx).toFixed(1)} data-dy={(sy - fy).toFixed(1)}><title>{`${id}: ${Math.round(by[id].soh * 100)}% health, ${by[id].action}${by[id].pack ? ` in ${by[id].pack}` : ''}`}</title></circle>
        })}
        {labels.map(l => (
          <g key={l.name} className="og-label">
            <text x={l.x} y={66} textAnchor="middle" className="og-name">{l.name}</text>
            {l.kind === 'reuse' && <text x={l.x} y={78} textAnchor="middle" className="og-cap"><tspan data-count={l.cap.toFixed(2)} data-decimals="2">{l.cap.toFixed(2)}</tspan> Ah</text>}
          </g>
        ))}
        <text x={W - 8} y={H - 8} textAnchor="end" className="og-cap">{edges.length - nForbid} compatible pairs · {nForbid} forbidden (red) · QpiAI Opt result, batch 1</text>
      </svg>
    </figure>
  )
}

/** Quantum ML: all-zero counts of the stored shot-based kernel circuits. */
export function ShotHistogram({ ft }) {
  const W = 620, H = 150, m = { l: 34, b: 22, t: 8 }
  const n = ft.values.length, bw = (W - m.l - 8) / n
  const h = v => v * (H - m.b - m.t)
  return (
    <figure style={{ margin: '10px 0 0' }} data-anim="histogram">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`All-zero outcome counts for ${n} kernel circuits, ${ft.shots} shots each`}>
        <line x1={m.l} x2={W - 4} y1={H - m.b} y2={H - m.b} stroke="var(--ink)" />
        {[0, 0.5, 1].map(v => <text key={v} x={m.l - 4} y={H - m.b - h(v) + 3} textAnchor="end" className="og-cap">{Math.round(v * ft.shots)}</text>)}
        {ft.values.map((v, i) => <rect key={i} className="hist-bar" x={m.l + i * bw + 1} y={H - m.b - h(v)} width={Math.max(1, bw - 2)} height={h(v)}><title>{`pair ${i + 1}: ${Math.round(v * ft.shots)} of ${ft.shots} shots all-zero (exact ${ft.exact[i].toFixed(3)})`}</title></rect>)}
        <text x={W - 6} y={14} textAnchor="end" className="og-cap">shots: <tspan data-count={ft.shots}>{ft.shots}</tspan> per circuit</text>
        <text x={m.l} y={H - 6} className="og-cap">{n} kernel circuits on {ft.device} · bar = count of the all-zero outcome = k(xᵢ, xⱼ) × shots</text>
      </svg>
    </figure>
  )
}

/** Marketplace: each real match drawn as pack — line — buyer, with the attributes that passed. */
export function MatchLinks({ data, apps }) {
  if (!data.matches.length) return null
  return (
    <div className="matchlinks" data-anim="matchlinks">
      {data.matches.map(m => {
        const L = m.listing_detail, Bu = m.buyer_detail
        const app = apps.find(a => a.id === Bu.application)
        const conf = L.app_confidence ? L.app_confidence[Bu.application] : null
        const ticks = [
          ['capacity', `${L.energy_wh} Wh ≥ ${Bu.min_energy_wh} Wh`],
          ['chemistry', `${L.chemistry.split(' ')[0]} allowed`],
          ['application', app ? app.name : Bu.application],
          ['confidence', conf != null ? confText(conf) : 'seller evidence'],
        ]
        return (
          <div key={m.buyer} className="ml-row" data-anim="mlrow">
            <span className="ml-box mono">{m.listing}</span>
            <svg className="ml-line" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="5" x2="100" y2="5" pathLength="1" /></svg>
            <span className="ml-box">{Bu.name}</span>
            <span className="ml-ticks small">{ticks.map(([k, v]) => <span key={k} className="ml-tick" data-anim="tick">✓ {k}: {v}</span>)}</span>
          </div>
        )
      })}
    </div>
  )
}

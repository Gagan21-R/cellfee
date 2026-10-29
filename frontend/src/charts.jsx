import { useRef, useState } from 'react'

export const ACTION_COLOR = { reuse: 'var(--series-3)', test: 'var(--series-4)', recycle: 'var(--series-2)' }
export const ACTION_LABEL = { reuse: 'Reuse', test: 'Full test', recycle: 'Recycle' }

export function useTip() {
  const [tip, setTip] = useState(null)
  const show = (e, content) => setTip({ x: e.clientX + 14, y: e.clientY + 14, content })
  const hide = () => setTip(null)
  const node = tip && (
    <div className="tip" style={{ left: Math.min(tip.x, window.innerWidth - 310), top: tip.y }}>{tip.content}</div>
  )
  return { show, hide, node }
}

const ticks = (lo, hi, n = 5) => Array.from({ length: n }, (_, i) => lo + (i * (hi - lo)) / (n - 1))

/** Sequential heatmap for a kernel matrix. */
export function Heatmap({ matrix, labels, title }) {
  const t = useTip()
  const n = matrix.length, cell = Math.max(8, Math.min(16, Math.floor(440 / n)))
  const pad = 46, W = pad + n * cell + 4, H = pad + n * cell + 4
  const color = v => {
    const stops = ['--seq-100', '--seq-300', '--seq-500', '--seq-700']
    const s = Math.max(0, Math.min(1, v)) * 3, k = Math.min(2, Math.floor(s))
    return `color-mix(in oklab, var(${stops[k + 1]}) ${((s - k) * 100).toFixed(0)}%, var(${stops[k]}))`
  }
  return (
    <div>
      <div className="legend"><span>0</span>
        <span style={{ width: 120, height: 10, borderRadius: 3, background: 'linear-gradient(90deg, var(--seq-100), var(--seq-300), var(--seq-500), var(--seq-700))' }} />
        <span>1 · {title}</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W * 1.25 }} role="img" aria-label={title}>
        {labels.map((l, i) => (
          <g key={l}>
            {i % 2 === 0 && <text x={pad - 4} y={pad + i * cell + cell * 0.75} textAnchor="end" style={{ fontSize: 9 }}>{l}</text>}
            {i % 2 === 0 && <text transform={`translate(${pad + i * cell + cell * 0.7} ${pad - 4}) rotate(-60)`} style={{ fontSize: 9 }}>{l}</text>}
          </g>
        ))}
        {matrix.map((row, i) => row.map((v, j) => (
          <rect key={`${i}-${j}`} x={pad + j * cell} y={pad + i * cell} width={cell - 1} height={cell - 1} fill={color(v)}
            onMouseMove={e => t.show(e, <><b>{labels[i]} × {labels[j]}</b>k = {v.toFixed(3)}</>)} onMouseLeave={t.hide} />
        )))}
      </svg>
      {t.node}
    </div>
  )
}

/** Simple single-series line with hover crosshair. */
export function LineChart({ values, yLabel, xLabel, height = 200, color = 'var(--series-1)', refLine }) {
  const t = useTip()
  const ref = useRef()
  const [hover, setHover] = useState(null)
  const W = 520, H = height, m = { l: 44, r: 12, t: 10, b: 30 }
  const lo = Math.min(...values, refLine ?? Infinity), hi = Math.max(...values, refLine ?? -Infinity)
  const pad = (hi - lo) * 0.08 || 0.01
  const sx = i => m.l + (i / Math.max(1, values.length - 1)) * (W - m.l - m.r)
  const sy = v => H - m.b - ((v - lo + pad) / (hi - lo + 2 * pad)) * (H - m.t - m.b)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join('')
  const onMove = e => {
    const r = ref.current.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * W
    const i = Math.max(0, Math.min(values.length - 1, Math.round(((x - m.l) / (W - m.l - m.r)) * (values.length - 1))))
    setHover(i); t.show(e, <><b>{xLabel} {i + 1}</b>{yLabel}: {values[i].toFixed(4)}</>)
  }
  return (
    <div>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" onMouseMove={onMove} onMouseLeave={() => { setHover(null); t.hide() }}>
        {ticks(lo, hi, 4).map(v => (
          <g key={v}><line x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" />
            <text x={m.l - 6} y={sy(v) + 4} textAnchor="end">{v.toFixed(2)}</text></g>
        ))}
        {refLine != null && <line x1={m.l} x2={W - m.r} y1={sy(refLine)} y2={sy(refLine)} stroke="var(--text-muted)" strokeDasharray="4 4" />}
        <path d={d} fill="none" stroke={color} strokeWidth="2" data-anim="drawpath" pathLength="1" />
        {hover != null && <><line x1={sx(hover)} x2={sx(hover)} y1={m.t} y2={H - m.b} stroke="var(--text-muted)" />
          <circle cx={sx(hover)} cy={sy(values[hover])} r="4.5" fill={color} stroke="var(--surface-1)" strokeWidth="2" /></>}
        <text x={(W + m.l) / 2} y={H - 6} textAnchor="middle">{xLabel}</text>
      </svg>
      {t.node}
    </div>
  )
}

/** Horizontal bars, one series; highlight one key. */
export function BarList({ rows, format = v => v.toFixed(3), highlight, unit = '' }) {
  const t = useTip()
  const max = Math.max(...rows.map(r => Math.abs(r.value)), 1e-9)
  return (
    <div className="grid" style={{ gap: 8 }}>
      {rows.map(r => (
        <div key={r.key} onMouseMove={e => t.show(e, <><b>{r.label}</b>{format(r.value)}{unit}</>)} onMouseLeave={t.hide}>
          <div className="row spread small"><span>{r.label}</span><span className="mono">{format(r.value)}{unit}</span></div>
          <div style={{ height: 10, background: 'var(--surface-2)', borderRadius: 4 }}>
            <div data-anim="growx" style={{ width: `${(Math.abs(r.value) / max) * 100}%`, height: '100%', borderRadius: '0 4px 4px 0',
              background: r.key === highlight ? 'var(--series-1)' : 'var(--text-muted)', opacity: r.key === highlight ? 1 : 0.55 }} />
          </div>
        </div>
      ))}
      {t.node}
    </div>
  )
}

/** One-layer schematic of the feature-map circuit. */
export function CircuitDiagram({ n = 6, labels }) {
  const W = 620, row = 30, H = n * row + 24, x0 = 92
  const gates = []
  for (let q = 0; q < n; q++) {
    gates.push({ x: x0 + 10, q, t: 'RY' }, { x: x0 + 60, q, t: 'RZ' })
  }
  const pairs = Array.from({ length: n }, (_, q) => [q, (q + 1) % n])
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Feature map circuit, one layer, then measurement" data-anim="circuit">
      {Array.from({ length: n }, (_, q) => (
        <g key={q}>
          <text x="4" y={18 + q * row + 4} style={{ fontSize: 10.5 }}>q{q} · {labels?.[q] ?? ''}</text>
          <line className="circuit-line" x1={x0} x2={W - 30} y1={18 + q * row} y2={18 + q * row} pathLength="1" />
          <g className="gate meas" data-x={W - 28}><rect x={W - 28} y={8 + q * row} width="22" height="20" />
            <path d={`M${W - 24} ${24 + q * row} a7 7 0 0 1 14 0 M${W - 17} ${24 + q * row} l5 -8`} fill="none" stroke="currentColor" /></g>
        </g>
      ))}
      {gates.map((g, i) => (
        <g className="gate" key={i} data-x={g.x}><rect x={g.x} y={6 + g.q * row} width="38" height="24" />
          <text x={g.x + 19} y={22 + g.q * row} textAnchor="middle">{g.t}</text></g>
      ))}
      {pairs.map(([a, b], i) => {
        const x = x0 + 120 + i * 58, y1 = 18 + a * row, y2 = 18 + b * row
        return (
          <g key={i} className="gate" data-x={x}>
            <line x1={x + 19} x2={x + 19} y1={y1} y2={y2} stroke="var(--accent)" strokeWidth="1.2" />
            <rect x={x} y={y1 - 10} width="38" height="20" /><text x={x + 19} y={y1 + 4} textAnchor="middle">ZZ</text>
            <rect x={x} y={y2 - 10} width="38" height="20" /><text x={x + 19} y={y2 + 4} textAnchor="middle">ZZ</text>
          </g>
        )
      })}
      <text x={W - 10} y={H - 4} textAnchor="end">× layers (data re-uploading) · then U(x′)† for the kernel</text>
    </svg>
  )
}

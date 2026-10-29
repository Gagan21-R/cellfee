import { inr } from './usageFormat.js'
// Small, project-specific animations that replace the battery photos.
// Pure SVG + CSS (styles.css → "motifs"), black outlines in the brutalist style; all motion stops
// under prefers-reduced-motion. The fleet and compare motifs are drawn from the real results.

const COLOR = { reuse: 'var(--green)', test: 'var(--amber)', recycle: 'var(--red)' }

/** Overview hero: every battery in the fleet as a cell, filling to its estimated health, coloured by decision. */
export function FleetCells({ cells }) {
  const cols = 11, w = 30, h = 52, gx = 10, gy = 18
  const rows = Math.ceil(cells.length / cols)
  const W = cols * (w + gx) - gx + 4, H = rows * (h + gy) - gy + 8 + 6
  return (
    <svg className="motif m-cells" viewBox={`-2 -6 ${W} ${H}`} role="img"
      aria-label={`All ${cells.length} batteries in the fleet, each filled to its estimated health and coloured by its decision`}>
      {cells.map((b, k) => {
        const x = (k % cols) * (w + gx), y = Math.floor(k / cols) * (h + gy)
        const fill = Math.max(0.05, Math.min(1, (b.soh - 0.75) / 0.25)) * (h - 6)
        return (
          <g key={b.id} transform={`translate(${x} ${y})`} style={{ '--d': `${k * 45}ms` }}>
            <rect x={w / 2 - 6} y={-5} width={12} height={5} className="cap" />
            <rect width={w} height={h} className="body" />
            <rect x={3} y={h - 3 - fill} width={w - 6} height={fill} className="lvl" style={{ fill: COLOR[b.action] }} />
            <title>{`${b.id}: ${Math.round(b.soh * 100)}% health, XGBoost ${Math.round(b.p_xgb * 100)} / AQSVC ${Math.round(b.p_aqsvc * 100)}, ${b.action}`}</title>
          </g>
        )
      })}
      <rect className="scan" x={-2} y={-6} width={6} height={H} />
    </svg>
  )
}

/** Fleet: cells drop from a conveyor into reuse / test / recycle bins. */
function Sorting() {
  const drops = [['reuse', 0], ['recycle', 1], ['test', 2], ['reuse', 3], ['recycle', 4], ['reuse', 5]]
  const bin = { reuse: 40, test: 150, recycle: 260 }
  return (
    <svg className="motif m-sort" viewBox="0 0 320 180" role="img" aria-label="Batteries being sorted into reuse, test and recycle bins">
      <line x1="10" y1="34" x2="310" y2="34" className="belt" />
      {drops.map(([a, k]) => (
        <g key={k} className="drop" style={{ '--d': `${k * 0.9}s`, '--x': `${bin[a] + 16}px` }}>
          <rect x="-9" y="-30" width="18" height="28" className="body" />
          <rect x="-6" y="-14" width="12" height="9" style={{ fill: COLOR[a] }} />
        </g>
      ))}
      {Object.entries(bin).map(([a, x]) => (
        <g key={a}><path d={`M${x} 118 v46 h52 v-46`} className="bin" /><text x={x + 26} y="176" className="lbl">{a.toUpperCase()}</text></g>
      ))}
    </svg>
  )
}

/** Battery passports: a report card with a scanning line and a stamp. */
function Passport() {
  return (
    <svg className="motif m-pass" viewBox="0 0 320 180" role="img" aria-label="A battery passport being checked and stamped">
      <rect x="70" y="14" width="150" height="156" className="paper" />
      <rect x="84" y="28" width="30" height="40" className="body" /><rect x="88" y="44" width="22" height="20" className="lvl-g" />
      {[30, 42, 54].map(y => <rect key={y} x="124" y={y} width="80" height="6" className="ln" />)}
      {[86, 100, 114, 128, 142].map((y, k) => <rect key={y} x="84" y={y} width={k % 2 ? 96 : 120} height="6" className="ln" />)}
      <rect x="70" y="14" width="150" height="5" className="scanbar" />
      <g className="stamp"><rect x="186" y="104" width="96" height="40" /><text x="234" y="130">PASSPORT</text></g>
    </svg>
  )
}

/** Quantum ML: six qubit wires, rotation gates, and pulses travelling through the circuit. */
function Circuit() {
  return (
    <svg className="motif m-circ" viewBox="0 0 320 180" role="img" aria-label="A six-qubit quantum circuit with signals passing through its gates">
      {[0, 1, 2, 3, 4, 5].map(q => {
        const y = 22 + q * 27
        return (
          <g key={q}>
            <line x1="14" y1={y} x2="306" y2={y} className="wire" />
            <rect x="52" y={y - 8} width="22" height="16" className="gate" /><rect x="96" y={y - 8} width="22" height="16" className="gate" />
            <circle cx="0" cy={y} r="4" className="pulse" style={{ '--d': `${q * 0.35}s` }} />
          </g>
        )
      })}
      {[0, 1, 2, 3, 4].map(q => <line key={q} x1={150 + q * 26} y1={22 + q * 27} x2={150 + q * 26} y2={49 + q * 27} className="ent" />)}
      <rect x="264" y="10" width="34" height="160" className="meter" />
      <text x="281" y="94" className="lbl" transform="rotate(-90 281 94)">MEASURE</text>
    </svg>
  )
}

/** Results: the four plans' realised values (real numbers) growing as bars. */
function Bars({ R }) {
  const keys = ['rule', 'xgb', 'aqsvc', 'both'], lab = ['RULE', 'XGBOOST', 'AQSVC', 'BOTH']
  const v = keys.map(k => R.comparison[k].realized_value), max = Math.max(...v)
  return (
    <svg className="motif m-bars" viewBox="0 0 320 180" role="img" aria-label={`Value of each plan: ${keys.map((k, i) => `${lab[i]} ${inr(v[i])}`).join(', ')}`}>
      <line x1="20" y1="150" x2="300" y2="150" className="axis" />
      {v.map((x, i) => {
        const h = (x / max) * 118
        return (
          <g key={i}>
            <rect x={36 + i * 68} y={150 - h} width="40" height={h} className="bar" style={{ '--d': `${i * 0.25}s`, fill: i === 3 ? 'var(--yellow)' : 'var(--card)' }} />
            <text x={56 + i * 68} y="168" className="lbl">{lab[i]}</text>
            <text x={56 + i * 68} y={144 - h} className="val">{inr(x)}</text>
          </g>
        )
      })}
    </svg>
  )
}

/** Decisions: eight cells link up and settle into two matched packs. */
function Packs() {
  const pts = [[60, 50], [100, 34], [92, 92], [52, 112], [228, 46], [268, 70], [222, 110], [262, 130]]
  return (
    <svg className="motif m-packs" viewBox="0 0 320 180" role="img" aria-label="Eight compatible cells grouped into two packs">
      <rect x="28" y="20" width="104" height="122" className="pack a" /><rect x="196" y="24" width="104" height="128" className="pack b" />
      {[[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4]].map(([i, j], k) => (
        <line key={k} x1={pts[i][0]} y1={pts[i][1]} x2={pts[j][0]} y2={pts[j][1]} className="edge" style={{ '--d': `${k * 0.15}s` }} />
      ))}
      {pts.map(([x, y], k) => <circle key={k} cx={x} cy={y} r="9" className={`node ${k < 4 ? 'a' : 'b'}`} style={{ '--d': `${k * 0.12}s` }} />)}
      <text x="80" y="164" className="lbl">PACK-1</text><text x="248" y="170" className="lbl">PACK-2</text>
    </svg>
  )
}

/** Assess: a battery being scanned while a health gauge sweeps. */
function Gauge() {
  return (
    <svg className="motif m-gauge" viewBox="0 0 320 180" role="img" aria-label="A battery being scanned while its health gauge reads out">
      <rect x="40" y="38" width="62" height="112" className="body" /><rect x="58" y="28" width="26" height="10" className="body" />
      <rect x="47" y="45" width="48" height="98" className="lvl-anim" />
      <rect x="34" y="38" width="74" height="4" className="scanbar v" />
      <path d="M160 140 A70 70 0 0 1 300 140" className="arc" />
      <g className="needle"><line x1="230" y1="140" x2="230" y2="84" /><circle cx="230" cy="140" r="7" /></g>
      <text x="230" y="168" className="lbl">HEALTH</text>
    </svg>
  )
}

/** Marketplace: a pack and a buyer connect, then a match tick appears. */
function Match() {
  return (
    <svg className="motif m-match" viewBox="0 0 320 180" role="img" aria-label="A battery pack being matched with a buyer">
      <rect x="22" y="56" width="86" height="68" className="box" /><text x="65" y="95" className="lbl">PACK</text>
      <rect x="212" y="56" width="86" height="68" className="box" /><text x="255" y="95" className="lbl">BUYER</text>
      <line x1="108" y1="90" x2="212" y2="90" className="link" />
      <g className="tick"><rect x="146" y="68" width="28" height="28" /><path d="M152 82 l6 6 l11 -12" /></g>
    </svg>
  )
}

/** Environmental impact: a slow reuse loop around a cell. */
function Loop() {
  return (
    <svg className="motif m-loop" viewBox="0 0 320 180" role="img" aria-label="A battery going round a reuse loop instead of being thrown away">
      <g className="ring">
        <path d="M160 26 A64 64 0 0 1 224 90" /><path d="M224 90 A64 64 0 0 1 160 154" /><path d="M160 154 A64 64 0 0 1 96 90" /><path d="M96 90 A64 64 0 0 1 160 26" />
        <path d="M218 76 l6 14 l9 -12" className="head" /><path d="M110 104 l-14 -14 l-9 12" className="head" />
      </g>
      <rect x="146" y="66" width="28" height="48" className="body" /><rect x="153" y="60" width="14" height="6" className="body" />
      <rect x="150" y="82" width="20" height="28" className="lvl-g" />
      <text x="56" y="40" className="lbl">REUSE</text><text x="264" y="152" className="lbl">LESS CO₂</text>
    </svg>
  )
}

/** Upload: a test-result file feeds both models at the same moment. */
function Upload() {
  return (
    <svg className="motif m-up" viewBox="0 0 320 180" role="img" aria-label="A test-result file being read by the classical and quantum models at the same time">
      <g className="sheet">
        <rect x="34" y="30" width="84" height="112" className="paper" />
        <text x="76" y="52" className="lbl">CSV</text>
        {[64, 78, 92, 106, 120].map(y => <rect key={y} x="46" y={y} width="60" height="5" className="ln" />)}
      </g>
      <path d="M128 86 H150 V58 H180 M150 86 V114 H180" className="wire2" />
      <circle r="4" className="ping p1" /><circle r="4" className="ping p2" />
      <rect x="184" y="40" width="104" height="36" className="box" /><text x="236" y="62" className="lbl">XGBOOST</text>
      <rect x="184" y="96" width="104" height="36" className="box q" /><text x="236" y="118" className="lbl">AQSVC</text>
    </svg>
  )
}

const MOTIFS = { sorting: Sorting, passport: Passport, circuit: Circuit, bars: Bars, packs: Packs, gauge: Gauge, match: Match, loop: Loop, upload: Upload }

export function Motif({ kind, R }) {
  const M = MOTIFS[kind]
  return M ? <M R={R} /> : null
}

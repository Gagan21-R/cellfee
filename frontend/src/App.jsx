import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { ACTION_COLOR, ACTION_LABEL, BarList, CircuitDiagram, Heatmap, LineChart } from './charts.jsx'
import { Explain, GuideProvider, useGuide } from './Assistant.jsx'
import { FleetCells, Motif } from './motifs.jsx'
import { AppConfidence, PackUsage, StateBadge, UsageBaseline } from './usage.jsx'
import { confText, inr } from './usageFormat.js'
import { MatchLinks, OptGraph, ShotHistogram } from './explainers.jsx'
import { Browse, Mine, Partners, Sell } from './marketplace.jsx'
import { MarketAssistant } from './marketAssistant.jsx'
import { answer as guideAnswer, buildKB } from './explain.js'
import { assessPlain, clearDownloads, downloadAssessPDF, downloadFleetPDF, downloadJSON, downloadPassportPDF, downloadUploadPDF, fleetPlain, passportPlain, recentDownloads, saveText, uploadPlain } from './report.js'

const api = (path, body) =>
  fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
    .then(async r => { if (!r.ok) throw new Error((await r.text()) || r.statusText); return r.json() })

const PAGES = [
  ['overview', 'Overview'], ['fleet', 'Fleet & passports'], ['qml', 'Quantum ML (QCloud)'],
  ['compare', 'XGBoost vs AQSVC'], ['opt', 'Decisions (QpiAI Opt)'], ['assess', 'Assess & upload'],
  ['market', 'Marketplace'], ['env', 'Environmental impact'], ['evidence', 'Evidence log'],
]
const f2 = v => (v == null ? '—' : Number(v).toFixed(2))
const f3 = v => (v == null ? '—' : Number(v).toFixed(3))
const money = inr   // all money is in Indian rupees
const pc = v => (v == null ? '—' : `${Math.round(Number(v) * 100)}%`)

/** One model's answer as a compact cell: chance of a long life ahead, ✓ / ✕ for its vote. */
function ModelCell({ p }) {
  return <span className={`mp ${p >= 0.5 ? 'yes' : 'no'}`} title={`${pc(p)} chance of a long life ahead`}>{Math.round(p * 100)}<small>%</small><i aria-hidden="true">{p >= 0.5 ? '✓' : '✕'}</i></span>
}

function ActionTag({ a }) {
  return <span className={`tag t-${a}`}>{ACTION_LABEL[a]}</span>
}
function GradeBadge({ g }) {
  const title = { A: 'Grade A', B: 'Grade B', C: 'Grade C — recycling route', T: 'Needs full test' }[g]
  return <span className="grade" title={title}>{g}</span>
}
function Stat({ label, value, note, explain }) {
  return <div className="card stat">{explain && <Explain id={explain} label="Explain" />}<div className="label">{label}</div><div className="value">{value}</div>{note && <div className="note">{note}</div>}</div>
}
function Head({ title, children, explain, motif, R }) {
  const text = <><div className="row spread"><h2>{title}</h2>{explain && <Explain id={explain} label="Explain this page" />}</div><p>{children}</p></>
  if (!motif) return <div className="page-head">{text}</div>
  return (
    <div className="page-head banner">
      <div className="banner-text">{text}</div>
      <div className="banner-img motif-box"><Motif kind={motif} R={R} /></div>
    </div>
  )
}

export default function App() {
  // old links keep working: #passports opens the merged Fleet & passports tab, #upload the merged Assess & upload tab
  const fromHash = () => { const h = { passports: 'fleet', upload: 'assess' }[window.location.hash.slice(1)] || window.location.hash.slice(1); return PAGES.some(([k]) => k === h) ? h : null }
  const [page, setPage] = useState(() => { try { return fromHash() || localStorage.getItem('cellfee-page') || 'overview' } catch { return fromHash() || 'overview' } })
  useEffect(() => { const on = () => { const h = fromHash(); if (h) setPage(h) }; window.addEventListener('hashchange', on); return () => window.removeEventListener('hashchange', on) }, [])
  const [R, setR] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api('/api/results').then(setR).catch(e => setErr(String(e))) }, [])
  useEffect(() => { try { localStorage.setItem('cellfee-page', page) } catch { /* storage unavailable */ } window.scrollTo(0, 0) }, [page])

  return (
    <GuideProvider R={R}>
    <div className="shell">
      <aside className="side">
        <div className="brand"><div className="brand-mark">C</div><h1>CELLFEE</h1></div>
        <div className="brand-sub">Give Retired Batteries a Second Life.</div>
        <a className="back-link" href="/">← Back to the story</a>
        <nav className="nav">
          {PAGES.map(([k, l], i) => (
            <button key={k} className={page === k ? 'on' : ''} onClick={() => setPage(k)}><span className="num">{i + 1}</span>{l}</button>
          ))}
        </nav>
        <div className="side-foot">
          {R && <>
            <div>QCloud key: <b>{R.sponsor_status.qcloud_key_configured ? 'configured' : 'not set (local sim)'}</b></div>
            <div>Opt key: <b>{R.sponsor_status.opt_key_configured ? 'configured' : 'not set (fallback)'}</b></div>
            <div style={{ marginTop: 6 }}>Run {R.generated} · rules v{R.rules_version}</div>
          </>}
        </div>
      </aside>
      <main>
        {err && <div className="callout warn">Could not load results: {err}. Start the API and run the pipeline first.</div>}
        {!R && !err && <p className="muted">Loading pipeline results…</p>}
        {R && page === 'overview' && <Overview R={R} go={setPage} />}
        {R && page === 'fleet' && <Fleet R={R} />}
        {R && page === 'qml' && <QML R={R} />}
        {R && page === 'compare' && <Compare R={R} />}
        {R && page === 'opt' && <Opt R={R} />}
        {R && page === 'assess' && <AssessUpload R={R} />}
        {R && page === 'market' && <Market R={R} />}
        {R && page === 'env' && <Env R={R} />}
        {R && page === 'evidence' && <Evidence R={R} />}
      </main>
    </div>
    </GuideProvider>
  )
}

/* ------------------------------------------------------------------ Overview */
const ICON = {
  data: <svg viewBox="0 0 24 24"><ellipse cx="12" cy="5.5" rx="7" ry="2.5" /><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5" /></svg>,
  prep: <svg viewBox="0 0 24 24"><path d="M4 5h16l-6 7.5V19l-4 1.5v-8L4 5z" /></svg>,
  ml: <svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>,
  quantum: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2" /><ellipse cx="12" cy="12" rx="10" ry="4" /><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(60 12 12)" /><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(120 12 12)" /></svg>,
  opt: <svg viewBox="0 0 24 24"><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="M7 6h10M6 8l5 8.3M18 8l-5 8.3" /></svg>,
  decision: <svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></svg>,
}
const TECH = {
  classical: { cls: '', label: 'Classical' },
  qcloud: { cls: 'qcloud', label: 'QpiAI QCloud' },
  opt: { cls: 'opt', label: 'QpiAI Opt' },
}

/** One architecture stage card; clicking it opens the stage's technical detail in the guide. */
function Stage({ n, icon, title, sub, status, tech, next, explain, i }) {
  const { explain: open } = useGuide()
  const band = tech === 'classical' && n === 6 ? 'result' : tech
  return (
    <li className={`st st-tech-${band}${next ? ' has-next' : ''}`} style={{ '--i': i }}>
      <button type="button" className="st-btn" onClick={() => open(explain)} aria-label={`${title}. Open technical detail`}>
        <div className="st-top">
          <span className="st-n" aria-hidden="true">0{n}</span>
          <span className="st-icon" aria-hidden="true">{ICON[icon]}</span>
          <span className="st-tech">{TECH[tech].label}</span>
        </div>
        <div className="st-body">
          <h4>{title}</h4>
          <p>{sub}</p>
          <div className="row"><span className={`st-status ${status.kind}`}><i aria-hidden="true" />{status.label}</span><span className="st-go">Detail →</span></div>
        </div>
      </button>
    </li>
  )
}

/** Adds .in once the element scrolls into view (stage reveal). */
function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (!('IntersectionObserver' in window)) { el.classList.add('in'); return }
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { el.classList.add('in'); io.disconnect() } }), { threshold: 0.12 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return ref
}

function SecTitle({ icon, children, as: H = 'h3', id }) {
  return <div className="sec-title"><span className="sec-icon" aria-hidden="true">{ICON[icon]}</span><H id={id}>{children}</H></div>
}

function Overview({ R, go }) {
  const counts = R.fleet.reduce((a, b) => ({ ...a, [b.action]: (a[b.action] || 0) + 1 }), {})
  const plan = R.plan, n = R.fleet.length, ss = R.sponsor_status
  const archRef = useReveal()
  const ok = { kind: 'ok', label: 'Operational' }
  const ticker = ['Reuse', 'Full test', 'Recycle', 'XGBoost', 'AQSVC', 'QpiAI QCloud', 'QpiAI Opt', ...Object.keys(R.packs), `${R.data.snapshots.toLocaleString()} real snapshots`, 'Second life']
  const C = R.comparison, sbs = R.side_by_side
  const reuseStates = R.fleet.filter(b => b.action === 'reuse').reduce((a, b) => ({ ...a, [b.state]: (a[b.state] || 0) + 1 }), {})
  const outcome = [
    { k: 'reuse', label: 'Reuse', chip: 'ok', color: 'var(--green)', bg: 'var(--mint)', v: counts.reuse || 0, explain: 'overview.actions' },
    { k: 'test', label: 'Full test', color: 'var(--amber)', bg: 'var(--peach)', v: counts.test || 0, explain: 'overview.actions' },
    { k: 'recycle', label: 'Recycle', color: 'var(--red)', bg: 'var(--pink)', v: counts.recycle || 0, explain: 'overview.actions' },
  ]
  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-text">
          <span className="eyebrow">✦ QML-03 · Retired EV battery qualification</span>
          <h1 id="hero-title" className="hero-title">CELLFEE</h1>
          <p className="hero-tag">Give Retired Batteries a Second Life.</p>
          <p className="hero-sub">Turn retired battery data into explainable second-life decisions.</p>
          <div className="chips-row">
            <span className={`chip${ss.qcloud_key_configured ? ' ok' : ''}`}>QpiAI QCloud {ss.qcloud_key_configured ? 'key on' : 'local'}</span>
            <span className={`chip${ss.opt_key_configured ? ' ok' : ''}`}>QpiAI Opt {ss.opt_key_configured ? 'key on' : 'fallback'}</span>
            <span className="chip">{R.data.snapshots.toLocaleString()} real snapshots</span>
            <span className="chip">Run {R.generated.slice(0, 10)}</span>
            <Explain id="page.overview" label="Explain" />
          </div>
          <div className="hero-actions">
            <button className="btn primary btn-lg" onClick={() => go('fleet')}>Explore the fleet →</button>
            <button className="btn btn-lg" onClick={() => document.getElementById('arch')?.scrollIntoView({ behavior: 'smooth' })}>View the workflow</button>
          </div>
        </div>
        <figure className="hero-figure motif-box">
          <FleetCells cells={R.fleet.filter(b => b.batch === 1)} />
          <figcaption className="small muted" style={{ fontFamily: 'var(--mono)', fontSize: 11, marginTop: 8 }}>BATCH 1 OF {R.fleet_plan.batches} · EACH BLOCK IS ONE BATTERY · FILL = HEALTH (75–100%) · GREEN REUSE · AMBER TEST · RED RECYCLE</figcaption>
        </figure>
      </section>

      <div className="marquee" data-anim="ticker" tabIndex={0} role="region" aria-label="Fleet ticker (hover or focus to pause)">
        <div className="marquee-track">{[...ticker, ...ticker].map((t, k) => <span key={k}>{t}</span>)}</div>
      </div>

      <SecTitle icon="decision">Fleet outcomes</SecTitle>
      <div className="outcomes">
        <div className="oc dark"><Explain id="overview.screened" label="Explain" /><div className="chip" style={{ background: 'transparent', color: '#fff', borderColor: '#fff' }}>Screened</div><div className="num">{n.toLocaleString()}</div></div>
        {outcome.map(o => (
          <div key={o.k} className="oc">
            <Explain id={o.explain} label="Explain" />
            <div className="chip" style={{ background: o.bg, color: o.color }}>{o.label}</div>
            <div className="num" style={{ color: o.color }}>{o.v.toLocaleString()}</div>
            <div className="bar" role="img" aria-label={`${o.v} of ${n} batteries`}><i style={{ width: `${(o.v / n) * 100}%`, background: o.color }} /></div>
            {o.k === 'reuse' && R.usage && <div className="small muted" style={{ marginTop: 8 }}>Usage baseline: {(reuseStates.Safe || 0).toLocaleString()} safe · {(reuseStates['Approaching limit'] || 0).toLocaleString()} approaching</div>}
          </div>
        ))}
        <div className="oc"><Explain id="overview.forbidden" label="Explain" /><div className="chip">Forbidden</div><div className="num">{R.fleet_plan.forbidden_assignments}</div>
          <div className="small muted" style={{ marginTop: 10 }}>{R.fleet_plan.packs.toLocaleString()} packs verified</div></div>
      </div>

      <SecTitle icon="ml">Two models, side by side</SecTitle>
      <div className="grid g4" style={{ marginBottom: 22 }}>
        <Stat explain="overview.xgb" label="XGBoost · classical" value={pc(C.xgb.accuracy)} note={`accurate on ${R.data.cells} cells it never saw`} />
        <Stat explain="overview.aqsvc" label="AQSVC · quantum" value={pc(C.aqsvc.accuracy)} note={`${R.aqsvc.members} QUBO-trained SVMs on QpiAI`} />
        <Stat explain="overview.agree" label="They agree" value={pc(sbs.agree_rate)} note={`and are right ${pc(sbs.accuracy_when_agree)} of the time when they do`} />
        <Stat explain="overview.disagree" label="They disagree" value={sbs.disagreements.toLocaleString()} note="snapshots: these go to a lab test" />
      </div>

      <section className="arch" id="arch" ref={archRef} aria-labelledby="arch-title">
        <div className="arch-head">
          <SecTitle icon="opt" id="arch-title">How CELLFEE works</SecTitle>
          <Explain id="overview.pipeline" />
        </div>
        <p className="sub" style={{ margin: '0 0 14px' }}>From raw battery data to a decision for every cell. Select a stage for its technical detail.</p>
        <div className="arch-legend">
          <span><span className="st-tech" style={{ background: 'var(--peach)' }}>Classical</span> data handling and baseline ML</span>
          <span><span className="st-tech" style={{ background: '#7b8cff' }}>QpiAI QCloud</span> quantum circuits</span>
          <span><span className="st-tech" style={{ background: 'var(--mint)' }}>QpiAI Opt</span> optimisation</span>
        </div>
        <ol className="arch-rows">
          <Stage i={0} next n={1} icon="data" tech="classical" explain="arch.1" title="Battery Dataset" status={ok}
            sub={`Real lab data (MIT, Stanford & Toyota): ${R.data.cells} cells, ${R.data.cycle_records.toLocaleString()} cycles, ${R.data.snapshots.toLocaleString()} screening snapshots.`} />
          <Stage i={1} next n={2} icon="prep" tech="classical" explain="arch.2" title="Data Preparation" status={ok}
            sub={`Validate every cycle, turn each battery's recent history into ${R.qml.n_qubits} screening features, scale with training cells only.`} />
          <Stage i={2} n={3} icon="ml" tech="classical" explain="arch.3" title="Classical model: XGBoost" status={ok}
            sub={`Gradient-boosted trees on every snapshot; ${pc(C.xgb.accuracy)} accurate on unseen cells. Runs on every battery.`} />
          <li className="arch-turn" aria-hidden="true">
            <svg viewBox="0 0 100 24" preserveAspectRatio="none"><path d="M84 0 V10 H16 V22" /></svg>
            <i />
          </li>
          <Stage i={3} next n={4} icon="quantum" tech="qcloud" explain="arch.4" title="Quantum model: AQSVC" status={{ kind: 'ok', label: 'Simulator' }}
            sub={`${R.aqsvc.maps ? R.aqsvc.maps.map(m => m.inputs).join(" + ") : R.qml.n_qubits}-qubit QpiAI kernels + ${R.aqsvc.members} SVMs trained as ${R.aqsvc.qubo_vars}-variable QUBOs on QpiAI Opt; ${pc(C.aqsvc.accuracy)} accurate. Runs beside XGBoost.`} />
          <Stage i={4} next n={5} icon="opt" tech="opt" explain="arch.5" title="Allocation Optimization" status={ok}
            sub={`${R.fleet_plan.batches} truckload batches, each a QpiAI Opt model (${plan.qubo.variables}-variable QUBO): reuse, test or recycle, and compatible 4-cell packs.`} />
          <Stage i={5} n={6} icon="decision" tech="classical" explain="arch.6" title="Battery Decisions" status={ok}
            sub={`Reuse ${(counts.reuse || 0).toLocaleString()} in ${R.fleet_plan.packs.toLocaleString()} packs, test ${(counts.test || 0).toLocaleString()}, recycle ${(counts.recycle || 0).toLocaleString()}, each with both models' answers and the reasons.`} />
        </ol>
      </section>
      <p className="muted small">Preliminary decision support, not safety certification. Quantum circuits ran on QpiAI's local simulator; no hardware run is claimed.</p>
    </>
  )
}

/* ------------------------------------------------------------------ Fleet */
const ACTION_ORDER = ['reuse', 'test', 'recycle']

function StatusDot({ a }) { return <i className="dot" style={{ background: ACTION_COLOR[a] }} aria-hidden="true" /> }

/** One short, data-backed line per battery for the compact list. */
function summaryOf(x) {
  if (x.action === 'reuse') return `${x.pack} · grade ${x.grade}`
  if (x.action === 'test') return x.agree ? 'Models unsure: full test first' : 'Models disagree: full test first'
  return x.reuse_blocked ? 'Little useful life left' : 'Lower value than reuse or test'
}

/** Search, decision filter and sort shared by Fleet and Passports (state lives in the page, so closing a report keeps it). */
const PAGE_SIZE = 50

function useListControls(R) {
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [grade, setGrade] = useState('all')
  const [sort, setSort] = useState('id')
  const [page, setPage] = useState(0)
  const all = useMemo(() => {
    const s = q.trim().toLowerCase()
    const rows = R.fleet.filter(x => (filter === 'all' || x.action === filter) && (grade === 'all' || x.grade === grade)
      && (!s || x.id.toLowerCase().includes(s) || x.source_cell.toLowerCase().includes(s) || (x.pack || '').toLowerCase().includes(s)))
    const by = { id: (a, b) => a.id.localeCompare(b.id), high: (a, b) => b.soh - a.soh, low: (a, b) => a.soh - b.soh,
      disagree: (a, b) => (a.agree - b.agree) || a.id.localeCompare(b.id) }[sort]
    return rows.sort(by)
  }, [R, q, filter, grade, sort])
  useEffect(() => setPage(0), [q, filter, grade, sort])
  const pages = Math.max(1, Math.ceil(all.length / PAGE_SIZE))
  const list = all.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const counts = R.fleet.reduce((a, b) => ({ ...a, [b.action]: (a[b.action] || 0) + 1 }), {})
  const bar = (
    <div className="toolbar">
      <input className="search" type="search" placeholder="Search ID, cell or pack" value={q} onChange={e => setQ(e.target.value)} aria-label="Search batteries" />
      <div className="toggle" role="group" aria-label="Filter by decision">
        {['all', ...ACTION_ORDER].map(k => <button key={k} aria-pressed={filter === k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>
          {k === 'all' ? `All ${R.fleet.length.toLocaleString()}` : `${ACTION_LABEL[k]} ${(counts[k] || 0).toLocaleString()}`}</button>)}
      </div>
      <select className="btn" value={grade} onChange={e => setGrade(e.target.value)} aria-label="Grade">
        <option value="all">Grade: all</option>{['A', 'B', 'T', 'C'].map(g => <option key={g} value={g}>Grade {g}</option>)}
      </select>
      <select className="btn" value={sort} onChange={e => setSort(e.target.value)} aria-label="Sort">
        <option value="id">Sort: ID</option><option value="high">Sort: health high → low</option><option value="low">Sort: health low → high</option>
        <option value="disagree">Sort: models disagree first</option>
      </select>
    </div>
  )
  const pager = (
    <div className="pager" role="navigation" aria-label="Pages">
      <span className="small muted">{all.length ? `${(page * PAGE_SIZE + 1).toLocaleString()}–${Math.min(all.length, (page + 1) * PAGE_SIZE).toLocaleString()} of ${all.length.toLocaleString()}` : 'none'}</span>
      <button className="btn small-btn" disabled={page === 0} onClick={() => setPage(0)}>« First</button>
      <button className="btn small-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>‹ Prev</button>
      <span className="mono small">Page {page + 1} / {pages}</span>
      <button className="btn small-btn" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next ›</button>
      <button className="btn small-btn" disabled={page >= pages - 1} onClick={() => setPage(pages - 1)}>Last »</button>
    </div>
  )
  return { list, bar, pager }
}

function FleetDownloads({ R }) {
  return (
    <div className="dl-row"><span className="lbl">Fleet summary</span>
      <button className="btn small-btn" onClick={() => downloadFleetPDF(fleetPlain(R))}>Download PDF</button>
      <button className="btn small-btn" onClick={() => downloadJSON(fleetPlain(R), `cellfee-fleet-summary.json`)}>Download JSON</button>
    </div>
  )
}

function Fleet({ R }) {
  const [sel, setSel] = useState(null)
  const { list, bar, pager } = useListControls(R)
  return (
    <>
      <Head motif="passport" R={R} explain="page.fleet" title="Fleet & battery passports">{R.fleet.length.toLocaleString()} used batteries in {R.fleet_plan.batches} truckload batches: grade, both models' answers side by side, the decision and its pack. Open any battery's passport for the complete report, and download it as PDF or JSON.</Head>
      {bar}
      <FleetDownloads R={R} />
      <div className="table-wrap table-card">
        <table className="fleet-table">
          <thead><tr><th>Battery</th><th>Grade</th><th className="num">Health</th><th className="num" title="Classical model: chance of a long life ahead">XGBoost</th><th className="num" title="Quantum model: chance of a long life ahead">AQSVC</th><th>Status</th><th className="col-sum">Summary</th><th aria-label="Action" /></tr></thead>
          <tbody>
            {list.map(x => (
              <tr key={x.id} tabIndex={0} onClick={() => setSel(x.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(x.id) } }}
                aria-label={`${x.id}, health ${Math.round(x.soh * 100)} percent, XGBoost ${Math.round(x.p_xgb * 100)}, AQSVC ${Math.round(x.p_aqsvc * 100)}, ${ACTION_LABEL[x.action]}. Open details`}>
                <td className="f-id">{x.id}</td>
                <td><GradeBadge g={x.grade} /></td>
                <td className="num f-soh">{Math.round(x.soh * 100)}<small>%</small></td>
                <td className="num"><ModelCell p={x.p_xgb} /></td>
                <td className="num"><ModelCell p={x.p_aqsvc} /></td>
                <td><span className={`tag t-${x.action}`}>{ACTION_LABEL[x.action]}</span></td>
                <td className="f-sum col-sum">{summaryOf(x)} · batch {x.batch}</td>
                <td className="f-go"><button className="btn small-btn" onClick={e => { e.stopPropagation(); setSel(x.id) }}>View passport</button></td>
              </tr>
            ))}
            {list.length === 0 && <tr><td colSpan={8} className="empty">No batteries match this search.</td></tr>}
          </tbody>
        </table>
      </div>
      {pager}
      {sel && <Passport id={sel} R={R} close={() => setSel(null)} />}
    </>
  )
}

/* ------------------------------------------------------------------ Passport report (drawer) */
/** Fetches one battery's full passport (the fleet list only carries the summary). */
function Passport({ id, R, close }) {
  const [b, setB] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { setB(null); setErr(null); api(`/api/fleet/${id}`).then(setB).catch(e => setErr(String(e))) }, [id])
  const ref = useRef(null)
  const closeRef = useRef(close)
  closeRef.current = close
  useEffect(() => {   // focus the report once on open; Escape closes it
    ref.current?.focus()
    const onKey = e => { if (e.key === 'Escape') closeRef.current() }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={`Battery passport ${id}`} tabIndex={-1} ref={ref}>
      {!b && <div className="row spread"><h3 style={{ margin: 0 }}>Passport · {id}</h3><button className="btn" onClick={close}>Close</button></div>}
      {!b && !err && <p className="muted">Loading the passport…</p>}
      {err && <div className="callout warn">{err}</div>}
      {b && <PassportBody b={b} R={R} close={close} />}
    </div>
  )
}

function PassportBody({ b, R, close }) {
  const U = b.utilities
  const packMates = b.pack ? (R.packs[b.pack] || []).filter(id => id !== b.id) : []
  const tagFor = k => b.measured.includes(k) ? 'measured' : 'from history'
  const plain = useMemo(() => passportPlain(b, R), [b, R])
  return (
    <>
      <div className="row spread"><h3 style={{ margin: 0 }}>Passport · {b.id}</h3><div className="row"><Explain id="passport" /><button className="btn" onClick={close}>Close</button></div></div>
      <div className="dl-row"><span className="lbl">Report</span>
        <button className="btn small-btn primary" onClick={() => downloadPassportPDF(plain)}>Download PDF</button>
        <button className="btn small-btn" onClick={() => downloadJSON(plain, `cellfee-passport-${b.id}.json`)}>Download JSON</button>
      </div>
      <div className="plain"><b className="small">IN PLAIN WORDS</b><p>{plain.decision.in_plain_words}</p><p>{plain.health.in_plain_words}</p></div>
      <div className="row" style={{ margin: '10px 0 12px' }}><GradeBadge g={b.grade} /><ActionTag a={b.action} />{b.pack && <span className="tag">{b.pack}</span>}</div>
      <div className="callout small">{b.explanation}</div>

      <h4>Two models, side by side</h4>
      <p className="small muted" style={{ margin: '0 0 8px' }}>Question to both: will it last at least {R.assumptions.LONG_LIFE_CYCLES} more cycles before it falls to 80% capacity?</p>
      <div className="duo">
        <div className="duo-m"><span className="lbl">XGBoost · classical</span><ModelCell p={b.p_xgb} /></div>
        <div className="duo-m q"><span className="lbl">AQSVC · quantum</span><ModelCell p={b.p_aqsvc} /><span className="small muted">stacked over {R.aqsvc.members} quantum SVMs</span></div>
      </div>
      <div className="kv">
        <div>Health now (measured)</div><div className="mono">{pc(b.soh)}</div>
        <div>Models agree</div><div className="mono">{b.agree ? 'yes' : 'no — a lab test decides'}</div>
        <div>Grade rule</div><div className="small">{b.reason}</div>
      </div>

      <h4>Allocation &amp; constraints</h4>
      <div className="kv">
        <div>Batch (truckload)</div><div className="mono">{b.batch} of {R.fleet_plan.batches} · {b.batch_size} batteries</div>
        <div>Chance of a long life (both models)</div><div className="mono">{f2(U.p_ok)}</div>
        <div>Expected value: reuse · test · recycle</div><div className="mono">{money(U.reuse)} · {money(U.test)} · {money(U.recycle)}</div>
        <div>Reuse blocked by hard rule</div><div className="mono">{b.reuse_blocked ? 'yes' : 'no'}</div>
        <div>Incompatible batteries in its batch (never same pack)</div><div className="mono">{b.incompatible} of {b.batch_size - 1}</div>
        {packMates.length > 0 && <><div>Pack-mates in {b.pack}</div><div className="mono">{packMates.join(', ')}</div></>}
      </div>

      <h4>Quantum features</h4>
      <div className="kv">
        <div>Encoded rotation angles ({b.angles.length} qubits)</div><div className="mono">{b.angles.map(a => a.toFixed(2)).join(' ')}</div>
      </div>
      <p className="small muted" style={{ margin: '8px 0 4px' }}>Most similar batteries in its batch, by quantum kernel</p>
      {b.similar.map(s => <div key={s.id} className="row spread small"><span className="mono">{s.id} <StatusDot a={s.action} /></span><span className="mono">k = {f3(s.k)}</span></div>)}

      <h4>Inputs</h4>
      <div className="kv">
        {R.data.features.map(f => <Fragment key={f.key}><div>{f.label} <span className="tag">{tagFor(f.key)}</span></div><div className="mono">{f3(b.features[f.key])}</div></Fragment>)}
      </div>

      <h4>Usage baseline</h4>
      <UsageBaseline u={b.usage} R={R} />

      <h4>Applications &amp; confidence</h4>
      <AppConfidence apps={b.usage.applications} R={R} />

      <h4>History</h4>
      <History b={b} R={R} />

      <h4>Provenance &amp; validation</h4>
      <div className="kv">
        <div>Source</div><div className="mono">MIT–Stanford–Toyota cell {b.source_cell} · cycle {b.cycle}</div>
        <div>Fast-charge protocol it lived with</div><div className="mono">{b.policy}</div>
        <div>What really happened (held out, never used to decide)</div><div className="mono">{b.truth.cycles_left} cycles left → {b.truth.fit ? 'fit' : 'not fit'} for second life</div>
        <div>Rules version · run</div><div className="mono">v{R.rules_version} · {R.generated}</div>
      </div>
      <div className="callout warn small" style={{ marginTop: 14 }}>Preliminary decision support only, not a safety certification. Real reuse needs qualified inspection, BMS compatibility and integration checks.</div>
    </>
  )
}

/** The passport's history as a vertical timeline (every step is stored data). */
function History({ b, R }) {
  const best = b.usage.applications.find(a => a.id === b.usage.best)
  const steps = [
    ['Source', `MIT–Stanford–Toyota cell ${b.source_cell}, recorded to cycle ${b.cycle} (${b.policy}).`],
    ['Measurements', `Health ${pc(b.soh)}, resistance ${b.features.ir_mohm.toFixed(1)} mΩ, peak ${b.features.temp_max_c.toFixed(0)} °C, ${b.features.charge_time_min.toFixed(1)} min charge.`],
    ['Both models', `XGBoost ${pc(b.p_xgb)} · AQSVC ${pc(b.p_aqsvc)} chance of ${R.assumptions.LONG_LIFE_CYCLES}+ cycles left${b.agree ? '' : ' (they disagree)'}.`],
    ['Decision', `Grade ${b.grade} → ${ACTION_LABEL[b.action]} (truckload ${b.batch}, QpiAI Opt exact MILP).`],
    ['New pack', b.pack ? `${b.pack} with ${(R.packs[b.pack] || []).filter(i => i !== b.id).join(', ')}.` : 'Not packed.'],
    ['Usage baseline', `${b.usage.state} · risk ${b.usage.risk.level}${best ? ` · stop by ${best.stop.p10.toLocaleString()} cycles (${best.name})` : ' · do not reuse'}.`],
    ['Application confidence', best ? `${best.name}: ${confText(best.confidence)}.` : 'No second-life application.'],
    ['Run IDs', [R.aqsvc.cv_evidence_id, R.fleet_plan.evidence_ids?.both, R.usage?.evidence_id].filter(Boolean).join(' · ')],
  ]
  return (
    <ol className="timeline" data-anim="timeline">
      {steps.map(([h, t]) => <li key={h} data-anim="step"><b>{h}</b><span className="small">{t}</span></li>)}
    </ol>
  )
}

/* ------------------------------------------------------------------ QML */
function QML({ R }) {
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [device, setDevice] = useState('QpiAI-QSV-Local')
  const q = R.qml
  const A = R.aqsvc
  const fold0 = q.folds[0]
  const doRun = () => { setBusy(true); api('/api/kernel/run', { pairs: 6, device, shots: 2000 }).then(setRun).catch(e => setRun({ error: String(e) })).finally(() => setBusy(false)) }
  return (
    <>
      <Head motif="circuit" R={R} explain="page.qml" title="AQSVC: quantum ML on QpiAI QCloud + QpiAI Opt">
        An annealing-based quantum support vector classifier. The kernel comes from a QpiAI circuit ({q.circuit_text}); each SVM is
        trained by solving a QUBO on QpiAI Opt's annealer, and {A.members} of them are combined by bagging, boosting, two tuned feature maps and stacking. Circuits run on <code>QpiAI-QSV-Local</code>; with a
        QCloud subscription the same compute-uncompute circuits run on QpiAI cloud simulators or the QpiAI-Indus-1 QPU.
      </Head>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card"><Explain id="qml.circuit" />
          <h3>Feature map U(x; θ) — one layer</h3>
          <p className="sub">Each battery feature is one qubit. Similarity map (used to build packs), learned scales s = [{q.feature_map.scales.join(', ')}], entangling g = {q.feature_map.entangle}</p>
          <CircuitDiagram n={q.n_qubits} labels={R.data.features.map(f => f.key)} />
        </div>
        <div className="card"><Explain id="qml.training" />
          <h3>QML training: kernel-target alignment</h3>
          <p className="sub">The circuit learns to place batteries with a similar life ahead close together (fold 1 shown).</p>
          <LineChart values={fold0.alignment_history} yLabel="alignment" xLabel="optimiser evaluation" color="var(--series-1)" />
          <table className="small"><thead><tr><th>Fold</th><th className="num">Untrained</th><th className="num">Trained</th></tr></thead>
            <tbody>{q.folds.map(f => <tr key={f.fold}><td>{f.fold}</td><td className="num">{f3(f.alignment_untrained)}</td><td className="num">{f3(f.alignment_trained)}</td></tr>)}</tbody></table>
        </div>
      </div>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card"><Explain id="qml.kernel" />
          <h3>Quantum kernel across batch 1</h3>
          <p className="sub">k(i,j) from QpiAI SDK statevectors — this matrix becomes the optimiser's compatibility cost.</p>
          <Heatmap matrix={q.fleet_kernel} labels={q.kernel_ids} title="quantum similarity" />
        </div>
        <div className="card"><Explain id="qml.aqsvc" />
          <h3>Training the SVMs as QUBOs on QpiAI Opt</h3>
          <p className="sub">Each member learns from {A.subset} batteries; its weights α are written in {A.bits} binary bits each, so training is one {A.qubo_vars}-variable QUBO.</p>
          <pre className="mono small" style={{ whiteSpace: 'pre-wrap', margin: '0 0 10px' }}>{A.formulation}</pre>
          <div className="kv">
            <div>Solver</div><div className="mono">{A.solver.join(', ')}</div>
            <div>QUBOs solved this run</div><div className="mono">{A.qubos_solved} ({A.reads} reads × {A.sweeps} sweeps each)</div>
            <div>Support vectors per SVM (mean)</div><div className="mono">{f2(A.mean_support_vectors)}</div>
            <div>Time per QUBO (mean)</div><div className="mono">{f2(A.mean_seconds_per_qubo)} s</div>
            <div>Deployed model</div><div className="mono">{A.members} SVMs · {A.deployed_support_vectors} support-vector circuits on QpiAI SDK</div>
            <div>SDK vs twin (max kernel diff)</div><div className="mono">{A.sdk_vs_twin_max_overlap_diff.toExponential(1)}</div>
          </div>
          <p className="small muted">Run records: evidence {A.cv_evidence_id} (cross-validation) and {A.final_evidence_id} (deployed model).</p>
        </div>
      </div>
      {A.maps && <AqsvcEnsemble R={R} />}
      <div className="card"><Explain id="qml.fidelity" />
        <div className="row spread"><div><h3>Shot-based fidelity test (hardware-ready path)</h3>
          <p className="sub">Circuit U(xᵢ)·U(xⱼ)† measured {q.fidelity_test.shots} shots on {q.fidelity_test.device}; k = P(0…0). {q.fidelity_test.pairs.length} pairs, mean |shots − exact| = {f3(q.fidelity_test.mean_abs_error)}.</p></div>
          <div className="row">
            <select value={device} onChange={e => setDevice(e.target.value)} className="btn">
              {['QpiAI-QSV-Local', 'QpiAI-QSV-Simulator', 'QpiAI-QDM-Simulator', 'QpiAI-QSV-Lite', 'QpiAI-Indus-1'].map(d => <option key={d}>{d}</option>)}
            </select>
            <button className="btn primary" disabled={busy} onClick={doRun}>{busy ? 'Running circuits…' : 'Run 6 new kernel circuits'}</button>
          </div></div>
        {run && (run.error ? <div className="callout warn">{run.error}</div> : (
          <table className="small"><thead><tr><th>Pair</th><th className="num">Shots estimate</th><th className="num">Exact</th></tr></thead>
            <tbody>{run.pairs.map((p, i) => <tr key={i}><td className="mono">{p[0]} × {p[1]}</td><td className="num">{f3(run.values[i])}</td><td className="num">{f3(run.exact[i])}</td></tr>)}</tbody>
            <caption className="muted small" style={{ captionSide: 'bottom', textAlign: 'left' }}>Device {run.device} · evidence {run.run_id}{run.job_ids.length ? ` · job IDs ${run.job_ids.join(', ')}` : ''}</caption></table>
        ))}
        <ShotHistogram ft={q.fidelity_test} />
        {(q.fidelity_test.notes || []).map((n, i) => <div key={i} className="callout warn small">{n}</div>)}
        {run?.notes?.map((n, i) => <div key={`r${i}`} className="callout warn small" style={{ marginTop: 8 }}>{n}</div>)}
        {!R.sponsor_status.qcloud_key_configured && <p className="small muted">No QCloud key configured: cloud devices fall back to QpiAI-QSV-Local. Add QPIAI_QCLOUD_API_KEY to .env to use QpiAI cloud simulators / Indus-1.</p>}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ Compare */
function Compare({ R }) {
  const keys = ['rule', 'xgb_small', 'svc_rbf', 'qsvc', 'xgb', 'aqsvc', 'both']
  const C = R.comparison, sbs = R.side_by_side
  const best = (k, lowGood = true) => keys.reduce((a, b) => (C[b][k] == null ? a : a == null || (lowGood ? C[b][k] < C[a][k] : C[b][k] > C[a][k]) ? b : a), null)
  const cols = [
    ['accuracy', 'Accuracy', false, pc], ['balanced_accuracy', 'Balanced acc.', false, pc], ['auc', 'ROC-AUC', false, f3],
    ['false_fit_rate', 'False "fit"', true, pc], ['brier', 'Brier', true, f3], ['seconds', 'Train time (s)', true, v => (v == null ? '—' : Math.round(v))],
    ['realized_value', 'Realised value', false, money], ['unfit_reused', 'Unfit reused', true, v => v],
    ['good_cells_recycled', 'Good cells recycled', true, v => v],
  ]
  return (
    <>
      <Head motif="bars" R={R} explain="page.compare" title="XGBoost vs AQSVC, side by side">
        Both production models answer the same question for every battery — will it last at least {R.assumptions.LONG_LIFE_CYCLES} more cycles? —
        checked on cells they never saw ({R.data.snapshots.toLocaleString()} snapshots, {R.data.cells} cells, 5 folds). Baselines show what each ingredient adds;
        each model's answers then drive the same QpiAI Opt plan, scored against what really happened.
      </Head>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat explain="compare.agree" label="Models agree" value={pc(sbs.agree_rate)} note={`on ${R.data.snapshots.toLocaleString()} snapshots`} />
        <Stat explain="compare.agree" label="Right when they agree" value={pc(sbs.accuracy_when_agree)} note={`XGBoost alone: ${pc(C.xgb.accuracy)}`} />
        <Stat explain="compare.agree" label="Disagreements" value={sbs.disagreements.toLocaleString()} note="sent to a lab test instead of guessing" />
        <Stat explain="compare.agree" label="When they disagree" value={`XGB ${pc(sbs.accuracy_xgb_when_disagree)}`} note={`AQSVC right ${pc(sbs.accuracy_aqsvc_when_disagree)} of those`} />
      </div>
      <div className="card table-wrap" style={{ marginBottom: 16 }}><Explain id="compare.table" />
        <table>
          <thead><tr><th>Model</th>{cols.map(c => <th key={c[0]} className="num">{c[1]}</th>)}</tr></thead>
          <tbody>{keys.map(k => (
            <tr key={k} className={['xgb', 'aqsvc', 'both'].includes(k) ? 'row-main' : ''}><td><b>{C[k].label}</b></td>
              {cols.map(([c, , low, fmt]) => <td key={c} className={`num ${best(c, low) === k ? 'best' : ''}`}>{fmt(C[k][c])}</td>)}</tr>
          ))}</tbody>
        </table>
        <p className="muted small">Bold = best in column. Accuracy columns: grouped cross-validation by cell. Value columns: the QpiAI Opt plan built from each model's answers on the same first {R.fleet_plan.comparison_batches} truckloads ({R.fleet_plan.comparison_batteries.toLocaleString()} batteries); CELLFEE's own plan covers all {R.fleet.length.toLocaleString()}.
          AQSVC and the B1/B2/C1 baselines see the same {R.aqsvc.members} × {R.aqsvc.subset} training batteries per fold; XGBoost sees every training snapshot.</p>
      </div>
      <div className="grid g2">
        <div className="card"><Explain id="compare.value" /><h3>Accuracy on unseen cells</h3><p className="sub">Share of snapshots answered correctly</p>
          <BarList rows={keys.map(k => ({ key: k, label: C[k].label, value: C[k].accuracy }))} format={v => `${(v * 100).toFixed(1)}%`} highlight={keys.reduce((a, k) => (C[k].accuracy > C[a].accuracy ? k : a))} /></div>
        <div className="card"><Explain id="compare.value" /><h3>Realised value of each plan</h3><p className="sub">₹ after test costs and rework for batteries that did not last</p>
          <BarList rows={keys.map(k => ({ key: k, label: C[k].label, value: C[k].realized_value }))} format={inr} highlight={keys.reduce((a, k) => (C[k].realized_value > C[a].realized_value ? k : a))} /></div>
      </div>
      <div className="callout" style={{ marginTop: 16 }}>
        Honest reading: XGBoost is the stronger single model here, and we claim no quantum advantage. AQSVC is a working quantum classifier trained
        end to end on QpiAI tools, and its value in CELLFEE is as an independent second opinion: when the two agree they are more often right than either alone,
        and when they disagree the battery goes to a lab test. Circuits ran on QpiAI's local simulator, which is classical simulation, not a hardware speed-up.
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ Opt */
function Opt({ R }) {
  const p = R.plan, qa = R.qaoa, run0 = qa.runs[0]
  return (
    <>
      <Head motif="packs" R={R} explain="page.opt" title="Decisions with QpiAI Opt">
        Batteries arrive in truckloads of about {R.fleet_plan.batch_size}. Each batch is written with the QpiAI Opt modeller (binary variables, constraints, objective) and compiled to a QUBO by QpiAI Opt;
        all {R.fleet_plan.batches} batches together decide the {R.fleet_plan.batteries.toLocaleString()}-battery fleet.
        The decision comes from QpiAI Opt's local exact MILP solver (proven optimum, cross-checked against HiGHS); the QUBO is also run on
        QpiAI Opt's local annealer and reported as-is.
      </Head>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat explain="opt.fleet" label="Batches solved" value={R.fleet_plan.batches} note={`${R.fleet_plan.batteries.toLocaleString()} batteries, ~${R.fleet_plan.batch_size} per truckload`} />
        <Stat explain="opt.fleet" label="QpiAI Opt exact solves" value={R.fleet_plan.opt_milp_batches} note={`${R.fleet_plan.opt_matches_highs} of ${R.fleet_plan.highs_checked_batches} re-solved by HiGHS match exactly`} />
        <Stat explain="opt.fleet" label="Packs built" value={R.fleet_plan.packs.toLocaleString()} note={`${R.fleet_plan.forbidden_assignments} forbidden assignments`} />
        <Stat explain="opt.fleet" label="Expected value (fleet)" value={money(R.fleet_plan.objective)} note={R.fleet_plan.all_feasible ? 'every batch passes the constraint check' : 'a batch FAILED the check'} />
      </div>
      <h3 style={{ margin: '0 0 10px' }}>Batch 1 in detail</h3>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat explain="opt.qubo" label="QUBO variables" value={p.qubo.variables} note={`${p.qubo.terms} terms, compiled by QpiAI Opt`} />
        <Stat explain="opt.forbidden" label="Forbidden pairs (learned)" value={p.forbidden_pairs} note="from quantum similarity + health gap" />
        <Stat explain="opt.check" label="Constraint check" value={p.constraint_check.feasible ? 'Pass' : 'Fail'} note={`${p.constraint_check.violations.length} violations`} />
        <Stat explain="opt.objective" label="Objective (expected ₹)" value={money(p.objective)} note={`solved by ${p.solved_by}`} />
      </div>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card"><Explain id="opt.model" /><h3>Model</h3>
          <pre className="mono small" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{`variables  r_b, t_b, c_b ∈ {0,1}   reuse / test / recycle
           y_bp ∈ {0,1}            battery b in pack p
           u_p  ∈ {0,1}            pack p is built
s.t.       r_b + t_b + c_b = 1
           Σ_p y_bp = r_b
           Σ_b y_bp = ${R.assumptions.PACK_SIZE}·u_p
           y_bp + y_cp ≤ 1         for forbidden (b,c)
           Σ_b t_b ≤ ${p.test_capacity}              test-bench capacity
max  Σ_b [U_reuse·r_b + U_test·t_b + U_recycle·c_b]
     − λ Σ_p Σ_{b<c} d_bc · y_bp · y_cp
U from measured health & P(fit) of XGBoost + AQSVC; d_bc = ½(1 − k_bc) + ½·min(1, |Δhealth|/0.05)`}</pre>
        </div>
        <div className="card"><Explain id="opt.solvers" /><h3>Solver runs</h3>
          <table className="small"><thead><tr><th>Solver</th><th className="num">Objective</th><th>Status</th><th className="num">s</th></tr></thead>
            <tbody>{p.solver_runs.map((s, i) => <tr key={i}><td>{s.solver}</td><td className="num">{s.objective != null ? money(s.objective) : '—'}</td>
              <td>{s.error ? <span className="muted">{s.error.slice(0, 80)}</span> : s.optimal ? (s.matches_highs ? 'optimal ✓ matches HiGHS' : 'optimal') : s.feasible ? 'feasible' : 'violates constraints'}</td><td className="num">{s.seconds ?? '—'}</td></tr>)}</tbody></table>
          <h3 style={{ marginTop: 14 }}>Packs</h3>
          {Object.entries(R.packs).filter(([, cells]) => p.ids.includes(cells[0])).map(([name, cells]) => {
            const bs = cells.map(id => R.fleet.find(b => b.id === id))
            return <div key={name} className="row small" style={{ marginBottom: 6 }}><b style={{ width: 64 }}>{name}</b>
              {bs.map(b => <span key={b.id} className="tag">{b.id} · {pc(b.soh)}</span>)}</div>
          })}
          {!p.packs.length && <p className="muted small">No pack could be filled with compatible reuse-grade batteries in this batch.</p>}
        </div>
      </div>
      <div className="card" style={{ marginBottom: 16 }}><Explain id="opt.graph" />
        <h3>How batch 1 was decided</h3>
        <p className="sub">Each dot is a battery. Lines join pairs that may share a pack; red pairs are forbidden (low quantum similarity or health gap). QpiAI Opt's exact plan then groups them into packs, test and recycle.</p>
        <OptGraph R={R} />
      </div>
      <PackBaselines R={R} p={p} />
      <div className="card"><Explain id="opt.qaoa" />
        <h3>QAOA pack balancing ({qa.n_qubits} qubits, QpiAI QCloud circuits)</h3>
        <p className="sub">Split {qa.cell_ids.join(', ')} into two packs of {qa.n_qubits / 2} with minimum in-pack mismatch. XY mixer keeps every sample a valid split.</p>
        <div className="grid g3">
          <div className="kv">
            <div>Exact optimum (brute force)</div><div className="mono">{f3(qa.exact.objective)}</div>
            <div>QAOA best sampled</div><div className="mono">{f3(run0.best_objective)}</div>
            <div>Approximation ratio</div><div className="mono">{run0.approximation_ratio ? `${(run0.approximation_ratio * 100).toFixed(1)}%` : '—'}</div>
            <div>P(optimal) QAOA</div><div className="mono">{f3(run0.optimal_probability)}</div>
            <div>P(optimal) random split</div><div className="mono">{f3(run0.random_guess_optimal_probability)}</div>
            <div>Mean mismatch: QAOA / random</div><div className="mono">{f3(run0.mean_sampled_objective)} / {f3(run0.mean_random_objective)}</div>
            <div>Valid samples</div><div className="mono">{(run0.feasible_fraction * 100).toFixed(0)}%</div>
            <div>Sample device · shots</div><div className="mono">{run0.sample_device} · {run0.shots}</div>
          </div>
          {run0.device_note && <div className="callout warn small" style={{ gridColumn: '1 / -1' }}>{run0.device_note}</div>}
          <div><b className="small">Optimiser trace (CVaR energy)</b><LineChart values={run0.energy_history} yLabel="CVaR energy" xLabel="circuit evaluation" /></div>
          <div className="small">
            <b>Exact split</b>{qa.packs_exact.map((pk, i) => <div key={i}>Pack {i + 1}: {pk.join(', ')}</div>)}
            <b style={{ display: 'block', marginTop: 8 }}>QAOA split</b>{qa.packs_qaoa ? qa.packs_qaoa.map((pk, i) => <div key={i}>Pack {i + 1}: {pk.join(', ')}</div>) : '—'}
            {qa.runs.slice(1).map((r, i) => <div key={i} className="muted" style={{ marginTop: 8 }}>{r.solver}: {r.error ? r.error.slice(0, 120) : `objective ${f3(r.objective)}`}</div>)}
          </div>
        </div>
      </div>
    </>
  )
}

/** Per-pack usage baseline after the optimisation: batch 1's packs, plus a lookup for any of the fleet's packs. */
function PackBaselines({ R, p }) {
  const names = Object.keys(R.packs_detail || {})
  const own = names.filter(n => R.packs_detail[n].batch === 1)
  const [pick, setPick] = useState(own[0] || names[0])
  if (!names.length) return null
  return (
    <div className="card" style={{ marginBottom: 16 }} data-anim="packs"><Explain id="usage.pack" />
      <h3>Usage baseline per pack</h3>
      <p className="sub">After the optimisation, each pack's weakest member sets its stop period and application confidence. {R.usage.label}</p>
      <div className="grid g3" style={{ marginBottom: 12 }}>
        {own.map(n => <PackUsage key={n} name={n} pd={R.packs_detail[n]} R={R} />)}
      </div>
      <label className="small">Look up any of the {names.length.toLocaleString()} packs{' '}
        <select className="btn" value={pick} onChange={e => setPick(e.target.value)}>{names.map(n => <option key={n}>{n}</option>)}</select></label>
      {pick && !own.includes(pick) && <div style={{ marginTop: 12, maxWidth: 520 }}><PackUsage name={pick} pd={R.packs_detail[pick]} R={R} /></div>}
    </div>
  )
}

/* ------------------------------------------------------------------ Assess */
/** Both models' answers for one screened battery, next to each other. */
function Duo({ res, members }) {
  const x = res.models.xgb, q = res.models.aqsvc
  return (
    <div className="duo">
      <div className="duo-m"><span className="lbl">XGBoost · classical</span><ModelCell p={x.p_fit} /><span className="small muted">{x.ms} ms</span></div>
      <div className="duo-m q"><span className="lbl">AQSVC · quantum</span><ModelCell p={q.p_fit} /><span className="small muted">{q.votes_fit} of {q.members ?? members} SVMs say yes · {q.ms} ms</span></div>
    </div>
  )
}

/** Combined chance of a long life ahead as a needle; the band spans the two models' answers. */
function Gauge({ res }) {
  const px = res.models.xgb.p_fit, pq = res.models.aqsvc.p_fit, p = (px + pq) / 2
  const ang = v => -90 + v * 180
  const pt = (v, r) => [100 + r * Math.sin((ang(v) * Math.PI) / 180), 96 - r * Math.cos((ang(v) * Math.PI) / 180)]
  const [a1, b1] = [Math.min(px, pq), Math.max(px, pq)]
  const arc = (v0, v1, r) => { const s = pt(v0, r), e = pt(v1, r); return `M${s[0]},${s[1]} A${r},${r} 0 0 1 ${e[0]},${e[1]}` }
  return (
    <svg className="gauge" viewBox="0 0 200 112" role="img" aria-label={`Combined chance of a long life ahead ${Math.round(p * 100)}%, models between ${Math.round(a1 * 100)}% and ${Math.round(b1 * 100)}%`} data-anim="gauge">
      <path d={arc(0, 1, 78)} className="g-track" />
      {b1 > a1 && <path d={arc(a1, b1, 78)} className="g-band" data-anim="fade" />}
      <g className="g-needle" style={{ '--a': `${ang(p)}deg` }} data-anim="needle"><line x1="100" y1="96" x2="100" y2="30" /><circle cx="100" cy="96" r="6" /></g>
      <text x="22" y="110" className="g-lbl">0%</text><text x="178" y="110" className="g-lbl" textAnchor="end">100%</text>
      <text x="100" y="110" className="g-lbl" textAnchor="middle">{Math.round(p * 100)}% long life</text>
    </svg>
  )
}

/** One tab for both ways of screening: type one battery's numbers, or upload a test-result file. */
function AssessUpload({ R }) {
  const [mode, setMode] = useState('upload')
  return (
    <>
      <Head motif={mode === 'upload' ? 'upload' : 'gauge'} R={R} explain="page.assess" title="Assess & upload test results">
        Screen batteries that are not in the fleet. Upload a test-result file (CSV or JSON) for one or many batteries, or type one battery's numbers.
        Either way XGBoost and AQSVC run on every battery at the same time and you get both answers, the usage baseline and a report you can download.
      </Head>
      <div className="toggle" role="tablist" aria-label="How to assess" style={{ marginBottom: 16 }}>
        <button role="tab" aria-selected={mode === 'upload'} className={mode === 'upload' ? 'on' : ''} onClick={() => setMode('upload')}>Upload test results</button>
        <button role="tab" aria-selected={mode === 'form'} className={mode === 'form' ? 'on' : ''} onClick={() => setMode('form')}>Type one battery's numbers</button>
      </div>
      {mode === 'upload' ? <Upload R={R} /> : <Assess R={R} />}
    </>
  )
}

function Assess({ R }) {
  const [form, setForm] = useState({ soh: 0.93, ir_mohm: 16.8, cycles: 450, temp_max_c: 37, charge_time_min: 10.5, fade_100: 0.012, ir_rise_100: 0.1, distance_km: 150 })
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = k => e => setForm({ ...form, [k]: e.target.value === '' ? null : Number(e.target.value) })
  const go = () => { setBusy(true); api('/api/assess', form).then(setRes).catch(e => setRes({ error: String(e) })).finally(() => setBusy(false)) }
  const fields = [['soh', 'Health now (capacity ÷ rating, e.g. 0.93)'], ['ir_mohm', 'Internal resistance (mΩ)'], ['cycles', 'Cycles done so far'],
    ['temp_max_c', 'Peak temperature per cycle (°C)'], ['charge_time_min', 'Charge time per cycle (min)'],
    ['fade_100', 'Capacity lost per 100 cycles (fraction) — optional'], ['ir_rise_100', 'Resistance rise per 100 cycles (mΩ) — optional'], ['distance_km', 'Transport distance (km)']]
  const plain = res && !res.error ? assessPlain(res) : null
  return (
    <>
      <p className="sub" style={{ marginTop: 0 }}>Enter one battery's quick test numbers. The quantum model builds this battery's QpiAI circuit; both answers appear side by side.</p>
      <div className="grid g2">
        <div className="card"><Explain id="assess.form" />
          <div className="form">{fields.map(([k, l]) => <label key={k}>{l}<input type="number" step="any" value={form[k] ?? ''} onChange={set(k)} /></label>)}</div>
          <div className="row" style={{ marginTop: 14 }}><button className="btn primary" disabled={busy} onClick={go}>{busy ? 'Running both models…' : 'Assess battery'}</button>
            <span className="muted small">Leave the optional history fields empty to see missing-data handling.</span></div>
        </div>
        <div className="card"><Explain id="assess.result" />
          {!res && <p className="muted">Result appears here.</p>}
          {res?.error && <div className="callout warn">{res.error}</div>}
          {plain && <>
            <div className="dl-row" style={{ marginTop: 0 }}><span className="lbl">Report</span>
              <button className="btn small-btn primary" onClick={() => downloadAssessPDF(plain)}>Download PDF</button>
              <button className="btn small-btn" onClick={() => downloadJSON(plain, 'cellfee-assessment.json')}>Download JSON</button>
            </div>
            <div className="plain" style={{ marginBottom: 12 }}><b className="small">IN PLAIN WORDS</b><p>{plain.decision.in_plain_words}</p>{plain.two_models.in_plain_words.map((t, i) => <p key={i}>{t}</p>)}</div>
            <Duo res={res} members={R.aqsvc.members} />
            <Gauge res={res} />
            <div className="row"><GradeBadge g={res.grade} /><span data-anim="stamp"><ActionTag a={res.suggested_action} /></span><b>Health {pc(res.soh)}</b></div>
            <p className="small">{res.reason}</p>
            {res.notes.length > 0 && <div className="callout warn small">{res.notes.join(' · ')}</div>}
            <p className="small muted">Quantum circuit: {res.circuit.qubits} qubits, depth {res.circuit.depth}, {res.circuit.gates} gates on {res.circuit.device}.</p>
            <b className="small">Usage baseline</b>
            <UsageBaseline u={res.usage} R={R} />
            <b className="small">Applications &amp; confidence</b>
            <AppConfidence apps={res.usage.applications} R={R} />
            <p className="small"><b>Net CO₂e vs new battery: </b>{res.environment.net_kgco2e.low} / {res.environment.net_kgco2e.central} / {res.environment.net_kgco2e.high} kg (low / central / high)</p>
            <p className="small"><b>Most similar fleet batteries: </b>{res.nearest_fleet_batteries.map(n => `${n.id} (k=${f2(n.similarity)}, ${n.action})`).join(', ')}</p>
            <p className="small muted">{res.disclaimer}</p>
          </>}
        </div>
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ Upload test results */
const RECENT_KEY = 'cellfee-recent-uploads'
const loadRecent = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] } }
const saveRecent = list => { try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 5))) } catch { /* storage full or unavailable */ } }

function Upload({ R }) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const [recent, setRecent] = useState(loadRecent)
  const inputRef = useRef(null)
  const [open, setOpen] = useState(null)

  const [downloads, setDownloads] = useState(recentDownloads)
  useEffect(() => { const on = () => setDownloads(recentDownloads()); window.addEventListener('cellfee-downloads', on); return () => window.removeEventListener('cellfee-downloads', on) }, [])
  const send = async file => {
    if (!file) return
    if (file.size > 10_000_000) { setRes({ error: 'That file is larger than 10 MB. Please upload a smaller file.' }); return }
    const b64 = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1]); r.onerror = bad; r.readAsDataURL(file) })
    sendText(file.name, null, b64)
  }
  // any file: CSV / JSON / Excel / Word / PDF / image (read on the server; images with OCR)
  const sendText = async (name, content, content_b64) => {
    setBusy(true); setRes(null); setOpen(null)
    try {
      const file = { name }
      const out = await api('/api/upload', content_b64 ? { filename: name, content_b64 } : { filename: name, content })
      setRes(out)
      const entry = { name: file.name, at: new Date().toLocaleString(), screened: out.screened, summary: out.summary, result: out }
      const next = [entry, ...recent.filter(r => r.name !== file.name)]
      setRecent(next); saveRecent(next)
    } catch (e) { setRes({ error: String(e.message || e) }) } finally { setBusy(false) }
  }
  // Chrome / Edge open the picker straight in the Downloads folder, showing every file (no type filter, so nothing in
  // Downloads is hidden); other browsers open their normal picker at the last folder used.
  const pick = async () => {
    if (window.showOpenFilePicker && window.top === window.self) {
      try {
        const [h] = await window.showOpenFilePicker({ id: 'cellfee-upload', startIn: 'downloads' })
        send(await h.getFile()); return
      } catch (e) { if (e?.name === 'AbortError') return }
    }
    inputRef.current?.click()
  }
  const sample = async () => saveText(await (await fetch('/api/upload/sample.csv')).text(), 'cellfee-sample-test-log.csv', 'text/csv')
  const plain = res && !res.error ? uploadPlain(res) : null
  return (
    <>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card"><Explain id="upload.how" />
          <div className={`drop${drag ? ' on' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files?.[0]) }}>
            <b>Drop a test-result file here</b>
            <span className="small muted">Any file: CSV, Excel, JSON, PDF, Word, or a photo / scan of a test report (JPEG, PNG) · max 10 MB</span>
            <button className="btn primary" disabled={busy} onClick={pick}>{busy ? 'Screening with both models…' : 'Choose file from Downloads'}</button>
            <input ref={inputRef} type="file" hidden onChange={e => { send(e.target.files?.[0]); e.target.value = '' }} />
          </div>
          <div className="recent-dl">
            <div className="row spread"><h4 style={{ margin: 0 }}>Recent downloads from CELLFEE</h4>
              {downloads.length > 0 && <button className="btn small-btn" onClick={() => { clearDownloads(); setDownloads([]) }}>Clear</button>}</div>
            <p className="small muted" style={{ margin: '4px 0 8px' }}>Files you downloaded here (CSV, JSON or PDF reports). One click screens one — no need to find it on your device.</p>
            {downloads.length === 0 && <p className="small muted">No downloads yet. Try the sample test log below, or download a passport JSON.</p>}
            {downloads.map(d => (
              <div key={d.name + d.at} className="recent row spread">
                <span><b className="mono">{d.name}</b><span className="small muted"> · {d.at}</span></span>
                {d.content || d.content_b64 ? <button className="btn small-btn primary" disabled={busy} onClick={() => sendText(d.name, d.content, d.content_b64)}>Screen this file</button>
                  : <span className="small muted">too large to keep in the browser — choose it from Downloads</span>}
              </div>
            ))}
          </div>
          <div className="row small" style={{ marginTop: 10 }}>
            <button className="btn small-btn" onClick={sample}>Download a sample test log</button>
            <span className="muted">real cycler data from three lab cells — try uploading it</span>
          </div>
          <h4 style={{ marginTop: 16 }}>What can be uploaded</h4>
          <p className="small"><b>Test data</b> in CSV, Excel or JSON: a cycle log (one row per cycle: <code>battery_id, cycle, discharge_capacity_ah, internal_resistance_ohm, temperature_max_c, charge_time_min</code>) or a summary (one row per battery: <code>battery_id, soh, fade_100, ir_mohm, ir_rise_100, temp_max_c, charge_time_min, cycles</code>).</p>
          <p className="small"><b>A test report</b> as PDF, Word, or a photo / scan (JPEG, PNG, WEBP): tables are read if present, otherwise values such as State of Health, internal resistance, cycle count, peak temperature and charge time are picked out of the text (photos with OCR). Every value read is shown with where it came from, and anything not found is assumed typical and flagged — check them.</p>
          <p className="small muted">Column names are matched flexibly (e.g. "Capacity (mAh)", "IR", "Temp max"); units such as mAh, mΩ and seconds are detected. Add <code>rated_capacity_ah</code> if your cells are not 1.1 Ah.
            The models were trained on LFP 18650 cells, so results for other chemistries are indicative only. Files are processed by your local CELLFEE server and are not stored.</p>
        </div>
        <div className="card"><Explain id="upload.recent" />
          <h3>Recent uploads</h3>
          <p className="sub">Kept in this browser only, so you can reopen a result.</p>
          {recent.length === 0 && <p className="muted small">Nothing uploaded yet.</p>}
          {recent.map(r => (
            <button key={r.name + r.at} className="recent" onClick={() => { setRes(r.result); setOpen(null) }}>
              <b>{r.name}</b><span className="small muted">{r.at} · {r.screened} batteries · reuse {r.summary.reuse} · test {r.summary.test} · recycle {r.summary.recycle}</span>
            </button>
          ))}
          {recent.length > 0 && <button className="btn small-btn" style={{ marginTop: 8 }} onClick={() => { setRecent([]); saveRecent([]) }}>Clear list</button>}
        </div>
      </div>
      {res?.error && <div className="callout warn">{res.error}</div>}
      {plain && (
        <div className="card table-wrap">
          <div className="row spread"><div><h3 style={{ margin: 0 }}>{res.filename}</h3>
            <p className="sub" style={{ margin: '4px 0 0' }}>{res.layout} · {res.screened} screened{res.failed ? ` · ${res.failed} could not be read` : ''} · reuse {res.summary.reuse} · test {res.summary.test} · recycle {res.summary.recycle}</p></div>
            <div className="dl-row" style={{ margin: 0 }}><span className="lbl">Report</span>
              <button className="btn small-btn primary" onClick={() => downloadUploadPDF(plain)}>Download PDF</button>
              <button className="btn small-btn" onClick={() => downloadJSON(plain, 'cellfee-screening.json')}>Download JSON</button></div></div>
          {res.warnings.map((w, i) => <div key={i} className="callout warn small">{w}</div>)}
          {res.document && <div className="callout small">Read as <b>{res.document.kind.toUpperCase()}</b>{res.document.notes.length ? ` — ${res.document.notes.join('; ')}` : ''}.</div>}
          <table className="fleet-table" style={{ marginTop: 12 }}>
            <thead><tr><th>Battery</th><th className="num">Health</th><th className="num">XGBoost</th><th className="num">AQSVC</th><th>Verdict</th><th className="col-sum">In plain words</th><th aria-label="Action" /></tr></thead>
            <tbody>{res.results.map((r, i) => r.error
              ? <tr key={i}><td className="f-id">{r.battery_id}</td><td colSpan={6} className="muted small">Could not screen: {r.error}</td></tr>
              : <Fragment key={i}>
                <tr onClick={() => setOpen(open === i ? null : i)}>
                  <td className="f-id">{r.battery_id}</td><td className="num f-soh">{Math.round(r.soh * 100)}<small>%</small></td>
                  <td className="num"><ModelCell p={r.models.xgb.p_fit} /></td><td className="num"><ModelCell p={r.models.aqsvc.p_fit} /></td>
                  <td><ActionTag a={r.suggested_action} /></td>
                  <td className="f-sum col-sum">{assessPlain(r).decision.in_plain_words}</td>
                  <td className="f-go">{open === i ? 'Hide' : 'Details →'}</td>
                </tr>
                {open === i && <tr className="detail"><td colSpan={7}>
                  <Duo res={r} members={R.aqsvc.members} />
                  <p className="small">{r.reason}</p>
                  <UsageBaseline u={r.usage} R={R} />
                  <AppConfidence apps={r.usage.applications} R={R} limit={5} />
                  {r.notes.length > 0 && <p className="small muted">{r.notes.join(' · ')}</p>}
                  <div className="dl-row"><span className="lbl">This battery</span>
                    <button className="btn small-btn" onClick={() => downloadAssessPDF(assessPlain(r, r.battery_id))}>Download PDF</button>
                    <button className="btn small-btn" onClick={() => downloadJSON(assessPlain(r, r.battery_id), `cellfee-${r.battery_id}.json`)}>Download JSON</button></div>
                </td></tr>}
              </Fragment>)}</tbody>
          </table>
          <p className="small muted">{res.disclaimer}</p>
        </div>
      )}
    </>
  )
}

/* ------------------------------------------------------------------ Market */
/** Marketplace tab: buy & sell used EV batteries, plus CELLFEE's own packs matched to buyers (QpiAI Opt). */
const MARKET_VIEWS = [['browse', 'Browse batteries'], ['sell', 'Sell a battery'], ['mine', 'My listings & interests'],
  ['partners', 'Testing partners (demo)'], ['packs', 'CELLFEE packs & matching']]

function Market({ R }) {
  const [view, setView] = useState(() => { try { return localStorage.getItem('cellfee-market-view') || 'browse' } catch { return 'browse' } })
  useEffect(() => { try { localStorage.setItem('cellfee-market-view', view) } catch { /* storage unavailable */ } }, [view])
  const KB = useMemo(() => buildKB(R), [R])
  return (
    <>
      <Head motif="match" R={R} explain="page.market" title="Marketplace">
        Buy and sell used EV batteries with their health reports, and see how CELLFEE's own packs are matched to buyers.
        A seller's report, a partner-verified report and a professional safety assessment are three different things; this marketplace never treats a report as a safety certificate.
      </Head>
      <MarketAssistant R={R} KB={KB} answer={guideAnswer} />
      <div className="toggle" role="tablist" aria-label="Marketplace views" style={{ marginBottom: 16, flexWrap: 'wrap' }}>
        {MARKET_VIEWS.map(([k, l]) => <button key={k} role="tab" aria-selected={view === k} className={view === k ? 'on' : ''} onClick={() => setView(k)}>{l}</button>)}
      </div>
      {view === 'browse' && <Browse R={R} />}
      {view === 'sell' && <Sell R={R} />}
      {view === 'mine' && <Mine />}
      {view === 'partners' && <Partners />}
      {view === 'packs' && <PackMatching R={R} />}
    </>
  )
}

function PackMatching({ R }) {
  const [data, setData] = useState({ ...R.market })
  const [nb, setNb] = useState({ name: 'Community microgrid (Pune)', application: 'solar', min_energy_wh: 11, max_price: 200, location: 'Pune', needs_test_report: true })
  const [added, setAdded] = useState([])
  const [busy, setBusy] = useState(false)
  const rematch = list => { setBusy(true); api('/api/market/match', list).then(setData).finally(() => setBusy(false)) }
  const byPair = useMemo(() => Object.fromEntries(data.all_pairs.map(p => [`${p.listing}|${p.buyer}`, p])), [data])
  return (
    <>
      <p className="sub" style={{ marginTop: 0 }}>CELLFEE-built packs and example listings matched to buyers: hard compatibility filters first, then a transparent score, then a one-to-one assignment solved as a QpiAI Opt model ({data.solver}).</p>
      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card table-wrap"><Explain id="market.listings" /><h3>Listings</h3>
          <table className="small"><thead><tr><th>ID</th><th>Seller</th><th className="num">Wh</th><th className="num">Weakest health</th><th className="num">Price</th><th>Evidence</th></tr></thead>
            <tbody>{data.listings.map(l => <tr key={l.id}><td className="mono">{l.id}</td><td>{l.seller}</td><td className="num">{l.energy_wh}</td><td className="num">{l.soh_min != null ? pc(l.soh_min) : '—'}</td><td className="num">{money(l.price)}</td>
              <td>{l.verified ? 'verified · ' : 'unverified · '}{l.test_report || <span className="muted">no report</span>}</td></tr>)}</tbody></table></div>
        <div className="card"><Explain id="market.buyer" /><h3>Post a buyer requirement</h3>
          <div className="form">
            <label>Name<input value={nb.name} onChange={e => setNb({ ...nb, name: e.target.value })} /></label>
            <label>Application<select value={nb.application} onChange={e => setNb({ ...nb, application: e.target.value })}>{R.applications.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
            <label>Min energy (Wh)<input type="number" value={nb.min_energy_wh} onChange={e => setNb({ ...nb, min_energy_wh: Number(e.target.value) })} /></label>
            <label>Budget (₹)<input type="number" value={nb.max_price} onChange={e => setNb({ ...nb, max_price: Number(e.target.value) })} /></label>
            <label>Location<select value={nb.location} onChange={e => setNb({ ...nb, location: e.target.value })}>{(data.locations || R.market.locations || ['Pune']).map(c => <option key={c}>{c}</option>)}</select></label>
            <label>Needs test report<select value={String(nb.needs_test_report)} onChange={e => setNb({ ...nb, needs_test_report: e.target.value === 'true' })}><option value="true">yes</option><option value="false">no</option></select></label>
          </div>
          <button className="btn primary" style={{ marginTop: 12 }} disabled={busy} onClick={() => { const list = [...added, nb]; setAdded(list); rematch(list) }}>{busy ? 'Matching…' : 'Add & re-match'}</button>
        </div>
      </div>
      <div className="card table-wrap" style={{ marginBottom: 16 }}><Explain id="market.matches" /><h3>Matches ({data.matches.length} of {data.compatible_pairs} compatible pairs)</h3>
        <MatchLinks data={data} apps={R.applications} />
        <table className="small"><thead><tr><th>Buyer</th><th>Listing</th><th className="num">Score</th><th>Why</th></tr></thead>
          <tbody>{data.matches.map(m => <tr key={m.buyer}><td>{m.buyer_detail.name}</td><td className="mono">{m.listing}</td><td className="num">{f3(m.score)}</td><td>{m.reasons.join(' · ')}</td></tr>)}</tbody></table>
      </div>
      <div className="card table-wrap"><Explain id="market.screen" /><h3>Compatibility screen (every buyer × listing)</h3>
        <table className="small"><thead><tr><th>Buyer \ Listing</th>{data.listings.map(l => <th key={l.id}>{l.id}</th>)}</tr></thead>
          <tbody>{data.buyers.map(b => <tr key={b.id}><td>{b.name}</td>{data.listings.map(l => { const p = byPair[`${l.id}|${b.id}`]; return (
            <td key={l.id} title={[...(p?.blockers || []), ...(p?.missing || [])].join('\n') || p?.reasons.join('\n')}>
              {p?.compatible ? <span className="tag"><i className="dot" style={{ background: 'var(--good)' }} />{f2(p.score)}</span> : <span className="muted">✕ {p?.blockers[0]?.slice(0, 34)}</span>}</td>) })}</tr>)}</tbody></table>
        <p className="muted small">Hover a cell for the full reasons. A match is a screening result only — not a recommendation to connect batteries.</p>
      </div>
    </>
  )
}

/** AQSVC's ensemble: the two tuned classifier maps and what each technique adds, fold by fold. */
function AqsvcEnsemble({ R }) {
  const A = R.aqsvc, folds = R.qml.folds
  return (
    <div className="card" style={{ marginBottom: 16 }}><Explain id="qml.ensemble" />
      <h3>AQSVC ensemble: bagging · boosting · heterogeneous maps · stacking</h3>
      <p className="sub">{A.bag} bagged + {A.boost} boosted QUBO-trained SVMs on each of {A.maps.length} quantum feature maps ({A.members} in all). A logistic-regression meta-learner, fitted on out-of-bag margins, stacks them into one probability.</p>
      <div className="grid g2">
        <div className="table-wrap"><table className="small"><thead><tr><th>Classifier map</th><th>Inputs → qubits</th><th>Tuned scales s · entangling g</th><th className="num">Held-out accuracy while tuning</th></tr></thead>
          <tbody>{A.maps.map(m => <tr key={m.inputs}><td>{m.inputs === 8 ? '7 features + cycles-to-80% estimate' : '7 screening features'}</td><td className="num">{m.inputs}</td>
            <td className="mono">[{m.scales.join(', ')}] · {m.entangle}</td><td className="num">{pc(m.validation_accuracy)}</td></tr>)}</tbody></table>
          <p className="small muted">Inputs are rank-encoded to angles in [0, π]. Scales are tuned for accuracy on held-out training cells, never on the test fold.</p></div>
        <div className="table-wrap"><table className="small"><thead><tr><th>Fold</th><th className="num">Plain vote</th><th className="num">Stacked (AQSVC)</th><th className="num">XGBoost</th></tr></thead>
          <tbody>{folds.map((f, i) => <tr key={f.fold}><td>{f.fold}</td><td className="num">{A.vote_accuracy_by_fold?.[i] != null ? pc(A.vote_accuracy_by_fold[i]) : '—'}</td><td className="num"><b>{pc(f.accuracy.aqsvc)}</b></td><td className="num">{pc(f.accuracy.xgb)}</td></tr>)}</tbody></table>
          <p className="small muted">Accuracy on cells the models never saw (grouped cross-validation by cell).</p></div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ Environment */
function Env({ R }) {
  const [p, setP] = useState({ soh: 0.9, nominal_kwh: 10, distance_km: 150, baseline: 'new_battery' })
  const [res, setRes] = useState(R.environment_example)
  useEffect(() => { const t = setTimeout(() => api('/api/environment', p).then(setRes).catch(() => {}), 250); return () => clearTimeout(t) }, [p])
  return (
    <>
      <Head motif="loop" R={R} explain="page.env" title="Environmental scenario estimate">Reuse compared against an explicit baseline with stated, editable assumptions. Outputs are estimates, not measured savings.</Head>
      <div className="grid g2">
        <div className="card"><Explain id="env.inputs" /><div className="form">
          <label>Health of the second-life battery (0–1)<input type="number" step="0.01" value={p.soh} onChange={e => setP({ ...p, soh: Number(e.target.value) })} /></label>
          <label>Nominal capacity (kWh)<input type="number" step="0.5" value={p.nominal_kwh} onChange={e => setP({ ...p, nominal_kwh: Number(e.target.value) })} /></label>
          <label>Transport distance (km)<input type="number" value={p.distance_km} onChange={e => setP({ ...p, distance_km: Number(e.target.value) })} /></label>
          <label>Baseline<select value={p.baseline} onChange={e => setP({ ...p, baseline: e.target.value })}><option value="new_battery">Buy a new battery instead</option><option value="recycle_now">Recycle now (no displaced product)</option></select></label>
        </div>
          <h3 style={{ marginTop: 16 }}>Assumptions</h3>
          <table className="small"><thead><tr><th>Factor</th><th className="num">Low</th><th className="num">Central</th><th className="num">High</th></tr></thead>
            <tbody>{Object.entries(res.assumptions).map(([k, v]) => <tr key={k}><td>{v.note}</td><td className="num">{v.low}</td><td className="num">{v.central}</td><td className="num">{v.high}</td></tr>)}</tbody></table>
        </div>
        <div className="card"><Explain id="env.result" />
          <h3>Net emissions avoided</h3><p className="sub">{res.functional_unit} · baseline: {res.baseline}</p>
          <div className="grid g3">{['low', 'central', 'high'].map(k => <div key={k} className="stat"><div className="label">{k} case</div><div key={res.net_kgco2e[k]} className="value">{res.net_kgco2e[k]}</div><div className="note">kg CO₂e</div></div>)}</div>
          {res.breakdown_central && <>
            <h4 style={{ marginTop: 16 }}>Where the central number comes from</h4>
            <BarList highlight="avoided_new_battery" rows={Object.entries(res.breakdown_central).map(([k, v]) => ({ key: k, label: { avoided_new_battery: 'New battery not made (saved)', refurbishment: 'Testing & refurbishing (spent)', extra_losses: 'Extra energy losses of aged cells (spent)', transport: 'Transport (spent)' }[k], value: v }))} format={v => `${v > 0 ? '+' : ''}${v.toFixed(1)}`} unit=" kg CO₂e" />
          </>}
          {res.equivalents && <EnvEquivalents eq={res.equivalents} />}
          <div className="callout small" style={{ marginTop: 14 }}>{res.label}. Avoided manufacturing is credited once; recycling is delayed (counted in both scenarios), so it is not double counted.</div>
        </div>
      </div>
      <EnvTotals />
    </>
  )
}

function EnvEquivalents({ eq }) {
  return <>
    <h4 style={{ marginTop: 16 }}>That is about the same as…</h4>
    <div className="grid g2 env-eq">{Object.entries(eq).map(([k, e]) => <div key={k} className="stat" title={e.note}><div key={e.value} className="value">{e.value.toLocaleString('en-IN')}</div><div className="note">{e.label}</div></div>)}</div>
    <p className="small muted">Central case. Hover a number for the factor behind it; each is a stated assumption.</p>
  </>
}

/** Totals under the same assumptions: CELLFEE's fleet plan and the buy & sell marketplace. */
function EnvTotals() {
  const [t, setT] = useState(null)
  useEffect(() => { api('/api/environment/summary').then(setT).catch(() => {}) }, [])
  if (!t) return null
  const kg = v => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)} t` : `${Math.round(v)} kg`)
  const rows = [
    ['fleet_reused', 'Fleet plan: cells reused', 'Cells QpiAI Opt sent straight to reuse (lab cells, ~3.6 Wh each).'],
    ['fleet_expected_after_test', 'Fleet plan: expected after testing', 'Cells sent to a test, each weighted by the models\' chance that the test confirms it.'],
    ['market_listed', 'Marketplace: batteries listed', 'Every battery shown in Browse, if each found a second-life buyer instead of a new battery being made.'],
    ['market_sold', 'Marketplace: batteries sold', 'Listings marked sold.'],
  ]
  return (
    <div className="card" style={{ marginTop: 16 }}><Explain id="env.totals" />
      <h3>Totals: the fleet plan and the marketplace</h3>
      <p className="sub">Same assumptions as above, baseline "buy a new battery instead"; {t.assumptions.fleet_distance_km} km transport for fleet cells, {t.assumptions.market_distance_km} km for marketplace batteries.</p>
      <div className="table-wrap"><table className="small">
        <thead><tr><th>What</th><th className="num">Batteries</th><th className="num">Usable kWh</th><th className="num">Net CO₂e avoided (low / central / high)</th><th className="num">Battery mass kept in use</th><th>Central case is about</th></tr></thead>
        <tbody>{rows.map(([k, label, note]) => { const r = t[k]; return <tr key={k} title={note}><td><b>{label}</b><div className="muted">{note}</div></td><td className="num">{r.count.toLocaleString()}</td><td className="num">{r.usable_kwh.toLocaleString('en-IN')}</td>
          <td className="num">{kg(r.net_kgco2e.low)} / <b>{kg(r.net_kgco2e.central)}</b> / {kg(r.net_kgco2e.high)}</td><td className="num">{kg(r.battery_kg_kept_in_use)}</td>
          <td>{r.equivalents.car_km.value.toLocaleString('en-IN')} km of petrol driving · {r.equivalents.tree_years.value.toLocaleString('en-IN')} tree-years</td></tr> })}</tbody></table></div>
      <div className="callout small" style={{ marginTop: 12 }}>{t.label}. The fleet uses 1.1 Ah laboratory cells, so its totals are small; marketplace batteries are whole EV packs and modules. Marketplace figures use each seller's <i>reported</i> SoH, and the demo listings are fictional.</div>
    </div>
  )
}

/* ------------------------------------------------------------------ Evidence */
function Evidence({ R }) {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(null)
  useEffect(() => { api('/api/evidence').then(setRows) }, [])
  return (
    <>
      <Head explain="page.evidence" title="Evidence log">Every QpiAI QCloud / QpiAI Opt run is recorded with its device, settings, job IDs (cloud runs) and outputs — reproducible from the repository.</Head>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat explain="evidence.sdk" label="QpiAI Quantum SDK" value={R.sponsor_status.qpiai_quantum_version} note={`kernel device ${R.sponsor_status.kernel_device}`} />
        <Stat explain="evidence.qaoa" label="QAOA device" value={R.sponsor_status.qaoa_device} />
        <Stat explain="evidence.opt" label="Opt solver" value={R.sponsor_status.opt_key_configured ? 'QpiAI Opt' : 'Fallback'} note={R.sponsor_status.opt_solver} />
        <Stat explain="evidence.runs" label="Runs recorded" value={rows ? rows.length : '…'} />
      </div>
      <div className="card table-wrap"><Explain id="evidence.log" /><table className="small">
        <thead><tr><th>Run</th><th>Kind</th><th>Backend</th><th>Device</th><th>Summary</th></tr></thead>
        <tbody>{(rows || []).map(r => <tr key={r.run_id} className="click" onClick={() => api(`/api/evidence/${r.run_id}`).then(setOpen)}>
          <td className="mono">{r.run_id}</td><td>{r.kind}</td><td>{r.backend}</td><td>{r.device || '—'}</td><td>{r.summary}</td></tr>)}</tbody></table></div>
      {open && <div className="drawer"><div className="row spread"><h3 style={{ margin: 0 }}>{open.run_id}</h3><div className="row"><button className="btn small-btn" onClick={() => downloadJSON(open, `cellfee-run-${open.run_id}.json`)}>Download JSON</button><button className="btn" onClick={() => setOpen(null)}>Close</button></div></div>
        <pre className="mono small" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(open, null, 2).slice(0, 20000)}</pre></div>}
    </>
  )
}

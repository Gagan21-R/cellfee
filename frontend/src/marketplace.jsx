// Buy & sell marketplace for used EV batteries (seller wizard, buyer browse / detail / interest, status tracking,
// demo testing-partner verification). All data comes from /api/listings. Listings flagged `demo` were created by
// `python -m cellfee.market_seed` (fictional people and batteries) and are labelled "Demo listing" wherever shown.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { inr } from './usageFormat.js'
import { Explain, useGuide } from './Assistant.jsx'

const api = (path, body, method) =>
  fetch(path, body !== undefined ? { method: method || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
    .then(async r => { if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m } catch { /* not json */ } throw new Error(m) } return r.json() })

// seller / buyer keys live only in this browser (the server stores hashes)
const store = key => ({
  get: () => { try { return JSON.parse(localStorage.getItem(key) || '{}') } catch { return {} } },
  put: (id, tok) => { try { const m = JSON.parse(localStorage.getItem(key) || '{}'); m[id] = tok; localStorage.setItem(key, JSON.stringify(m)) } catch { /* storage unavailable */ } },
  putAll: keys => { try { const m = JSON.parse(localStorage.getItem(key) || '{}'); localStorage.setItem(key, JSON.stringify({ ...m, ...keys })) } catch { /* storage unavailable */ } },
})
const DEMO_KEY = 'cellfee-demo-persona'
const sellerKeys = store('cellfee-seller-keys'), buyerKeys = store('cellfee-buyer-keys')

const toB64 = file => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.onerror = rej; r.readAsDataURL(file) })
// file-picker filters as plain extensions: MIME wildcards such as image/* make the Windows file picker very slow to open
const REPORT_TYPES = '.pdf,.doc,.docx,.jpg,.jpeg,.png,.webp'
const PHOTO_TYPES = '.jpg,.jpeg,.png,.webp'
export const NA = 'not_available'
export const show = v => (v === NA ? 'Not available' : v == null || v === '' ? '—' : String(v))
const VCLASS = { verified: 'reuse', awaiting_provider: 'test', report_uploaded: 'test', more_testing: 'test', mismatch: 'recycle', held: 'recycle', rejected: 'recycle', draft: '' }
export const NOTE = 'A health report or CELLFEE estimate is not a safety certification. Have the battery inspected by a qualified professional before buying or using it.'

export function VerifBadge({ v, label }) { return <span className={`tag t-${VCLASS[v] || ''}`}>{label}</span> }

/* ================================================================== browse (buyers) */
export function Browse({ R }) {
  const { explain } = useGuide()
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [f, setF] = useState({ q: '', min: '', max: '', chem: 'all', cap: '', soh: '', age: '', city: 'all', form: 'all', ver: 'all', use: 'all', sort: 'rank' })
  const [open, setOpen] = useState(null)
  useEffect(() => { api('/api/listings').then(setData).catch(e => setErr(String(e.message || e))) }, [open])
  const set = k => e => setF({ ...f, [k]: e.target.value })
  const list = useMemo(() => {
    if (!data) return []
    const num = v => (v === '' || v == null || v === NA ? null : Number(v))
    let L = data.listings.filter(l => {
      const d = l.details, r = l.report, p = num(l.sale.price_inr)
      const s = (f.q || '').toLowerCase()
      if (s && !`${d.manufacturer} ${d.model} ${d.vehicle} ${l.id}`.toLowerCase().includes(s)) return false
      if (f.min && (p == null || p < +f.min)) return false
      if (f.max && (p == null || p > +f.max)) return false
      if (f.chem !== 'all' && String(d.chemistry || '').toUpperCase() !== f.chem) return false
      if (f.cap && (num(r.measured_capacity_kwh ?? d.rated_capacity_kwh) ?? 0) < +f.cap) return false
      if (f.soh && (num(r.soh_pct) ?? 0) < +f.soh) return false
      if (f.age && (num(d.age_years) == null || num(d.age_years) > +f.age)) return false
      if (f.city !== 'all' && d.city !== f.city) return false
      if (f.form !== 'all' && d.form !== f.form) return false
      if (f.ver !== 'all' && l.verification !== f.ver) return false
      if (f.use !== 'all' && !l.uses.some(u => u.id === f.use)) return false
      return true
    })
    if (f.sort === 'price_low') L = [...L].sort((a, b) => (a.sale.price_inr ?? 1e12) - (b.sale.price_inr ?? 1e12))
    if (f.sort === 'price_high') L = [...L].sort((a, b) => (b.sale.price_inr ?? 0) - (a.sale.price_inr ?? 0))
    if (f.sort === 'newest') L = [...L].sort((a, b) => b.created.localeCompare(a.created))
    return L
  }, [data, f])
  if (err) return <div className="callout warn">{err}</div>
  if (!data) return <p className="muted">Loading listings…</p>
  return (
    <>
      <div className="card" style={{ marginBottom: 14 }}><Explain id="market.browse" />
        <div className="form mk-filters" style={{ marginTop: 34 }}>
          <label>Search<input value={f.q} onChange={set('q')} placeholder="make, model, vehicle" /></label>
          <label>Price from (₹)<input type="number" value={f.min} onChange={set('min')} /></label>
          <label>Price to (₹)<input type="number" value={f.max} onChange={set('max')} /></label>
          <label>Chemistry<select value={f.chem} onChange={set('chem')}><option value="all">Any</option>{['LFP', 'NMC', 'NCA', 'LMO', 'LCO', 'LTO'].map(c => <option key={c}>{c}</option>)}</select></label>
          <label>Capacity at least (kWh)<input type="number" step="any" value={f.cap} onChange={set('cap')} /></label>
          <label>Reported SoH at least (%)<input type="number" value={f.soh} onChange={set('soh')} /></label>
          <label>Age at most (years)<input type="number" value={f.age} onChange={set('age')} /></label>
          <label>Location<select value={f.city} onChange={set('city')}><option value="all">Anywhere</option>{data.cities.map(c => <option key={c}>{c}</option>)}</select></label>
          <label>Pack or module<select value={f.form} onChange={set('form')}><option value="all">Either</option><option value="pack">Complete pack</option><option value="module">Module</option></select></label>
          <label>Report status<select value={f.ver} onChange={set('ver')}><option value="all">Any</option>{['verified', 'awaiting_provider', 'report_uploaded', 'more_testing'].map(v => <option key={v} value={v}>{data.verification_labels[v]}</option>)}</select></label>
          <label>Use case<select value={f.use} onChange={set('use')}><option value="all">Any</option>{data.uses.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
          <label>Sort<select value={f.sort} onChange={set('sort')}><option value="rank">Best evidence first</option><option value="price_low">Price: low → high</option><option value="price_high">Price: high → low</option><option value="newest">Newest</option></select></label>
        </div>
        <p className="small muted" style={{ margin: '8px 0 0' }}>"Best evidence first" ranks by {data.ranking} — never by SoH alone. <button className="link-btn" onClick={() => explain('market.status')}>What do the report labels mean?</button></p>
      </div>
      {data.listings.length === 0 && <div className="callout">No batteries are listed yet. Sellers can list one under <b>Sell a battery</b>.</div>}
      {data.listings.length > 0 && list.length === 0 && <p className="muted">No listing matches these filters.</p>}
      {data.listings.length > 0 && <p className="small muted" style={{ margin: '0 0 10px' }}>Showing {list.length} of {data.listings.length} batteries{data.listings.some(l => l.demo) ? ' · listings marked "Demo listing" are fictional sample data (people, batteries and reports invented to show the marketplace working)' : ''}.</p>}
      <div className="mk-grid">
        {list.map(l => (
          <div key={l.id} className="card mk-card">
            {l.photos[0] ? <img className="mk-thumb" src={`/api/listings/${l.id}/photos/0`} alt={`${show(l.details.manufacturer)} ${show(l.details.model)}`} loading="lazy" />
              : <div className="mk-thumb mk-nophoto small muted">no photo</div>}
            <div className="row spread" style={{ alignItems: 'flex-start' }}><h4 style={{ margin: 0 }}>{[l.details.manufacturer, l.details.model].filter(v => v && v !== NA).join(' ') || 'Battery'}</h4>
              <b className="mono">{inr(l.sale.price_inr)}</b></div>
            <div className="small">{show(l.details.form === 'pack' ? 'Complete pack' : l.details.form === 'module' ? 'Module' : l.details.form)} · {show(l.details.chemistry)} · {show(l.details.city)}</div>
            <div className="small">Capacity {show(l.report.measured_capacity_kwh ?? l.details.rated_capacity_kwh)} kWh · reported SoH {show(l.report.soh_pct)}%</div>
            <div className="small muted">Report {show(l.report.test_date)}{l.report.provider ? ` · ${l.report.provider}` : ''}</div>
            {l.seller && <div className="small muted">Seller: {l.seller.name} ({l.seller.type})</div>}
            <div className="row" style={{ marginTop: 6, flexWrap: 'wrap' }}><VerifBadge v={l.verification} label={l.verification_label} />{l.sale.negotiable && <span className="tag">negotiable</span>}{l.demo && <span className="tag t-demo">Demo listing</span>}</div>
            <button className="btn small-btn primary" style={{ marginTop: 8 }} onClick={() => setOpen(l.id)}>View details</button>
          </div>
        ))}
      </div>
      <p className="small muted">{data.disclaimer}</p>
      {open && <ListingDetail id={open} close={() => setOpen(null)} />}
    </>
  )
}

/* ================================================================== detail page (full screen) */
export function ListingDetail({ id, close }) {
  const [l, setL] = useState(null)
  const [err, setErr] = useState(null)
  const [form, setForm] = useState({ name: '', contact: '', message: '' })
  const [sent, setSent] = useState(null)
  const ref = useRef(null)
  useEffect(() => { api(`/api/listings/${id}`).then(setL).catch(e => setErr(String(e.message || e))) }, [id])
  useEffect(() => { ref.current?.focus(); const k = e => { if (e.key === 'Escape') close() }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [close])
  const interest = () => api(`/api/listings/${id}/interest`, form).then(r => { buyerKeys.put(r.id, r.token); setSent(r) }).catch(e => setSent({ error: String(e.message || e) }))
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={`Battery listing ${id}`} tabIndex={-1} ref={ref}>
      <div className="row spread"><h3 style={{ margin: 0 }}>Listing · {id}</h3><button className="btn" onClick={close}>Close</button></div>
      {err && <div className="callout warn">{err}</div>}
      {!l && !err && <p className="muted">Loading…</p>}
      {l && <>
        <div className="row" style={{ margin: '10px 0', flexWrap: 'wrap' }}><VerifBadge v={l.verification} label={l.verification_label} /><span className="tag">{l.status_label}</span><b className="mono" style={{ fontSize: 22 }}>{inr(l.sale.price_inr)}</b>{l.sale.negotiable && <span className="tag">negotiable</span>}</div>
        {l.demo && <div className="callout small"><b>Demo listing.</b> The seller, battery, report and photos are fictional sample data, generated to show how the marketplace works.</div>}
        {l.seller && <p className="small" style={{ margin: '6px 0' }}>Seller: <b>{l.seller.name}</b> · {l.seller.type} · {show(l.details.city)}</p>}
        {l.partner_confirmation && <div className="callout small">Partner check: {l.partner_confirmation.reason} ({l.partner_confirmation.at?.slice(0, 10)})</div>}
        <div className="callout warn small">{l.verification_note} {NOTE}</div>
        {l.photos.length > 0 && <div className="mk-photos">{l.photos.map(p => <figure key={p.n}><img src={`/api/listings/${id}/photos/${p.n}`} alt={`${p.kind} photo`} /><figcaption className="small muted">{p.kind}</figcaption></figure>)}</div>}
        <div className="grid g2" style={{ marginTop: 12 }}>
          <div><h4>Battery</h4><Specs d={l.details} /></div>
          <div><h4>Health report ({l.report_file?.kind?.toUpperCase() || 'none'})</h4><ReportFields r={l.report} />
            {l.report_file && <p className="small"><a className="btn small-btn" href={`/api/listings/${id}/report-file`} target="_blank" rel="noopener noreferrer">Open the original report</a> <span className="muted">{l.report_file.original_name}</span></p>}</div>
        </div>
        <h4>Seller's description</h4>
        <div className="kv small"><div>Condition</div><div>{show(l.sale.condition)}</div><div>Known faults</div><div>{show(l.sale.known_faults)}</div>
          <div>Warranty / refurbishment</div><div>{show(l.sale.warranty)}</div><div>Inspection before purchase</div><div>{l.sale.inspection_allowed ? 'allowed' : 'not offered'}</div>
          <div>Transport</div><div>{show(l.sale.transport)}</div><div>Usage history</div><div>{show(l.details.usage_history)}</div></div>
        <h4>Checks &amp; outstanding items</h4><Checks list={l.checks} />
        {l.missing.length > 0 && <p className="small">Not available from the seller: {l.missing.join(', ').replaceAll('_', ' ')}.</p>}
        <h4>Possible uses</h4>
        {l.uses.length ? <p className="small">{l.uses.map(u => u.name).join(' · ')}. <span className="muted">From the reported SoH{l.verification !== 'verified' ? ' (not yet verified)' : ''} against each use's health floor; not a certification.</span></p> : <p className="small muted">No use case can be suggested from the information given.</p>}
        <ListingCO2 l={l} />
        <h4>Interested?</h4>
        {sent && !sent.error ? <div className="callout small">Sent. {sent.next} Track it under <b>My listings &amp; interests</b>.</div> : <>
          <p className="small muted">The seller sees your name and message, not your contact, until they accept. Then both of you see each other's contact details.</p>
          <div className="form"><label>Your name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
            <label>Your phone or email<input value={form.contact} onChange={e => setForm({ ...form, contact: e.target.value })} /></label>
            <label>Message<input value={form.message} onChange={e => setForm({ ...form, message: e.target.value })} placeholder="e.g. Can I arrange an inspection?" /></label></div>
          <button className="btn primary" style={{ marginTop: 10 }} disabled={form.name.length < 2 || form.contact.length < 5} onClick={interest}>Send interest to the seller</button>
          {sent?.error && <div className="callout warn small">{sent.error}</div>}</>}
        <p className="small muted" style={{ marginTop: 14 }}>{l.disclaimer}</p>
      </>}
    </div>
  )
}

/** CO₂ estimate for buying this battery instead of a new one (same assumptions as the Environmental impact tab). */
function ListingCO2({ l }) {
  const [e, setE] = useState(null)
  const soh = Number(l.report.soh_pct) / 100
  const nominal = Number(l.details.rated_capacity_kwh) || Number(l.report.measured_capacity_kwh) / soh
  useEffect(() => {
    if (soh > 0 && soh <= 1.1 && nominal > 0 && nominal <= 200) api('/api/environment', { soh, nominal_kwh: nominal, distance_km: 300, baseline: 'new_battery' }).then(setE).catch(() => {})
  }, [l.id])
  if (!e) return null
  return <>
    <h4>Environmental impact</h4>
    <p className="small">Giving this battery a second life instead of buying a new one avoids an estimated <b>{Math.round(e.net_kgco2e.central).toLocaleString('en-IN')} kg CO₂e</b> (range {Math.round(e.net_kgco2e.low).toLocaleString('en-IN')}–{Math.round(e.net_kgco2e.high).toLocaleString('en-IN')} kg). That is about {e.equivalents.car_km.value.toLocaleString('en-IN')} km of petrol-car driving, or {e.equivalents.tree_years.value.toLocaleString('en-IN')} tree-years of CO₂ uptake. <span className="muted">Estimate from the reported SoH{l.verification !== 'verified' ? ' (not yet verified)' : ''}, 300 km transport and stated assumptions; not a measured saving.</span></p>
  </>
}

function Specs({ d }) {
  const rows = [['Manufacturer', d.manufacturer], ['Model', d.model], ['Chemistry', d.chemistry], ['Original vehicle', d.vehicle], ['Age (years)', d.age_years],
    ['Battery ID / serial', d.serial], ['Rated capacity (kWh)', d.rated_capacity_kwh], ['Rated voltage (V)', d.rated_voltage_v],
    ['Location', d.city], ['Pack or module', d.form], ['Reason for selling', d.reason]]
  return <div className="kv small">{rows.map(([k, v]) => <Fragment key={k}><div>{k}</div><div className="mono">{show(v)}</div></Fragment>)}</div>
}
function ReportFields({ r }) {
  const rows = [['Testing provider', r.provider], ['Report ID', r.report_id], ['Test date', r.test_date], ['Reported SoH (%)', r.soh_pct],
    ['Measured capacity (kWh)', r.measured_capacity_kwh], ['Internal resistance (mΩ)', r.internal_resistance_mohm], ['Other measurements', r.other_measurements],
    ['Tests performed', r.tests_performed], ['Known limitations', r.limitations], ['Issuer / verification reference', r.issuer_reference]]
  return <div className="kv small">{rows.map(([k, v]) => <Fragment key={k}><div>{k}</div><div className="mono">{show(v)}</div></Fragment>)}</div>
}
function Checks({ list }) {
  if (!list?.length) return <p className="small muted">No issues found by the automatic checks.</p>
  return <div className="mk-checks">{list.map((c, i) => <div key={i} className={`mk-check ${c.level}`}><b>{c.message}</b><span className="small">{c.reason}</span></div>)}</div>
}

/* ================================================================== sell (seller wizard) */
const STEPS = ['Battery details', 'Health report', 'Price & sale', 'Photos', 'Preview & submit']

export function Sell({ R, onDone }) {
  const [draft, setDraft] = useState(null)       // {id, token}
  const [v, setV] = useState(null)               // server view of the listing
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [noReport, setNoReport] = useState(false)
  const [agree, setAgree] = useState(false)
  const [pre, setPre] = useState(null)
  const [cities, setCities] = useState([])
  const [partners, setPartners] = useState([])
  useEffect(() => { api('/api/listings').then(d => { setCities(d.cities); setPartners(d.partners) }).catch(() => {}) }, [])
  const run = async fn => { setBusy(true); setErr(null); try { await fn() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) } }
  const start = () => run(async () => { const r = await api('/api/listings', {}); sellerKeys.put(r.id, r.token); setDraft(r); setV(await api(`/api/listings/${r.id}`, { token: r.token, details: {} }, 'PATCH')) })
  const patch = body => run(async () => setV(await api(`/api/listings/${draft.id}`, { token: draft.token, ...body }, 'PATCH')))
  const [mode, setMode] = useState(null)          // null (choose) | 'quick' | 'steps'
  if (mode === 'quick') return <QuickSell cities={cities} back={() => setMode(null)} onDone={onDone} />
  if (!draft) return (
    <div className="grid g2 mk-sell-start">
      <div className="card"><Explain id="market.quick" />
        <span className="tag t-reuse">Recommended · about 2 minutes</span>
        <h3 style={{ marginTop: 8 }}>⚡ Quick listing: just drop your files</h3>
        <p className="small">Upload the battery's <b>health report</b> (PDF, Word or a photo of it) and a few <b>photos</b>. CELLFEE reads the report and fills in the listing for you: make, model, chemistry, serial number, capacity, State of Health, test lab and date. You only check what was read and add the price and your contact.</p>
        <button className="btn primary" style={{ marginTop: 6 }} onClick={() => setMode('quick')}>Start a quick listing</button>
      </div>
      <div className="card">
        <span className="tag">Full control</span>
        <h3 style={{ marginTop: 8 }}>Step-by-step form</h3>
        <p className="small">Five short steps: battery details → health report → price → photos → preview, with a guide on every step. You can mark anything you don't know as <b>Not available</b>.</p>
        <button className="btn" style={{ marginTop: 6 }} disabled={busy} onClick={start}>Start the step-by-step form</button>
        {err && <div className="callout warn small">{err}</div>}
      </div>
      <div className="card" style={{ gridColumn: '1 / -1' }}><Explain id="market.sell" /><SellGuide /></div>
    </div>
  )
  return (
    <div className="card"><Explain id="market.sell" />
      <ol className="mk-steps" style={{ paddingRight: 130 }}>{STEPS.map((s, i) => <li key={s} className={i === step ? 'on' : i < step ? 'done' : ''}><button onClick={() => setStep(i)} disabled={busy}>{i + 1}. {s}</button></li>)}</ol>
      <p className="small muted">Listing {draft.id} · saved automatically · your seller key is kept in this browser.</p>
      <StepGuide step={step} />
      {err && <div className="callout warn small">{err}</div>}
      {step === 0 && v && <DetailsStep v={v} cities={cities} save={d => patch({ details: d }).then(() => setStep(1))} busy={busy} />}
      {step === 1 && v && <ReportStep v={v} draft={draft} setV={setV} run={run} busy={busy} noReport={noReport} setNoReport={setNoReport} partners={partners}
        save={r => patch({ report: r }).then(() => setStep(2))} />}
      {step === 2 && v && <SaleStep v={v} agree={agree} setAgree={setAgree} save={s => patch({ sale: s }).then(() => setStep(3))} busy={busy} />}
      {step === 3 && v && <PhotoStep v={v} draft={draft} setV={setV} run={run} busy={busy} next={() => run(async () => { setPre(await api(`/api/listings/${draft.id}/preview`, { token: draft.token })); setStep(4) })} />}
      {step === 4 && pre && <PreviewStep pre={pre} draft={draft} agree={agree} busy={busy} run={run} done={r => { setPre({ ...r, submitted: true }); onDone?.() }} />}
    </div>
  )
}

/* ---------------------------------------------------------------- seller guide */
const SAMPLE = <span className="small">No files at hand? Try it with a <a href="/api/listings/sample/report.pdf">sample report (PDF)</a>, a <a href="/api/listings/sample/photo.png?kind=exterior">sample exterior photo</a> and a <a href="/api/listings/sample/photo.png?kind=label">sample label photo</a> (fictional, marked as samples).</span>

function SellGuide() {
  return <>
    <h3>How selling works</h3>
    <ol className="mk-guide">
      <li><b>Get a health report.</b> A testing shop or lab measures the battery's State of Health (SoH), capacity and internal resistance. A report from a <i>registered testing partner</i> can later be verified.</li>
      <li><b>Upload the report and a few photos.</b> An exterior photo and the label with the serial number are the most useful. Don't open the battery to take photos.</li>
      <li><b>Check what CELLFEE read, add your price and contact.</b> Your contact stays private until you accept a buyer.</li>
      <li><b>Automatic checks run</b> (serial matches the report, report not too old, no duplicate report). Then the listing goes live in <b>Browse batteries</b>.</li>
      <li><b>Buyers send interest; you accept or decline</b> under <b>My listings &amp; interests</b>. Accepting shares both contacts.</li>
    </ol>
    <div className="grid g2">
      <div className="callout small"><b>What a good report contains:</b> test lab name · report ID · test date · battery serial number · chemistry · State of Health (%) · measured capacity (kWh) · internal resistance (mΩ) · which tests were done.</div>
      <div className="callout small"><b>Good to know:</b> uploading a report does not make a listing "verified": only the testing partner confirming it can. Even then it is not a safety certificate. {SAMPLE}</div>
    </div>
  </>
}

const STEP_TIPS = [
  ['Battery details', 'Copy these from the battery label or the vehicle papers. The serial number must match the one on the report, or the listing is stopped for a mismatch. Only city and pack/module are required; tick "Not available" for anything you don\'t know.'],
  ['Health report', 'Upload the report first: CELLFEE reads it and fills in the fields below (each read value shows the text it came from). Check every value; if the document and your entry disagree by more than 2 SoH points, the listing is flagged.'],
  ['Price & sale', 'Similar listings in Browse batteries give a price guide (most sell for roughly ₹4,000–9,000 per kWh of remaining capacity). Disclose known faults: it builds trust and protects you. Your contact is shown only to a buyer you accept.'],
  ['Photos', 'Best photos: the whole battery from outside, the label with the serial number, and the connector. Use daylight, no flash glare. Never open or dismantle a high-voltage battery.'],
  ['Preview & submit', 'This is exactly what buyers will see. Read the checks: a red item stops the listing; amber items are shown to buyers as outstanding.'],
]
function StepGuide({ step }) {
  const [hide, setHide] = useState(false)
  if (hide) return <button className="link-btn small" onClick={() => setHide(false)}>Show the guide for this step</button>
  return <div className="callout small mk-stepguide"><b>Guide · {STEP_TIPS[step][0]}:</b> {STEP_TIPS[step][1]} <button className="link-btn" onClick={() => setHide(true)}>hide</button></div>
}

/* ---------------------------------------------------------------- quick listing: report + photos, then confirm */
const READ_LABELS = { manufacturer: 'Manufacturer', model: 'Model', vehicle: 'Original vehicle', chemistry: 'Chemistry', serial: 'Serial number', age_years: 'Age (years)',
  rated_capacity_kwh: 'Rated capacity (kWh)', rated_voltage_v: 'Rated voltage (V)', city: 'City', form: 'Pack or module' }
const REP_LABELS = { provider: 'Testing lab', report_id: 'Report ID', test_date: 'Test date', soh_pct: 'State of Health (%)', measured_capacity_kwh: 'Measured capacity (kWh)', internal_resistance_mohm: 'Internal resistance (mΩ)',
  tests_performed: 'Tests performed', limitations: 'Known limitations of the test' }

function QuickSell({ cities, back, onDone }) {
  const [report, setReport] = useState(null)
  const [photos, setPhotos] = useState([])
  const [draft, setDraft] = useState(null)
  const [v, setV] = useState(null)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)
  const [d, setD] = useState({})
  const [r, setR] = useState({})
  const [s, setS] = useState({ price_inr: '', negotiable: true, contact_method: 'phone', contact_value: '', condition: '', known_faults: '', inspection_allowed: true })
  const [agree, setAgree] = useState(false)
  const [pre, setPre] = useState(null)
  const [drag, setDrag] = useState(false)
  const take = files => {
    const fs = [...files]
    const isImg = f => /^image\//.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name)
    const doc = fs.find(f => !isImg(f))
    if (doc) setReport(doc)
    const imgs = fs.filter(isImg)
    if (!doc && !report && imgs.length) { setReport(imgs[0]); imgs.shift() }   // a photo of the report
    setPhotos(p => [...p, ...imgs].slice(0, 8))
  }
  const read = async () => {
    setErr(null)
    try {
      setBusy('Creating your listing…')
      const dr = await api('/api/listings', {}); sellerKeys.put(dr.id, dr.token); setDraft(dr)
      setBusy(`Reading ${report.name}… (a photo of a report is read with OCR and can take a few seconds)`)
      let view = await api(`/api/listings/${dr.id}/report`, { token: dr.token, filename: report.name, content_b64: await toB64(report) })
      for (let k = 0; k < photos.length; k++) {
        setBusy(`Uploading photo ${k + 1} of ${photos.length}…`)
        view = await api(`/api/listings/${dr.id}/photos`, { token: dr.token, filename: photos[k].name, content_b64: await toB64(photos[k]), kind: ['exterior', 'label'][k] || 'condition' })
      }
      setV(view); setD(view.details); setR(view.report)
      const sl = view.sale || {}            // price, contact, condition... written in the report
      setS(prev => ({ ...prev, ...Object.fromEntries(Object.entries(sl).filter(([, x]) => x !== null && x !== '' && x !== undefined)),
        ...(sl.price_inr != null ? { price_inr: String(sl.price_inr) } : {}) }))
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(null) }
  }
  const ext = v?.extracted || {}
  const readKeys = new Set(Object.keys(ext).map(k => ({ capacity_kwh: 'measured_capacity_kwh', ir_mohm: 'internal_resistance_mohm', voltage_v: 'rated_voltage_v' }[k] || k)))
  const missing = [!d.city && 'city', !d.form && 'pack or module', !s.price_inr && 'price', !s.contact_value && 'your contact', !agree && 'the confirmation'].filter(Boolean)
  const preview = async () => {
    setErr(null); setBusy('Saving and running the checks…')
    try {
      const num = x => (x === '' || x == null ? undefined : x)
      await api(`/api/listings/${draft.id}`, { token: draft.token, details: Object.fromEntries(Object.entries(d).filter(([, x]) => num(x) !== undefined)),
        report: Object.fromEntries(Object.entries(r).filter(([k, x]) => k !== 'extracted' && num(x) !== undefined)),
        sale: { ...s, price_inr: Number(s.price_inr) } }, 'PATCH')
      setPre(await api(`/api/listings/${draft.id}/preview`, { token: draft.token }))
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(null) }
  }
  const field = (obj, set, k, label, type = 'text') => (
    <label key={k} className={readKeys.has(k) ? 'mk-read' : ''}>{label}{readKeys.has(k) && <span className="mk-readtag">read from report</span>}
      <input type={type} value={obj[k] ?? ''} onChange={e => set({ ...obj, [k]: e.target.value })} /></label>)

  return <div className="card"><Explain id="market.quick" />
    <div className="row" style={{ paddingRight: 130, flexWrap: 'wrap' }}><h3 style={{ margin: 0 }}>⚡ Quick listing</h3><button className="btn small-btn" onClick={back}>← Other ways to sell</button></div>
    <ol className="mk-steps" style={{ marginTop: 10 }}>{['Drop your files', 'Check & complete', 'Preview & submit'].map((t, i) => {
      const at = pre ? 2 : v ? 1 : 0
      return <li key={t} className={i === at ? 'on' : i < at ? 'done' : ''}><button disabled>{i + 1}. {t}</button></li> })}</ol>
    {err && <div className="callout warn small">{err}</div>}
    {busy && <div className="callout small">{busy}</div>}

    {!v && <>
      <p className="small"><b>Guide:</b> drop the health report and up to 8 photos together (or pick them below). A PDF or Word file is taken as the report; images become the listing photos (the first one is the exterior, the second the label). If you only have a <i>photo</i> of the report, drop it first.</p>
      <div className={`drop mk-dropall${drag ? ' over' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); take(e.dataTransfer.files) }}>
        <b>Drop the report and photos here</b>
        <span className="small muted">Report: PDF, Word, or a photo of it (max 10 MB) · Photos: JPEG / PNG / WEBP (max 5 MB each)</span>
        <div className="row" style={{ flexWrap: 'wrap', justifyContent: 'center' }}>
          <label className="btn small-btn">Choose the report<input type="file" hidden accept={REPORT_TYPES} onChange={e => { e.target.files?.[0] && setReport(e.target.files[0]); e.target.value = '' }} /></label>
          <label className="btn small-btn">Add photos<input type="file" hidden multiple accept={PHOTO_TYPES} onChange={e => { const picked = [...e.target.files]; e.target.value = ''; setPhotos(p => [...p, ...picked].slice(0, 8)) }} /></label>
        </div>
      </div>
      <div className="mk-files small">
        <div><b>Report:</b> {report ? <>{report.name} <button className="link-btn" onClick={() => setReport(null)}>remove</button></> : <span className="muted">none yet (required)</span>}</div>
        <div><b>Photos ({photos.length}/8):</b> {photos.length ? photos.map((p, k) => <span key={k} className="tag">{['exterior', 'label'][k] || 'condition'}: {p.name} <button className="link-btn" onClick={() => setPhotos(photos.filter((_, j) => j !== k))}>✕</button></span>) : <span className="muted">none yet (recommended: exterior + label)</span>}</div>
      </div>
      <div className="callout warn small" style={{ marginTop: 10 }}><b>Safety:</b> do not open, dismantle or handle a high-voltage battery to take photos.</div>
      <p style={{ marginTop: 10 }}>{SAMPLE}</p>
      <button className="btn primary" disabled={!report || !!busy} onClick={read}>Read my files and fill the listing</button>
    </>}

    {v && !pre && <>
      <div className="callout small"><b>{Object.keys(ext).length} values were read from {v.report_file?.original_name}.</b> Fields marked <span className="mk-readtag">read from report</span> came from the document; check them. {v.report_file?.notes?.join(' ')} {v.photos.length} photo(s) attached.</div>
      {Object.keys(ext).length > 0 && <details className="howcalc"><summary>Show where each value came from</summary>
        <div className="small">{Object.entries(ext).map(([k, x]) => <div key={k}><b>{k.replaceAll('_', ' ')}:</b> {String(x.value)} <span className="muted">— “{x.snippet}”</span></div>)}</div></details>}
      <h4>Battery</h4>
      <div className="form">
        {['manufacturer', 'model', 'vehicle', 'chemistry', 'serial', 'age_years', 'rated_capacity_kwh', 'rated_voltage_v'].map(k => field(d, setD, k, READ_LABELS[k]))}
        <label className={readKeys.has('city') ? 'mk-read' : d.city ? '' : 'mk-need'}>City (required){readKeys.has('city') && <span className="mk-readtag">read from report</span>}
          <select value={d.city || ''} onChange={e => setD({ ...d, city: e.target.value })}><option value="">Choose…</option>{cities.map(c => <option key={c}>{c}</option>)}</select></label>
        <label className={readKeys.has('form') ? 'mk-read' : d.form ? '' : 'mk-need'}>Complete pack or module (required){readKeys.has('form') && <span className="mk-readtag">read from report</span>}
          <select value={d.form || ''} onChange={e => setD({ ...d, form: e.target.value })}><option value="">Choose…</option><option value="pack">Complete pack</option><option value="module">Individual module</option></select></label>
      </div>
      <h4>Health report</h4>
      <div className="form">{Object.keys(REP_LABELS).map(k => field(r, setR, k, REP_LABELS[k]))}</div>
      <h4>Price &amp; contact</h4>
      <div className="form">
        <label className={readKeys.has('price_inr') ? 'mk-read' : s.price_inr ? '' : 'mk-need'}>Asking price (₹, required){readKeys.has('price_inr') && <span className="mk-readtag">read from report</span>}<input type="number" value={s.price_inr} onChange={e => setS({ ...s, price_inr: e.target.value })} />
          {r.measured_capacity_kwh && <span className="small muted">Guide: about {inr(Math.round(r.measured_capacity_kwh * 4000 / 500) * 500)}–{inr(Math.round(r.measured_capacity_kwh * 9000 / 500) * 500)} for {r.measured_capacity_kwh} kWh remaining</span>}</label>
        <label className={readKeys.has('negotiable') ? 'mk-read' : ''}>Price negotiable{readKeys.has('negotiable') && <span className="mk-readtag">read from report</span>}<select value={String(s.negotiable)} onChange={e => setS({ ...s, negotiable: e.target.value === 'true' })}><option value="true">Yes</option><option value="false">No</option></select></label>
        {field(s, setS, 'condition', 'Condition')}
        {field(s, setS, 'known_faults', 'Known faults')}
        <label className={readKeys.has('contact_method') ? 'mk-read' : ''}>Preferred contact{readKeys.has('contact_method') && <span className="mk-readtag">read from report</span>}<select value={s.contact_method} onChange={e => setS({ ...s, contact_method: e.target.value })}><option value="phone">Phone</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option></select></label>
        <label className={readKeys.has('contact_value') ? 'mk-read' : s.contact_value ? '' : 'mk-need'}>Your contact (private until you accept a buyer){readKeys.has('contact_value') && <span className="mk-readtag">read from report</span>}<input value={s.contact_value} onChange={e => setS({ ...s, contact_value: e.target.value })} /></label>
      </div>
      <label className="small" style={{ display: 'block', marginTop: 10 }}><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} /> I confirm the information is accurate and I have disclosed all known faults. I understand a sale is not guaranteed.</label>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={!!busy || missing.length > 0} onClick={preview}>Preview the listing</button>
        {missing.length > 0 && <span className="small muted">Still needed: {missing.join(', ')}.</span>}
      </div>
    </>}

    {pre && <>
      {!pre.submitted && <button className="btn small-btn" style={{ marginBottom: 8 }} onClick={() => setPre(null)}>← Back to edit</button>}
      <PreviewStep pre={pre} draft={draft} agree={agree} busy={!!busy} run={async fn => { setBusy('Submitting…'); try { await fn() } catch (e) { setErr(String(e.message || e)) } finally { setBusy(null) } }}
        done={x => { setPre({ ...x, submitted: true }); onDone?.() }} />
    </>}
  </div>
}

function useFields(init) {
  const [s, setS] = useState(init)
  const bind = (k, type = 'text') => ({
    value: s[k] === 'not_available' ? '' : s[k] ?? '', disabled: s[k] === 'not_available', type,
    onChange: e => setS({ ...s, [k]: e.target.value }),
  })
  const na = k => <label className="mk-na"><input type="checkbox" checked={s[k] === 'not_available'} onChange={e => setS({ ...s, [k]: e.target.checked ? 'not_available' : '' })} /> Not available</label>
  return [s, setS, bind, na]
}

function DetailsStep({ v, cities, save, busy }) {
  const [s, setS, bind, na] = useFields(v.details)
  return <>
    <h4>A · Battery details</h4>
    <div className="form">
      <label>Manufacturer{na('manufacturer')}<input {...bind('manufacturer')} /></label>
      <label>Model{na('model')}<input {...bind('model')} /></label>
      <label>Chemistry{na('chemistry')}<select value={s.chemistry === 'not_available' ? '' : s.chemistry || ''} disabled={s.chemistry === 'not_available'} onChange={e => setS({ ...s, chemistry: e.target.value })}><option value="">Choose…</option>{['LFP', 'NMC', 'NCA', 'LMO', 'LCO', 'LTO'].map(c => <option key={c}>{c}</option>)}</select></label>
      <label>Original vehicle (make and model){na('vehicle')}<input {...bind('vehicle')} /></label>
      <label>Approximate age (years){na('age_years')}<input {...bind('age_years', 'number')} /></label>
      <label>Usage history{na('usage_history')}<input {...bind('usage_history')} placeholder="e.g. city commuting, ~30 km/day" /></label>
      <label>Battery serial number / identifier{na('serial')}<input {...bind('serial')} /></label>
      <label>Rated capacity (kWh){na('rated_capacity_kwh')}<input {...bind('rated_capacity_kwh', 'number')} /></label>
      <label>Rated voltage (V){na('rated_voltage_v')}<input {...bind('rated_voltage_v', 'number')} /></label>
      <label>City (where the battery is)<select value={s.city || ''} onChange={e => setS({ ...s, city: e.target.value })}><option value="">Choose…</option>{cities.map(c => <option key={c}>{c}</option>)}</select></label>
      <label>Complete pack or module<select value={s.form || ''} onChange={e => setS({ ...s, form: e.target.value })}><option value="">Choose…</option><option value="pack">Complete pack</option><option value="module">Individual module</option></select></label>
      <label>Reason for selling (optional)<input {...bind('reason')} /></label>
    </div>
    <button className="btn primary" style={{ marginTop: 12 }} disabled={busy || !s.city || !s.form} onClick={() => save(s)}>Save and continue</button>
    {(!s.city || !s.form) && <span className="small muted"> City and pack/module are needed.</span>}
  </>
}

function ReportStep({ v, draft, setV, run, busy, noReport, setNoReport, partners, save }) {
  const [s, setS, bind, na] = useFields(v.report)
  useEffect(() => { setS(v.report) }, [v.report])
  const upload = file => run(async () => setV(await api(`/api/listings/${draft.id}/report`, { token: draft.token, filename: file.name, content_b64: await toB64(file) })))
  const ext = v.extracted || {}
  return <>
    <h4>B · Battery health / testing report (required)</h4>
    {!noReport && <>
      <div className="drop"><b>Upload the report</b><span className="small muted">PDF, photo of the report (JPEG / PNG / WEBP) or Word document · max 10 MB</span>
        <input type="file" onChange={e => e.target.files?.[0] && upload(e.target.files[0])} disabled={busy} /></div>
      {busy && <p className="small muted">Reading the report… (photos are read with OCR and can take a few seconds)</p>}
      {v.report_file && <div className="callout small" style={{ marginTop: 10 }}>Uploaded <b>{v.report_file.original_name}</b> ({v.report_file.kind.toUpperCase()}). {(v.report_file.notes || []).join(' ')}
        {' '}{Object.keys(ext).length ? `${Object.keys(ext).length} fields were read automatically — check and correct them below.` : 'No fields could be read automatically — please type them.'}</div>}
      {Object.keys(ext).length > 0 && <details className="howcalc" open><summary>What was read from the document</summary>
        <div className="small">{Object.entries(ext).map(([k, x]) => <div key={k}><b>{k.replaceAll('_', ' ')}:</b> {String(x.value)} <span className="muted">— “{x.snippet}”</span></div>)}</div></details>}
      <div className="form" style={{ marginTop: 10 }}>
        <label>Testing shop / provider{na('provider')}<input {...bind('provider')} /></label>
        <label>Report ID{na('report_id')}<input {...bind('report_id')} /></label>
        <label>Test date (YYYY-MM-DD){na('test_date')}<input {...bind('test_date')} /></label>
        <label>Reported State of Health (%){na('soh_pct')}<input {...bind('soh_pct', 'number')} /></label>
        <label>Measured capacity (kWh){na('measured_capacity_kwh')}<input {...bind('measured_capacity_kwh', 'number')} /></label>
        <label>Internal resistance (mΩ){na('internal_resistance_mohm')}<input {...bind('internal_resistance_mohm', 'number')} /></label>
        <label>Other diagnostic measurements{na('other_measurements')}<input {...bind('other_measurements')} /></label>
        <label>Tests performed{na('tests_performed')}<input {...bind('tests_performed')} placeholder="e.g. capacity test, DCIR, insulation" /></label>
        <label>Known limitations of the test{na('limitations')}<input {...bind('limitations')} /></label>
        <label>Issuer details / verification reference{na('issuer_reference')}<input {...bind('issuer_reference')} /></label>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={busy || !v.report_file} onClick={() => save(s)}>Save and continue</button>
        <button className="btn small-btn" onClick={() => setNoReport(true)}>I don't have a report</button>
      </div>
    </>}
    {noReport && <div className="callout warn">
      <b>A report is needed before the battery can be listed.</b> Book a health test with a registered testing partner; once they have tested it,
      come back and upload their report. A listing without a report is never shown as verified.
      <ul className="small">{partners.map(p => <li key={p.id}>{p.name}</li>)}</ul>
      <p className="small muted">These partner entries are demo placeholders for this prototype.</p>
      <button className="btn small-btn" onClick={() => setNoReport(false)}>I have a report now</button>
    </div>}
  </>
}

function SaleStep({ v, agree, setAgree, save, busy }) {
  const [s, setS] = useState({ negotiable: false, inspection_allowed: true, contact_method: 'phone', ...v.sale })
  const b = k => ({ value: s[k] ?? '', onChange: e => setS({ ...s, [k]: e.target.value }) })
  return <>
    <h4>D · Price and sale essentials</h4>
    <div className="form">
      <label>Asking price (₹)<input type="number" {...b('price_inr')} /></label>
      <label>Price negotiable<select value={String(!!s.negotiable)} onChange={e => setS({ ...s, negotiable: e.target.value === 'true' })}><option value="false">No</option><option value="true">Yes</option></select></label>
      <label>Battery condition<input {...b('condition')} placeholder="e.g. no visible damage, kept indoors" /></label>
      <label>Known faults (please disclose)<input {...b('known_faults')} placeholder="write 'none known' if none" /></label>
      <label>Warranty / refurbishment, if any<input {...b('warranty')} placeholder="leave empty if none" /></label>
      <label>Inspection allowed before purchase<select value={String(!!s.inspection_allowed)} onChange={e => setS({ ...s, inspection_allowed: e.target.value === 'true' })}><option value="true">Yes</option><option value="false">No</option></select></label>
      <label>Transport (through an appropriate provider)<input {...b('transport')} placeholder="e.g. can arrange a licensed hazmat courier" /></label>
      <label>Preferred contact method<select value={s.contact_method} onChange={e => setS({ ...s, contact_method: e.target.value })}><option value="phone">Phone</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option></select></label>
      <label>Your contact (kept private until you accept a buyer)<input {...b('contact_value')} /></label>
    </div>
    <label className="small" style={{ display: 'block', marginTop: 10 }}><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} /> I confirm the information is accurate and I have disclosed all known faults. I understand a sale is not guaranteed.</label>
    <button className="btn primary" style={{ marginTop: 12 }} disabled={busy || !agree || !s.price_inr || !s.contact_value} onClick={() => save(s)}>Save and continue</button>
  </>
}

function PhotoStep({ v, draft, setV, run, busy, next }) {
  const [kind, setKind] = useState('exterior')
  const add = file => run(async () => setV(await api(`/api/listings/${draft.id}/photos`, { token: draft.token, filename: file.name, content_b64: await toB64(file), kind })))
  const del = n => run(async () => setV(await fetch(`/api/listings/${draft.id}/photos/${n}?token=${encodeURIComponent(draft.token)}`, { method: 'DELETE' }).then(r => r.json())))
  return <>
    <h4>E · Photos</h4>
    <div className="callout warn small"><b>Safety:</b> do not open, dismantle or handle a high-voltage battery to take photos. Existing photos and documents are fine.</div>
    <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
      <select className="btn" value={kind} onChange={e => setKind(e.target.value)}><option value="exterior">Exterior</option><option value="label">Label / identifier</option><option value="connector">Connector / specification</option><option value="condition">Other condition photo</option></select>
      <input type="file" accept={PHOTO_TYPES} disabled={busy || v.photos.length >= 8} onChange={e => { e.target.files?.[0] && add(e.target.files[0]); e.target.value = '' }} />
      <span className="small muted">JPEG / PNG / WEBP, max 5 MB, up to 8 photos</span>
    </div>
    <div className="mk-photos" style={{ marginTop: 10 }}>{v.photos.map(p => <figure key={p.n}><img src={`/api/listings/${draft.id}/photos/${p.n}?token=${encodeURIComponent(draft.token)}`} alt={`${p.kind} photo`} /><figcaption className="small">{p.kind} · <button className="link-btn" onClick={() => del(p.n)}>remove</button></figcaption></figure>)}</div>
    <button className="btn primary" style={{ marginTop: 12 }} disabled={busy} onClick={next}>Preview the listing</button>
  </>
}

function PreviewStep({ pre, draft, agree, busy, run, done }) {
  if (pre.submitted) return <>
    <h4>Submitted</h4>
    <div className="row" style={{ flexWrap: 'wrap' }}><VerifBadge v={pre.verification} label={pre.verification_label} /><span className="tag">{pre.status_label}</span></div>
    <NextSteps v={pre} />
    <Checks list={pre.checks} />
  </>
  return <>
    <h4>F · Preview</h4>
    <p className="small">This is what buyers will see. Status after submitting: <VerifBadge v={pre.would_be.verification} label={pre.would_be.verification_label} /></p>
    <div className="grid g2"><div><h4>Battery</h4><Specs d={pre.details} /></div><div><h4>Report</h4><ReportFields r={pre.report} />
      {pre.report_file && <p className="small"><a href={`/api/listings/${pre.id}/report-file?token=${encodeURIComponent(draft.token)}`} target="_blank" rel="noopener noreferrer">Open uploaded report</a></p>}</div></div>
    <p className="small"><b>Asking price:</b> {inr(pre.sale.price_inr)}{pre.sale.negotiable ? ' (negotiable)' : ''} · <b>Photos:</b> {pre.photos.length}</p>
    {pre.missing.length > 0 && <p className="small">Marked not available: {pre.missing.join(', ').replaceAll('_', ' ')}.</p>}
    <h4>Checks</h4><Checks list={pre.checks} />
    <div className="row" style={{ marginTop: 12 }}>
      <button className="btn primary" disabled={busy || !agree} onClick={() => run(async () => done(await api(`/api/listings/${draft.id}/submit`, { token: draft.token })))}>Submit listing</button>
      <span className="small muted">You can go back to any step to edit.</span>
    </div>
  </>
}

function NextSteps({ v }) {
  const t = {
    awaiting_provider: 'Your report names a registered testing partner. They will be asked to confirm the report ID and SoH; until then buyers see "Awaiting provider verification".',
    report_uploaded: 'Buyers see your listing as "Report uploaded — not yet verified". To get it verified, have the battery tested by a registered testing partner and upload their report.',
    more_testing: 'Your report is older than the policy allows, so buyers see "Additional testing required". A new test will let it be verified.',
    mismatch: 'Something in the report does not match the listing (see the checks below). The listing is not shown to buyers until it is corrected.',
    held: 'The listing is held for review because its report or battery ID also appears on another listing. It is not shown to buyers meanwhile.',
    verified: 'Verified by a registered testing partner.',
  }[v.verification]
  return <div className="callout small" style={{ margin: '8px 0' }}><b>Next steps:</b> {t} Track interest and status under <b>My listings &amp; interests</b>.</div>
}

/* ================================================================== my listings (seller) + my interests (buyer) */
export function Mine() {
  const [L, setL] = useState(null)
  const [I, setI] = useState(null)
  const [demo, setDemo] = useState(() => { try { return JSON.parse(localStorage.getItem(DEMO_KEY) || 'null') } catch { return null } })
  const [demoErr, setDemoErr] = useState(null)
  const loadDemo = () => api('/api/listings/demo/accounts').then(a => {
    sellerKeys.putAll(a.seller.keys); buyerKeys.putAll(a.buyer.keys)
    const who = { seller: `${a.seller.name} (${a.seller.about})`, buyer: `${a.buyer.name} (${a.buyer.about})` }
    try { localStorage.setItem(DEMO_KEY, JSON.stringify(who)) } catch { /* storage unavailable */ }
    setDemo(who); setDemoErr(null); load()
  }).catch(e => setDemoErr(String(e.message || e)))
  const load = () => {
    api('/api/listings/mine', { tokens: Object.values(sellerKeys.get()) }).then(setL).catch(() => setL([]))
    api('/api/listings/interests/mine', { tokens: Object.values(buyerKeys.get()) }).then(setI).catch(() => setI([]))
  }
  useEffect(load, [])
  const tok = id => sellerKeys.get()[id]
  const act = (path, body) => api(path, body).then(load)
  return <>
    <div className="callout small" style={{ marginBottom: 14 }}>
      {demo ? <>Viewing as the demo personas <b>{demo.seller}</b> (seller) and <b>{demo.buyer}</b> (buyer), plus anything you listed or contacted from this browser.</>
        : <>Your listings and requests are remembered in this browser. To try the seller and buyer side with sample data, open the demo accounts (fictional people).</>}
      {' '}<button className="btn small-btn primary" onClick={loadDemo}>{demo ? 'Reload demo accounts' : 'Open demo accounts'}</button>
      {demoErr && <div className="small" style={{ marginTop: 6 }}>{demoErr}</div>}
    </div>
    <div className="grid g2">
    <div className="card"><Explain id="market.mine" /><h3>My listings (as seller)</h3>
      {L === null && <p className="muted small">Loading…</p>}
      {L?.length === 0 && <p className="muted small">No listings from this browser yet.</p>}
      {L?.map(l => (
        <div key={l.id} className="mk-mine">
          <div className="row spread"><b className="mono">{l.id}</b><span className="mono">{inr(l.sale.price_inr)}</span></div>
          <div className="small">{[l.details.manufacturer, l.details.model].filter(Boolean).join(' ') || 'Battery'} · {show(l.details.city)}</div>
          <div className="row" style={{ flexWrap: 'wrap', margin: '6px 0' }}><VerifBadge v={l.verification} label={l.verification_label} /><span className="tag">{l.status_label}</span></div>
          {l.checks.filter(c => c.level !== 'info').length > 0 && <details className="howcalc"><summary>{l.checks.filter(c => c.level !== 'info').length} item(s) to resolve</summary><Checks list={l.checks.filter(c => c.level !== 'info')} /></details>}
          {l.interests?.length > 0 && <div className="small" style={{ marginTop: 6 }}><b>Buyer interest</b>{l.interests.map(i => (
            <div key={i.id} className="mk-interest"><span>{i.name}: “{i.message || '—'}” · <i>{i.status}</i>{i.contact ? ` · contact: ${i.contact}` : ''}</span>
              {i.status === 'pending' && !['sold', 'withdrawn'].includes(l.status) && <span className="row"><button className="btn small-btn primary" onClick={() => act(`/api/listings/${l.id}/interests/${i.id}/accept`, { token: tok(l.id) })}>Accept & share contacts</button>
                <button className="btn small-btn" onClick={() => act(`/api/listings/${l.id}/interests/${i.id}/decline`, { token: tok(l.id) })}>Decline</button></span>}</div>))}</div>}
          <div className="row" style={{ marginTop: 6, flexWrap: 'wrap' }}>
            {!['sold', 'withdrawn', 'draft'].includes(l.status) && <button className="btn small-btn" onClick={() => act(`/api/listings/${l.id}/status`, { token: tok(l.id), status: 'sold' })}>Mark sold</button>}
            {!['withdrawn', 'draft'].includes(l.status) && <button className="btn small-btn" onClick={() => act(`/api/listings/${l.id}/status`, { token: tok(l.id), status: 'withdrawn' })}>Withdraw</button>}
          </div>
          <details className="howcalc"><summary>History</summary><div className="small">{(l.history || []).map((h, k) => <div key={k}>{h.at} — {h.event}</div>)}</div></details>
        </div>))}
    </div>
    <div className="card"><h3>My interests (as buyer)</h3>
      {I === null && <p className="muted small">Loading…</p>}
      {I?.length === 0 && <p className="muted small">You have not contacted any seller from this browser.</p>}
      {I?.map(i => <div key={i.id} className="mk-mine small"><b>{i.battery}</b> · listing {i.listing_id} · {i.listing_status}<br />Your request: <i>{i.status}</i>
        {i.seller_contact && <div className="callout small" style={{ marginTop: 6 }}>Seller contact ({i.seller_contact.method}): <b>{i.seller_contact.value}</b>. Arrange an inspection by a qualified professional before paying.</div>}</div>)}
    </div>
  </div>
  </>
}

/* ================================================================== testing partners (demo verification) */
export function Partners() {
  const [p, setP] = useState(null)
  const [f, setF] = useState({ listing: '', partner_code: '', report_id: '', measured_soh_pct: '' })
  const [out, setOut] = useState(null)
  const [q, setQ] = useState(null)
  const loadQ = () => api('/api/listings/partners/queue').then(r => setQ(r.queue)).catch(() => setQ([]))
  useEffect(() => { api('/api/listings/partners/list').then(setP).catch(() => {}); loadQ() }, [])
  useEffect(() => { if (out && !out.error) loadQ() }, [out])
  const pick = x => { setOut(null); setF({ listing: x.id, partner_code: p?.demo_codes?.[x.provider] || '', report_id: x.report_id || '', measured_soh_pct: x.soh_pct ?? '' }) }
  const go = () => api(`/api/listings/${f.listing.trim()}/partner-confirm`, { partner_code: f.partner_code, report_id: f.report_id, measured_soh_pct: Number(f.measured_soh_pct) })
    .then(setOut).catch(e => setOut({ error: String(e.message || e) }))
  return <div className="card"><Explain id="market.partners" />
    <h3>Testing-partner confirmation (demo)</h3>
    <p className="small">Only a registered testing partner can move a listing to <b>Verification completed</b>, by confirming the report ID and the SoH they measured. In production this is an authenticated partner API; here it is a demo form with partner codes from <code>registry/testing_partners.json</code>.</p>
    {p && <p className="small muted">Registered (demo) partners: {p.partners.map(x => `${x.name}${p.demo_codes?.[x.name] ? ` — code ${p.demo_codes[x.name]}` : ''}`).join(' · ')}</p>}
    <h4>Waiting for a partner re-test ({q ? q.length : '…'})</h4>
    {q?.length === 0 && <p className="small muted">No listing is waiting for a registered partner.</p>}
    {q?.length > 0 && <div style={{ maxHeight: 280, overflow: 'auto', marginBottom: 12 }}><table className="small"><thead><tr><th>Listing</th><th>Battery</th><th>City</th><th>Partner named in report</th><th>Report ID</th><th>Reported SoH</th><th></th></tr></thead>
      <tbody>{q.map(x => <tr key={x.id}><td className="mono">{x.id}</td><td>{x.battery}{x.demo ? ' (demo)' : ''}</td><td>{x.city}</td><td>{x.provider}</td><td className="mono">{x.report_id}</td><td>{x.soh_pct}%</td>
        <td><button className="btn small-btn" onClick={() => pick(x)}>Re-test this one</button></td></tr>)}</tbody></table></div>}
    <p className="small muted">"Re-test this one" fills the form as if the partner measured the same SoH; change the measured SoH by more than 1 point to see a mismatch.</p>
    <div className="form">
      <label>Listing ID<input value={f.listing} onChange={e => setF({ ...f, listing: e.target.value })} placeholder="L-…" /></label>
      <label>Partner code<input value={f.partner_code} onChange={e => setF({ ...f, partner_code: e.target.value })} /></label>
      <label>Report ID (partner's record)<input value={f.report_id} onChange={e => setF({ ...f, report_id: e.target.value })} /></label>
      <label>SoH the partner measured (%)<input type="number" value={f.measured_soh_pct} onChange={e => setF({ ...f, measured_soh_pct: e.target.value })} /></label>
    </div>
    <button className="btn primary" style={{ marginTop: 10 }} onClick={go}>Confirm report</button>
    {out && (out.error ? <div className="callout warn small">{out.error}</div> : <div className="callout small"><VerifBadge v={out.verification} label={out.label} /> {out.reason}</div>)}
  </div>
}

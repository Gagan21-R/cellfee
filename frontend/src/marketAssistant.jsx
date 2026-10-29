// Marketplace assistant: a rule-based chat over the live listings (/api/listings) plus the CELLFEE guide's
// marketplace entries. It parses filters (chemistry, city, price, SoH, capacity, age, pack/module, vehicle, make,
// use case, verified) and an ordering from plain words; it is not a general AI and says so.
import { Fragment, useEffect, useRef, useState } from 'react'
import { Explain } from './Assistant.jsx'
import { ListingDetail, NA, show } from './marketplace.jsx'
import { inr } from './usageFormat.js'

const CHEMS = ['lfp', 'nmc', 'nca', 'lmo', 'lco', 'lto']
// words a buyer uses -> words found in listings' vehicle / model names (Indian EV models included)
const VEHICLES = {
  scooter: [['scooter', 'two-wheeler', 'two wheeler', '2-wheeler', 'bike'], ['scooter', 'ather', 'ola s1', 'iqube', 'chetak', 'optima', 'yulu']],
  car: [['car', 'suv', 'hatchback', 'sedan'], ['nexon', 'tigor', 'zs ev', 'everito', ' car']],
  bus: [['bus'], ['bus']],
  rickshaw: [['rickshaw', 'three-wheeler', 'three wheeler', '3-wheeler', 'auto'], ['treo', 'ape', 'rickshaw', 'three-wheeler']],
  cargo: [['cargo', 'delivery', 'truck', 'van'], ['hiload', 'cargo', 'delivery', 'truck', 'van']],
}
const CHIPS = ['Cheapest LFP battery', 'Verified batteries under 1 lakh', 'Best health in Bengaluru', 'How many listings are there?',
  'How do I sell my battery?', 'What does awaiting provider mean?']
const lower = s => String(s ?? '').toLowerCase()
const UNIT = { lakh: 1e5, lakhs: 1e5, lac: 1e5, l: 1e5, k: 1e3, thousand: 1e3, cr: 1e7, crore: 1e7 }
const soh = l => Number(l.report.soh_pct) || 0
const cap = l => Number(l.report.measured_capacity_kwh ?? l.details.rated_capacity_kwh) || 0

/** Reads a question about the listings. Returns {text, items?}, or null when it is a how/why question for the guide. */
export function marketQuery(question, data) {
  const q = ` ${lower(question).replace(/[,?!"']/g, ' ').replace(/₹/g, ' rs ')} `
  const L = data.listings
  const id = q.match(/\bl-\d{6}-[0-9a-f]{6}\b/)
  if (id) {
    const l = L.find(x => lower(x.id) === id[0])
    return l ? { text: `Listing **${l.id}**:`, items: [l] }
      : { text: `I can't find ${id[0].toUpperCase()} among the listed batteries (it may be a draft, sold, or hidden for review).` }
  }
  const crit = [], keep = []
  const add = (label, fn) => { crit.push(label); keep.push(fn) }
  const chem = CHEMS.find(c => q.includes(` ${c} `) || (c === 'lfp' && q.includes('lifepo4')))
  if (chem) add(chem.toUpperCase(), l => lower(l.details.chemistry) === chem)
  const city = data.cities.find(c => q.includes(lower(c)) || (c === 'Bengaluru' && q.includes('bangalore')) || (c === 'Mumbai' && q.includes('bombay')))
  if (city) add(`in ${city}`, l => l.details.city === city)
  if (/\b(un ?verified|not verified)\b/.test(q)) add('not yet verified', l => l.verification !== 'verified')
  else if (/\b(verified|confirmed|certified)\b/.test(q)) add('partner-verified', l => l.verification === 'verified')
  if (/\bmodules?\b/.test(q)) add('modules', l => l.details.form === 'module')
  else if (/\b(packs?|complete)\b/.test(q)) add('complete packs', l => l.details.form === 'pack')
  for (const [k, [asked, found]] of Object.entries(VEHICLES)) {
    if (asked.some(w => q.includes(` ${w}`))) add(`from a ${k}`, l => found.some(w => ` ${lower(`${l.details.vehicle} ${l.details.model}`)}`.includes(w)))
  }
  const makes = [...new Set(L.flatMap(l => lower(l.details.manufacturer).split(/\s+/)))].filter(w => w.length >= 3 && w !== NA)
  const make = makes.find(m => q.includes(` ${m} `))
  if (make) add(make[0].toUpperCase() + make.slice(1), l => lower(`${l.details.manufacturer} ${l.details.model}`).includes(make))
  const use = data.uses.find(u => q.includes(` ${lower(u.id)} `) || lower(u.name).split(/[^a-z]+/).some(w => w.length > 4 && q.includes(` ${w}`)))
  if (use) add(`suitable for ${use.name}`, l => l.uses.some(u => u.id === use.id))

  // numbers: "under 1 lakh", "above 85%", "at least 10 kwh", "under 4 years"
  const re = /(under|below|less than|cheaper than|within|up ?to|max(?:imum)?|above|over|more than|at least|min(?:imum)?)?\s*(?:rs\.?\s*|inr\s*)?(\d+(?:\.\d+)?)\s*(lakhs?|lac|crore|cr|thousand|k|l)?\b\s*(%|percent|soh|kwh|years?|yrs?)?/g
  for (const [, op, num, unit, kind0] of q.matchAll(re)) {
    const kind = kind0 || ''
    if (!op && !kind) continue
    const atLeast = !op || /above|over|more|least|min/.test(op)
    const v = Number(num)
    if (/%|percent|soh/.test(kind)) add(`SoH ${atLeast ? '≥' : '≤'} ${v}%`, l => (atLeast ? soh(l) >= v : soh(l) <= v))
    else if (kind === 'kwh') add(`${atLeast ? '≥' : '≤'} ${v} kWh`, l => (atLeast ? cap(l) >= v : cap(l) <= v))
    else if (/^y/.test(kind)) {
      const age = l => Number(l.details.age_years)
      add(`${atLeast && op ? '≥' : '≤'} ${v} years old`, l => Number.isFinite(age(l)) && (atLeast && op ? age(l) >= v : age(l) <= v))
    } else if (op) {
      const p = v * (UNIT[unit] || 1)
      if (p >= 1000) add(`${atLeast ? 'over' : 'under'} ${inr(p)}`, l => (atLeast ? l.sale.price_inr >= p : l.sale.price_inr <= p))
    }
  }

  const counting = /\bhow many\b|\bcount\b|\bnumber of\b/.test(q)
  const help = /\b(how|what|why|mean|means|explain|can i|should|when|who)\b/.test(q) && !counting && !/\b(which|show|find|list)\b/.test(q)
  if (help && !crit.length) return null
  let M = L.filter(l => keep.every(g => g(l)))
  if (counting) {
    const by = M.reduce((a, l) => ({ ...a, [l.verification_label]: (a[l.verification_label] || 0) + 1 }), {})
    return { text: `**${M.length}** batter${M.length === 1 ? 'y is' : 'ies are'} listed${crit.length ? ` (${crit.join(', ')})` : ''}.\n${Object.entries(by).map(([k, n]) => `• ${k}: ${n}`).join('\n')}` }
  }
  const searching = crit.length || /\b(cheap\w*|lowest|expensive|costliest|best|healthiest|highest|biggest|largest|newest|latest|show|find|list|any|which|available|batter(y|ies)|packs?)\b/.test(q)
  if (!searching) return null
  let order = 'best evidence first'
  const sortBy = (fn, label) => { M = [...M].sort(fn); order = label }
  if (/cheap|lowest price|low price|budget|affordable/.test(q)) sortBy((a, b) => a.sale.price_inr - b.sale.price_inr, 'cheapest first')
  else if (/expensive|costliest|highest price|premium/.test(q)) sortBy((a, b) => b.sale.price_inr - a.sale.price_inr, 'most expensive first')
  else if (/best|healthiest|highest soh|health/.test(q)) sortBy((a, b) => soh(b) - soh(a), 'highest SoH first')
  else if (/biggest|largest|most capacity|most energy|highest capacity/.test(q)) sortBy((a, b) => cap(b) - cap(a), 'largest capacity first')
  else if (/newest|latest|recent/.test(q)) sortBy((a, b) => b.created.localeCompare(a.created), 'newest first')
  if (!M.length) return { text: `No listed battery matches ${crit.join(', ') || 'that'}. Try removing a condition, for example the city or the price limit.` }
  const perKwh = M.map(l => l.sale.price_inr / cap(l)).filter(Number.isFinite).sort((a, b) => a - b)
  const typical = perKwh.length > 1 ? ` Their median price is about ${inr(Math.round(perKwh[Math.floor(perKwh.length / 2)] / 100) * 100)} per kWh.` : ''
  return { text: `Found **${M.length}** batter${M.length === 1 ? 'y' : 'ies'}${crit.length ? ` (${crit.join(', ')})` : ''}, ${order}${M.length > 5 ? '; here are the top 5' : ''}.${typical}`, items: M.slice(0, 5) }
}

const bold = s => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith('**') ? <b key={i}>{p.slice(2, -2)}</b> : <Fragment key={i}>{p}</Fragment>))

export function MarketAssistant({ R, KB, answer }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [msgs, setMsgs] = useState([])
  const [draft, setDraft] = useState('')
  const [view, setView] = useState(null)
  const listRef = useRef(null)
  useEffect(() => {
    if (open && !data) fetch('/api/listings').then(r => r.json()).then(setData).catch(() => setData({ listings: [], cities: [], uses: [] }))
  }, [open, data])
  useEffect(() => { if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight }, [msgs])
  const ask = text => {
    const q = text.trim()
    if (!q || !data) return
    let a = marketQuery(q, data)
    if (!a) {
      const hit = answer(KB, q, R)
      a = hit ? { title: hit.title, text: hit.text }
        : { text: 'I answer questions about the listed batteries (try "cheapest LFP in Pune" or "verified packs over 20 kWh") and about how buying and selling work here. I could not match that one.' }
    }
    setMsgs(m => [...m, { who: 'user', text: q }, { who: 'bot', ...a }])
    setDraft('')
  }
  return (
    <div className="card mk-assist" style={{ marginBottom: 16 }}>
      <Explain id="market.assistant" />
      <div className="row" style={{ flexWrap: 'wrap', paddingRight: 120 }}>
        <h3 style={{ margin: 0 }}>💬 Marketplace assistant</h3>
        <span className="small muted">Ask about the batteries for sale, or how buying and selling work.</span>
        {!open && <button className="btn small-btn primary" onClick={() => setOpen(true)}>Ask a question</button>}
      </div>
      {open && <>
        <div className="mk-assist-list" ref={listRef} aria-live="polite">
          {msgs.length === 0 && <div className="bubble bot"><p>Hi! I can search the <b>{data ? data.listings.length : '…'} listed batteries</b> for you and explain how the marketplace works. Try a suggestion below or type your own question.</p></div>}
          {msgs.map((m, i) => (
            <div key={i} className={`bubble ${m.who}`}>
              {m.title && <b className="bubble-title">{m.title}</b>}
              {m.text.split('\n').filter(Boolean).map((line, j) => <p key={j}>{bold(line)}</p>)}
              {m.items?.map(l => (
                <div key={l.id} className="mk-interest">
                  <span><b>{[l.details.manufacturer, l.details.model].filter(x => x && x !== NA).join(' ') || 'Battery'}</b> · {inr(l.sale.price_inr)} · SoH {show(l.report.soh_pct)}% · {show(l.report.measured_capacity_kwh ?? l.details.rated_capacity_kwh)} kWh · {show(l.details.city)} · {l.verification_label}{l.demo ? ' · demo listing' : ''}</span>
                  <button className="btn small-btn" onClick={() => setView(l.id)}>View</button>
                </div>))}
            </div>))}
        </div>
        <div className="guide-chips" style={{ padding: 0, border: 0 }}>{CHIPS.map(s => <button key={s} type="button" className="chip-btn" onClick={() => ask(s)} disabled={!data}>{s}</button>)}</div>
        <form onSubmit={e => { e.preventDefault(); ask(draft) }}>
          <input value={draft} onChange={e => setDraft(e.target.value)} placeholder='e.g. "NMC packs in Delhi under 2 lakh"' aria-label="Ask the marketplace assistant" />
          <button className="btn primary" disabled={!draft.trim() || !data}>Ask</button>
          <button type="button" className="btn small-btn" onClick={() => setOpen(false)}>Hide</button>
        </form>
        <span className="small muted">Rule-based search over this marketplace's live listings and guide, not a general AI. Check every listing yourself before buying.</span>
      </>}
      {view && <ListingDetail id={view} close={() => setView(null)} />}
    </div>
  )
}

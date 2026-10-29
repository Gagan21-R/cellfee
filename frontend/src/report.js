// Plain-language reports + PDF / JSON downloads.
// Every report is first turned into short everyday sentences (no jargon, few numbers), and both the
// PDF and the JSON are built from that same plain version, so the two downloads always agree.

const ACTION = { reuse: 'Reuse', test: 'Test first', recycle: 'Recycle' }
const GRADE = {
  A: 'Very good: both models are confident it has a long life ahead',
  B: 'Good: both models expect a long life ahead',
  T: 'Unclear: the models disagree or are unsure, so it needs a lab test before deciding',
  C: 'Near the end of its useful life: recycling route',
}
const NOTE = 'This is an early screening result, not a safety certificate. A qualified technician should inspect the battery before it is reused.'
const pct = v => Math.round(v * 100)
const today = () => new Date().toISOString().slice(0, 10)
const LONG = 300   // cycles: what "a long life ahead" means in every report
const SAFETY = 'Decision support from stored test data. Not a safety certification.'

/** Usage baseline + confidence in everyday words (same stored numbers as the screen). */
function usagePlain(u) {
  const best = u.applications.find(a => a.id === u.best)
  const usable = u.applications.filter(a => a.confidence != null)
  const stop = best ? best.stop : null
  return {
    state: u.state,
    risk_level: u.risk.level,
    pathway: u.pathway.label,
    stop_using_after: best
      ? (stop.p10 === 0 ? `Stop using it now for ${best.name}: it is at or below that use's health floor.`
        : `For ${best.name}, stop using it after about ${stop.p10.toLocaleString()} more full cycles (${stop.months_p10 > 120 ? 'over 10 years at that pace, but calendar ageing is not modelled' : `about ${stop.months_p10} months at that use's pace`}). A typical battery like it lasts about ${stop.p50.toLocaleString()} cycles.`)
      : 'Do not reuse this battery.',
    ...(stop && stop.restricted_cap != null ? { until_tested: `Until a full test confirms it, use it for at most ${stop.restricted_cap} cycles, at low power, in low-risk uses only.` } : {}),
    can_be_used_for: usable.map(a => ({ application: a.name, confidence_percent: a.confidence >= 99.5 ? '>99' : Math.round(a.confidence),
      stop_after_cycles: a.stop.p10, ...(a.low_confidence ? { advice: 'Low confidence: run a full test first.' } : {}),
      ...(a.status === 'conditional on test' ? { condition: 'only after a full test confirms it' } : {}) })),
    limits: u.label,
    note: SAFETY,
  }
}

function usageLines(U) {
  return [
    `State: ${U.state}. Risk: ${U.risk_level}. ${U.pathway}.`,
    U.stop_using_after,
    ...(U.until_tested ? [U.until_tested] : []),
    ...U.can_be_used_for.slice(0, 6).map(a => `Can be used for ${a.application}, with ${a.confidence_percent}% confidence${a.condition ? ` (${a.condition})` : ''}.${a.advice ? ` ${a.advice}` : ''}`),
    `${U.limits} ${U.note}`,
  ]
}

/** The two models' answers, in everyday words. */
function modelsSentence(px, pq) {
  const both = `The standard model (XGBoost) gives it ${pct(px)} in 100, and the quantum model (AQSVC) gives it ${pct(pq)} in 100.`
  const agree = (px >= 0.5) === (pq >= 0.5)
  return [
    `Two computer models checked, separately, how likely this battery is to last at least ${LONG} more full charges. ${both}`,
    agree ? `The two models agree that it ${px >= 0.5 ? 'has a long life ahead' : 'is close to the end of its useful life'}.`
      : 'The two models disagree, so a lab test is the safest way to decide.',
  ]
}

function riseSentence(r) {
  if (r > 0.3) return `rising by about ${r.toFixed(1)} milliohms every 100 charges`
  if (r < -0.1) return 'slowly falling'
  return 'almost unchanged over recent charges'
}

/* ------------------------------------------------------------------ battery passport */
export function passportPlain(b, R) {
  const U = b.utilities
  const blocked = b.reuse_blocked
  const mates = b.pack ? (R.packs[b.pack] || []).filter(id => id !== b.id) : []
  let decision
  if (b.action === 'reuse') decision = `Reuse this battery. It has a long life ahead and has been grouped into ${b.pack} with ${mates.length} similar batteries.`
  else if (b.action === 'test') decision = 'Test this battery before deciding. It might be good enough to reuse, but the answer is not clear enough yet, so a proper lab test is the safer and cheaper choice.'
  else if (blocked) decision = 'Recycle this battery. It is close to the end of its useful life.'
  else decision = 'Recycle this battery. Testing it is not worth the cost compared with the other batteries, and no matching group of batteries was available for it.'

  const why = modelsSentence(b.p_xgb, b.p_aqsvc)
  if (b.action === 'reuse') why.push('Its group-mates have very similar health and behaviour, so they should age evenly together.')
  if (b.action === 'test' && U.test < U.reuse) why.push('It could probably be reused, but no matching group of batteries was available for it right now, so a test is the best next step.')
  if (b.action === 'recycle' && !blocked) why.push('Only a few batteries can be tested at a time, and those slots went to batteries where a test helps more.')

  const usageB = usagePlain(b.usage)
  const f = b.features

  return {
    document: 'CELLFEE battery passport',
    battery_id: b.id,
    created: today(),
    decision: { verdict: ACTION[b.action], ...(b.pack ? { group: b.pack, group_mates: mates } : {}), in_plain_words: decision },
    health: {
      health_percent: pct(b.soh),
      in_plain_words: `It still holds about ${pct(b.soh)}% of the energy it could store when new (measured).`,
      grade: b.grade,
      grade_meaning: GRADE[b.grade],
    },
    two_models: {
      question: `Will it last at least ${LONG} more full charges?`,
      standard_model_xgboost_chance_in_100: pct(b.p_xgb),
      quantum_model_aqsvc_chance_in_100: pct(b.p_aqsvc),
      models_agree: b.agree,
    },
    why,
    usage_baseline: usageB,
    key_measurements: {
      internal_resistance: `${f.ir_mohm.toFixed(1)} milliohms, ${riseSentence(f.ir_rise_100)}`,
      charge_cycles_used: Math.round(f.cycles),
      peak_temperature: `${Math.round(f.temp_max_c)} °C`,
      charge_time: `${Math.round(f.charge_time_min)} minutes`,
    },
    data_source: `Real laboratory test cell ${b.source_cell} (MIT, Stanford and Toyota research dataset), at charge cycle ${b.cycle}.`,
    screening_inputs: { ...b.features, chemistry: 'LFP' },
    important_note: NOTE,
  }
}

function passportSections(P) {
  const k = P.key_measurements
  return [
    { h: 'Decision', lines: [P.decision.in_plain_words] },
    { h: 'Health', lines: [P.health.in_plain_words, `Grade ${P.health.grade}: ${P.health.grade_meaning}.`] },
    { h: 'Two models', lines: P.why },
    { h: 'Usage baseline', lines: usageLines(P.usage_baseline) },
    { h: 'Key measurements', lines: [`Internal resistance: ${k.internal_resistance}.`, `Charge cycles used: ${k.charge_cycles_used}.`, `Peak temperature: ${k.peak_temperature}. Charge time: ${k.charge_time}.`] },
    { h: 'Data source', lines: [P.data_source] },
  ]
}

/* ------------------------------------------------------------------ assess / upload result */
const VERDICT = { reuse: 'Looks reusable', test: 'Test first', recycle: 'Recycle' }

export function assessPlain(res, name) {
  const verdict = VERDICT[res.suggested_action]
  const usageB = usagePlain(res.usage)
  const co2 = res.environment.net_kgco2e
  const f = res.features
  return {
    document: 'CELLFEE battery assessment',
    ...(name ? { battery_id: name } : {}),
    created: today(),
    decision: {
      verdict,
      in_plain_words: verdict === 'Looks reusable' ? 'This battery looks healthy enough for a second life, and both models expect a long life ahead.'
        : verdict === 'Test first' ? 'This battery might be reusable, but the answer is not clear. Give it a full lab test before deciding.'
          : 'This battery looks close to the end of its useful life. Recycling is the best route.',
    },
    health: {
      health_percent: pct(res.soh),
      in_plain_words: `It holds about ${pct(res.soh)}% of the energy it could store when new.`,
      grade: res.grade,
      grade_meaning: GRADE[res.grade],
    },
    two_models: {
      standard_model_xgboost_chance_in_100: pct(res.models.xgb.p_fit),
      quantum_model_aqsvc_chance_in_100: pct(res.models.aqsvc.p_fit),
      models_agree: res.agree,
      in_plain_words: modelsSentence(res.models.xgb.p_fit, res.models.aqsvc.p_fit),
    },
    usage_baseline: usageB,
    climate: `Reusing it instead of buying a new battery could avoid roughly ${co2.central} kg of CO2 (somewhere between ${co2.low} and ${co2.high} kg, depending on assumptions).`,
    notes: res.notes.map(m => m.split(' — ')[0]),
    screening_inputs: { ...f, chemistry: res.chemistry || 'LFP' },
    measurements: {
      internal_resistance: `${f.ir_mohm.toFixed(1)} milliohms, ${riseSentence(f.ir_rise_100)}`,
      charge_cycles_used: Math.round(f.cycles),
      peak_temperature: `${Math.round(f.temp_max_c)} °C`,
      charge_time: `${Math.round(f.charge_time_min)} minutes`,
    },
    important_note: NOTE,
  }
}

function assessSections(P) {
  const m = P.measurements
  return [
    { h: 'Decision', lines: [P.decision.in_plain_words] },
    { h: 'Health', lines: [P.health.in_plain_words, `Grade ${P.health.grade}: ${P.health.grade_meaning}.`] },
    { h: 'Two models', lines: P.two_models.in_plain_words },
    { h: 'Usage baseline', lines: usageLines(P.usage_baseline) },
    { h: 'Climate', lines: [P.climate] },
    ...(P.notes.length ? [{ h: 'Notes', lines: P.notes.map(n => n[0].toUpperCase() + n.slice(1) + '.') }] : []),
    { h: 'Measurements', lines: [`Internal resistance: ${m.internal_resistance}.`, `Charge cycles used: ${m.charge_cycles_used}.`, `Peak temperature: ${m.peak_temperature}. Charge time: ${m.charge_time}.`] },
  ]
}

/** A whole uploaded file of test results: one short plain record per battery. */
export function uploadPlain(U) {
  const ok = U.results.filter(r => !r.error)
  return {
    document: 'CELLFEE test-result screening',
    file: U.filename,
    created: today(),
    batteries_screened: ok.length,
    could_not_read: U.results.filter(r => r.error).map(r => ({ battery_id: r.battery_id, reason: r.error })),
    totals: ok.reduce((a, r) => ({ ...a, [VERDICT[r.suggested_action]]: (a[VERDICT[r.suggested_action]] || 0) + 1 }), {}),
    batteries: ok.map(r => {
      const P = assessPlain(r, r.battery_id)
      return {
        battery_id: r.battery_id, verdict: P.decision.verdict, health_percent: P.health.health_percent,
        standard_model_chance_in_100: P.two_models.standard_model_xgboost_chance_in_100,
        quantum_model_chance_in_100: P.two_models.quantum_model_aqsvc_chance_in_100,
        models_agree: P.two_models.models_agree, in_plain_words: P.decision.in_plain_words,
        screening_inputs: P.screening_inputs,
      }
    }),
    important_note: NOTE,
  }
}

/* ------------------------------------------------------------------ whole fleet */
const SHORT = {
  reuse: b => `Reuse, in ${b.pack}.`,
  test: b => (b.agree ? 'Test first: the models are not sure.' : 'Test first: the two models disagree.'),
  recycle: b => (b.reuse_blocked ? 'Recycle: close to the end of its useful life.' : 'Recycle: other batteries made better use of the test bench.'),
}

export function fleetPlain(R) {
  const F = R.fleet
  const tally = list => list.reduce((a, b) => ({ ...a, [ACTION[b.action]]: (a[ACTION[b.action]] || 0) + 1 }), {})
  const byBatch = {}
  F.forEach(b => { (byBatch[b.batch] = byBatch[b.batch] || []).push(b) })
  return {
    document: 'CELLFEE fleet summary',
    created: today(),
    batteries_screened: F.length,
    batches: R.fleet_plan.batches,
    packs_built: R.fleet_plan.packs,
    totals: tally(F),
    models_agree_on: F.filter(b => b.agree).length,
    per_batch: Object.entries(byBatch).map(([k, list]) => ({ batch: +k, batteries: list.length, ...tally(list) })),
    batteries: F.map(b => ({
      battery_id: b.id, batch: b.batch, verdict: ACTION[b.action], ...(b.pack ? { group: b.pack } : {}), health_percent: pct(b.soh),
      standard_model_chance_in_100: pct(b.p_xgb), quantum_model_chance_in_100: pct(b.p_aqsvc), in_plain_words: SHORT[b.action](b),
    })),
    important_note: NOTE,
  }
}

/* ------------------------------------------------------------------ files */
// Every download is also remembered in this browser (name, time and, for small CSV / JSON files, the content), so the
// Upload tab can list "recent downloads from CELLFEE" and re-screen one with a click: a web page cannot look inside
// the device's Downloads folder by itself.
const DL_KEY = 'cellfee-downloads'
const DL_KEEP = 8, DL_MAX_CHARS = 400_000

export function recentDownloads() {
  try { return JSON.parse(localStorage.getItem(DL_KEY) || '[]') } catch { return [] }
}
export function clearDownloads() {
  try { localStorage.removeItem(DL_KEY) } catch { /* storage unavailable */ }
}
function remember(name, type, content, content_b64) {
  const entry = { name, type, at: new Date().toLocaleString(), ...(content && content.length <= DL_MAX_CHARS ? { content } : {}),
    ...(content_b64 && content_b64.length <= DL_MAX_CHARS ? { content_b64 } : {}) }
  const list = [entry, ...recentDownloads().filter(d => d.name !== name)].slice(0, DL_KEEP)
  for (let n = list.length; n > 0; n--) {          // drop the oldest if browser storage is full
    try { localStorage.setItem(DL_KEY, JSON.stringify(list.slice(0, n))); break } catch { /* try fewer */ }
  }
  window.dispatchEvent(new Event('cellfee-downloads'))
}

function save(blob, name, text) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  const type = (name.split('.').pop() || '').toLowerCase()
  if (text != null || blob.size > DL_MAX_CHARS) { remember(name, type, text); return }
  const r = new FileReader()          // binary (PDF): keep it as base64 so it can be re-screened in one click
  r.onload = () => remember(name, type, null, String(r.result).split(',')[1])
  r.readAsDataURL(blob)
}
export function downloadJSON(obj, name) {
  const text = JSON.stringify(obj, null, 2)
  save(new Blob([text], { type: 'application/json' }), name, text)
}
export function saveText(text, name, type = 'text/plain') {
  save(new Blob([text], { type }), name, text)
}

// built-in PDF fonts only cover Latin-1, so swap the few symbols we use
const latin = s => String(s).replace(/₹/g, 'Rs. ').replace(/≥/g, '>=').replace(/≤/g, '<=').replace(/→/g, '->').replace(/₂/g, '2').replace(/Ω/g, 'ohm')
  .replace(/[–—]/g, '-').replace(/[✦]/g, '').replace(/[^\x00-\xFF]/g, '')

const VERDICT_FILL = { Reuse: [201, 243, 226], 'Looks reusable': [201, 243, 226], 'Test first': [255, 231, 184], Recycle: [255, 214, 208] }

// jsPDF is loaded on first use, so it doesn't weigh down the dashboard's initial load
async function buildPDF({ title, subtitle, verdict, sections, note }) {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), M = 48, TW = W - 2 * M
  let y = 0
  const ensure = (h, bottom = 60) => { if (y + h > H - bottom) { doc.addPage(); y = M } }
  // header bar
  doc.setFillColor(11, 11, 11); doc.rect(0, 0, W, 74, 'F')
  doc.setTextColor(255, 225, 77); doc.setFont('helvetica', 'bold'); doc.setFontSize(22); doc.text('CELLFEE', M, 44)
  doc.setTextColor(255, 255, 255); doc.setFontSize(11); doc.setFont('helvetica', 'normal')
  doc.text(latin(title), W - M, 38, { align: 'right' }); doc.text(latin(subtitle), W - M, 54, { align: 'right' })
  y = 104
  // verdict box
  doc.setDrawColor(11, 11, 11); doc.setLineWidth(1.6)
  doc.setFillColor(...(VERDICT_FILL[verdict] || [255, 253, 247])); doc.rect(M, y, TW, 46, 'FD')
  doc.setTextColor(11, 11, 11); doc.setFont('helvetica', 'bold'); doc.setFontSize(10); doc.text('DECISION', M + 14, y + 18)
  doc.setFontSize(20); doc.text(latin(verdict.toUpperCase()), M + 14, y + 38)
  y += 70
  for (const s of sections) {
    ensure(46)
    doc.setFillColor(255, 225, 77); doc.rect(M, y, doc.getTextWidth(latin(s.h.toUpperCase())) * 0.9 + 22, 18, 'FD')
    doc.setFont('helvetica', 'bold'); doc.setFontSize(9.5); doc.text(latin(s.h.toUpperCase()), M + 8, y + 12.5)
    y += 28
    doc.setFont('helvetica', 'normal'); doc.setFontSize(11.5)
    for (const line of s.lines) {
      const wrapped = doc.splitTextToSize(latin(line), TW)
      ensure(wrapped.length * 15 + 4)
      doc.text(wrapped, M, y); y += wrapped.length * 15 + 5
    }
    y += 8
  }
  ensure(44, 36)
  doc.setDrawColor(11, 11, 11); doc.setLineWidth(1); doc.line(M, y, W - M, y); y += 16
  doc.setFontSize(9.5); doc.setTextColor(80, 78, 72)
  doc.text(doc.splitTextToSize(latin(note), TW), M, y)
  const pages = doc.getNumberOfPages()
  for (let i = 1; i <= pages; i++) { doc.setPage(i); doc.setFontSize(8.5); doc.setTextColor(120, 116, 106); doc.text(`Page ${i} of ${pages}`, W - M, H - 24, { align: 'right' }) }
  return doc
}

export async function downloadPassportPDF(P) {
  save((await buildPDF({ title: `Battery passport · ${P.battery_id}`, subtitle: `Created ${P.created}`, verdict: P.decision.verdict, sections: passportSections(P), note: P.important_note })).output('blob'), `cellfee-passport-${P.battery_id}.pdf`)
}
export async function downloadAssessPDF(P) {
  save((await buildPDF({ title: 'Battery assessment', subtitle: `Created ${P.created}`, verdict: P.decision.verdict, sections: assessSections(P), note: P.important_note })).output('blob'), `cellfee-assessment-${P.created}.pdf`)
}
export async function downloadFleetPDF(F) {
  // thousands of batteries: the PDF summarises (totals + one line per batch); the JSON lists every battery
  const t = F.totals
  const groups = [
    { h: 'In short', lines: [
      `${F.batteries_screened.toLocaleString()} batteries were checked, in ${F.batches} truckloads.`,
      `Reuse: ${(t.Reuse || 0).toLocaleString()} (grouped into ${F.packs_built.toLocaleString()} packs of 4). Test first: ${(t['Test first'] || 0).toLocaleString()}. Recycle: ${(t.Recycle || 0).toLocaleString()}.`,
      `The standard and quantum models agreed on ${F.models_agree_on.toLocaleString()} of them. Where they disagreed, the battery is tested before deciding.`,
      'The JSON download lists every battery with its verdict and a one-line reason.'] },
    { h: 'Truckload by truckload', lines: F.per_batch.map(b => `Batch ${b.batch}: ${b.batteries} batteries - reuse ${b.Reuse || 0}, test ${b['Test first'] || 0}, recycle ${b.Recycle || 0}.`) },
  ]
  save((await buildPDF({ title: 'Fleet summary', subtitle: `${F.batteries_screened} batteries · created ${F.created}`, verdict: `${F.batteries_screened} batteries`, sections: groups, note: F.important_note })).output('blob'), `cellfee-fleet-summary-${F.created}.pdf`)
}
export async function downloadUploadPDF(F) {
  const groups = ['Looks reusable', 'Test first', 'Recycle'].map(v => ({
    h: `${v} (${F.batteries.filter(b => b.verdict === v).length})`,
    lines: F.batteries.filter(b => b.verdict === v).map(b => `${b.battery_id}: ${b.health_percent}% health; standard model ${b.standard_model_chance_in_100}/100, quantum model ${b.quantum_model_chance_in_100}/100${b.models_agree ? '' : ' (they disagree)'}. ${b.in_plain_words}`),
  })).filter(g => g.lines.length)
  if (F.could_not_read.length) groups.push({ h: 'Could not read', lines: F.could_not_read.map(c => `${c.battery_id}: ${c.reason}.`) })
  save((await buildPDF({ title: 'Test-result screening', subtitle: `${F.file} · ${F.created}`, verdict: `${F.batteries_screened} batteries`, sections: groups, note: F.important_note })).output('blob'), `cellfee-screening-${F.created}.pdf`)
}
export { passportSections, assessSections }

// Usage baseline, risk factor, stop period and per-application confidence (Part A2-A4).
// Every value comes from the stored pipeline output or the live /api/assess result; the limits are configured
// baselines from backend/cellfee/registry (labelled as such on screen).
import { STATE_CLASS, RISK_CLASS, confFrac, confText, monthsText, stopText } from './usageFormat.js'

export const NOTE = 'Decision support from stored test data. Not a safety certification.'

export function SafetyNote() {
  return <p className="small muted usage-note">{NOTE}</p>
}

/** "How is this calculated?" — a native disclosure, so it works by keyboard and without JS. */
export function HowCalc({ children, label = 'How is this calculated?' }) {
  return <details className="howcalc"><summary>{label}</summary><div className="small">{children}</div></details>
}

export function StateBadge({ state }) {
  return <span className={`tag t-${STATE_CLASS[state] || 'recycle'}`} data-anim="stamp">{state}</span>
}

export function RiskBadge({ risk, R }) {
  const v = R.usage?.validation?.risk_levels?.[risk.level]
  const B = R.usage?.baselines?.risk
  return (
    <span className="row" style={{ gap: 6 }}>
      <span className={`tag t-${RISK_CLASS[risk.level]}`} data-anim="stamp">Risk: {risk.level}</span>
      <span className="mono small">score {risk.score.toFixed(2)}</span>
      <HowCalc label="How is the risk factor calculated?">
        Weighted mean of five 0–1 parts: health margin to 80% ({B?.weights.health_margin}), capacity fade rate ({B?.weights.fade_rate}),
        resistance rise ({B?.weights.resistance_rise}), peak temperature ({B?.weights.temperature}) and model doubt ({B?.weights.model_doubt}; 1 when XGBoost
        and AQSVC disagree). Fade and resistance are percentiles among the {R.data.snapshots.toLocaleString()} training snapshots.
        Elevated from {B?.levels.elevated_from}, High from {B?.levels.high_from}. This battery: {Object.entries(risk.components).map(([k, x]) => `${k.replace('_', ' ')} ${x.toFixed(2)}`).join(', ')}.
        {v && v.reached_80pct_within_100_cycles != null && <> Check on the training data: {Math.round(v.reached_80pct_within_100_cycles * 100)}% of “{risk.level}” snapshots fell to 80% health within 100 cycles.</>}
        {' '}Risk caps the safety tier this battery may serve (tier ≤ {risk.tier_limit}).
      </HowCalc>
    </span>
  )
}

/** Stop-period bar: P10–P90 band, P50 tick, scaled to the configured cycle cap (the baseline limit marker). */
export function StopBar({ stop }) {
  const cap = Math.max(1, stop.cap)
  const f = v => Math.min(1, v / cap)
  return (
    <div className="stopbar" role="img" aria-label={`Stop period ${stopText(stop)}; baseline cap ${stop.cap} cycles`}>
      <i className="band" data-anim="growx" style={{ left: `${f(stop.p10) * 100}%`, width: `${(f(stop.p90) - f(stop.p10)) * 100}%` }} />
      <i className="fill" data-anim="growx" style={{ width: `${f(stop.p10) * 100}%` }} />
      <i className="p50" style={{ left: `${f(stop.p50) * 100}%` }} />
      <i className="cap" data-anim="slidein" title={`configured cap: ${stop.cap} cycles`} />
    </div>
  )
}

function Baseline({ b }) {
  return (
    <div className="kv small">
      <div>Health floor</div><div className="mono">{Math.round(b.min_soh * 100)}%</div>
      <div>Max C-rate · max temperature</div><div className="mono">{b.max_c_rate}C · {b.max_temp_c} °C</div>
      <div>Max internal resistance</div><div className="mono">{b.max_ir_mohm} mΩ</div>
      <div>Max cycles in service</div><div className="mono">{b.max_cycles_in_service.toLocaleString()}</div>
    </div>
  )
}

/** Ranked "can be used for X with confidence Y%" rows. */
export function AppConfidence({ apps, R, limit = 8, showAll = false }) {
  const low = R.usage?.baselines?.confidence?.low_threshold_pct ?? 60
  const rows = showAll ? apps : apps.filter(a => a.confidence != null).slice(0, limit)
  const off = apps.filter(a => a.confidence == null)
  return (
    <div className="appconf">
      {rows.length === 0 && <p className="small muted">No second-life application.</p>}
      {rows.map(a => (
        <div key={a.id} className="ac-row" data-anim="row">
          <div className="ac-name"><b>{a.name}</b><span className="small muted">{a.status}{a.limiter ? ` · limited by ${a.limiter}` : ''}</span></div>
          <div className="ac-bar" aria-hidden="true"><i data-anim="growx" style={{ width: `${confFrac(a.confidence) * 100}%` }} /></div>
          <div className="ac-pct mono">{confText(a.confidence)}</div>
          <div className="ac-stop small"><span className="mono">{stopText(a.stop)}</span> <span className="muted">{a.stop.state}</span></div>
          {a.low_confidence && <div className="ac-flag small">Below {low}% — run a full test before deploying.</div>}
        </div>
      ))}
      {!showAll && off.length > 0 && <details className="howcalc"><summary>{off.length} not suitable — why?</summary>
        <div className="small">{off.map(a => <div key={a.id}><b>{a.name}:</b> {a.status}{a.gates_failed?.length ? ` — ${a.gates_failed.join('; ')}` : ''}</div>)}</div></details>}
      <HowCalc>
        Confidence = the probability, from an XGBoost classifier trained for that application's requirement
        (health ≥ its floor for at least its required cycles; XGBoost is the stronger model in the stored comparison), validated by
        grouped cross-validation on {R.data.snapshots.toLocaleString()} real snapshots; fleet batteries use out-of-fold predictions.
        Measured requirements (chemistry, health, capacity, resistance, peak temperature, safety tier vs risk) are pass/fail gates, so a failed gate has no %.
        Stop period = XGBoost quantile regression of cycles until health falls below the application floor (P10 / P50 / P90), capped at the configured cycles in service.
        Packs: minimum over members.
      </HowCalc>
    </div>
  )
}

/** Battery-level usage baseline block (passport, Assess). */
export function UsageBaseline({ u, R }) {
  const best = u.applications.find(a => a.id === u.best)
  const testB = u.pathway.baseline
  return (
    <div className="usage" data-anim="usage">
      <div className="row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <StateBadge state={u.state} /><RiskBadge risk={u.risk} R={R} />
      </div>
      <p className="small" style={{ margin: '0 0 6px' }}><b>{u.pathway.label}.</b>{' '}
        {best ? <>Best fit: <b>{best.name}</b> ({confText(best.confidence)} confidence). Stop by {stopText(best.stop)} — {monthsText(best.stop)}.</>
          : u.pathway.action === 'recycle' ? 'Do not reuse: no further usage allowed.' : 'No application currently passes its baseline.'}</p>
      {best?.stop.restricted_cap != null && <p className="small" style={{ margin: '0 0 6px' }}><b>Restricted use until tested:</b> at most {best.stop.restricted_cap} cycles, ≤ {testB?.max_c_rate}C, ≤ {testB?.max_temp_c} °C, tier-1 uses only.</p>}
      {best && <StopBar stop={best.stop} />}
      {best && <Baseline b={testB ? { ...best.baseline, ...testB } : best.baseline} />}
      <p className="small muted" style={{ margin: '6px 0 0' }}>{u.label}</p>
      <SafetyNote />
    </div>
  )
}

/** Pack-level baseline: the weakest member governs. */
export function PackUsage({ name, pd, R }) {
  const best = pd.applications[0]
  return (
    <div className="card pack-usage" data-anim="pack">
      <div className="row spread"><h4 style={{ margin: 0 }}>{name}</h4><StateBadge state={pd.state} /></div>
      <p className="small muted" style={{ margin: '4px 0 8px' }}>Batch {pd.batch} · {pd.members.join(', ')} · <span data-count={pd.capacity_ah} data-decimals="2">{pd.capacity_ah.toFixed(2)}</span> Ah</p>
      {best ? <>
        <p className="small" style={{ margin: '0 0 6px' }}>Limiter: <b className="mono">{pd.limiter}</b> (weakest member). Stop by {stopText(best.stop)}.</p>
        <StopBar stop={best.stop} />
        <AppConfidence apps={pd.applications} R={R} limit={5} showAll />
      </> : <p className="small">No application passes for every member.</p>}
      <SafetyNote />
    </div>
  )
}

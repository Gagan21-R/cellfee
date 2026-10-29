import { createContext, Fragment, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { answer, buildKB, SUGGESTIONS } from './explain.js'

const Ctx = createContext({ explain: () => {} })
export const useGuide = () => useContext(Ctx)

/** "Explain me" button for the top-right corner of a card (the card is position: relative). */
export function Explain({ id, label = 'Explain me' }) {
  const { explain } = useGuide()
  return (
    <button type="button" className="explain-btn" onClick={e => { e.stopPropagation(); explain(id) }} aria-label={`${label}: open the guide for this section`}>
      <span aria-hidden="true">✦</span>{label}
    </button>
  )
}

// **bold**, paragraphs, and "• " bullets
function Rich({ text }) {
  const inline = s => s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') ? <b key={i}>{part.slice(2, -2)}</b> : <Fragment key={i}>{part}</Fragment>)
  return text.split(/\n\s*\n/).map((para, i) => {
    const lines = para.split('\n')
    if (lines.every(l => l.trim().startsWith('•'))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*•\s*/, ''))}</li>)}</ul>
    if (lines.some(l => l.trim().startsWith('•'))) return (
      <div key={i}>{lines.map((l, j) => l.trim().startsWith('•')
        ? <ul key={j}><li>{inline(l.replace(/^\s*•\s*/, ''))}</li></ul> : <p key={j}>{inline(l)}</p>)}</div>)
    return <p key={i}>{inline(para)}</p>
  })
}

export function GuideProvider({ R, children }) {
  const KB = useMemo(() => (R ? buildKB(R) : {}), [R])
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState([])
  const [draft, setDraft] = useState('')
  const listRef = useRef(null)
  const inputRef = useRef(null)

  const push = (...m) => setMsgs(prev => [...prev, ...m])
  const explain = id => {
    const e = KB[id]
    setOpen(true)
    if (!e) return push({ who: 'bot', title: 'Not found', text: "I don't have an explanation for that part yet." })
    push({ who: 'user', text: `Explain: ${e.title}` }, { who: 'bot', title: e.title, text: e.text })
  }
  const ask = text => {
    const q = text.trim(); if (!q) return
    const hit = answer(KB, q, R)
    push({ who: 'user', text: q }, hit
      ? { who: 'bot', title: hit.title, text: hit.text }
      : { who: 'bot', title: "I'm not sure about that one", text: `I answer from a built-in guide to this dashboard, so I may not know everything. Try asking about a part of the page, e.g. **quantum kernel**, **QAOA**, **grades**, **forbidden pairs**, **NLL**, **marketplace**, or a battery id like **RB-07**.` })
    setDraft('')
  }

  useEffect(() => { if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight }, [msgs, open])
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 60) }, [open])
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <Ctx.Provider value={{ explain }}>
      {children}
      {!open && R && (
        <button type="button" className="guide-fab" onClick={() => setOpen(true)} aria-label="Open the CELLFEE guide">
          <span aria-hidden="true">✦</span> Ask the guide
        </button>
      )}
      {open && (
        <aside className="guide" role="dialog" aria-label="CELLFEE guide">
          <header className="guide-head">
            <div>
              <b>CELLFEE Guide</b>
              <div className="muted small">Explains every part of this dashboard with your live results</div>
            </div>
            <div className="row">
              {msgs.length > 0 && <button type="button" className="btn small-btn" onClick={() => setMsgs([])}>Clear</button>}
              <button type="button" className="btn small-btn" onClick={() => setOpen(false)} aria-label="Close guide">Close</button>
            </div>
          </header>
          <div className="guide-list" ref={listRef} aria-live="polite">
            {msgs.length === 0 && (
              <div className="bubble bot">
                <b className="bubble-title">Hi! I'm the CELLFEE guide.</b>
                <p>Click <b>✦ Explain me</b> on any card and I'll explain what it means, using the numbers on your screen. You can also type a question below.</p>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.who}`}>
                {m.title && <b className="bubble-title">{m.title}</b>}
                {m.who === 'bot' ? <Rich text={m.text} /> : <p>{m.text}</p>}
              </div>
            ))}
          </div>
          <div className="guide-chips">
            {SUGGESTIONS.map(s => <button type="button" key={s} className="chip-btn" onClick={() => ask(s)}>{s}</button>)}
          </div>
          <form className="guide-input" onSubmit={e => { e.preventDefault(); ask(draft) }}>
            <input ref={inputRef} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Ask about any part of the dashboard…" aria-label="Ask the guide" />
            <button type="submit" className="btn primary" disabled={!draft.trim()}>Ask</button>
          </form>
          <div className="guide-note muted">Answers come from a built-in guide to this dashboard, not a general AI.</div>
        </aside>
      )}
    </Ctx.Provider>
  )
}

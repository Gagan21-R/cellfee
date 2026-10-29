// Run: node --test src/usageFormat.test.js   (from frontend/)
// Checks that displayed confidence text equals the stored value, rounded, and stays within 0-100.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { confFrac, confText, monthsText, stopText } from './usageFormat.js'

test('confidence text is the stored value rounded, clamped to 0-100', () => {
  assert.equal(confText(87.4), '87%')
  assert.equal(confText(87.5), '88%')
  assert.equal(confText(0), '0%')
  assert.equal(confText(99.4), '99%')
  assert.equal(confText(99.7), '>99%')
  assert.equal(confText(100), '>99%')
  assert.equal(confText(null), 'not available')
  assert.equal(confFrac(150), 1)
  assert.equal(confFrac(-3), 0)
})

test('stop period text shows P10 first, with the P10-P90 range', () => {
  assert.match(stopText({ p10: 120, p50: 300, p90: 520 }), /^120 cycles \(typical 300, range 120–520\)$/)
  assert.equal(stopText({ p10: 0, p50: 0, p90: 0 }), 'stop now (at or below the floor)')
  assert.match(monthsText({ p10: 386, p50: 462, months_p10: 385.6, months_p50: 462.3 }), /^over 10 years/)
  assert.equal(monthsText({ p10: 120, p50: 300, months_p10: 4.4, months_p50: 11 }), '≈ 4.4 months at that duty (typical 11)')
})

const details = new URL('../../artifacts/fleet_details.json', import.meta.url)
test('every stored confidence on the 5,000 passports is displayable as a 0-100 %', { skip: !existsSync(details) }, () => {
  const D = JSON.parse(readFileSync(details, 'utf8'))
  let n = 0
  for (const d of Object.values(D)) {
    for (const a of d.usage?.applications || []) {
      if (a.confidence == null) continue
      assert.ok(a.confidence >= 0 && a.confidence <= 100, `${a.id} ${a.confidence}`)
      assert.equal(confText(a.confidence), a.confidence >= 99.5 ? '>99%' : `${Math.round(a.confidence)}%`)
      n++
    }
  }
  assert.ok(n > 0)
})

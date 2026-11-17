import assert from 'node:assert/strict'
import test from 'node:test'
import { autoStartMission } from './autoStart.js'

test('a ready backend route automatically starts a mission', async () => {
  let starts = 0
  const started = await autoStartMission(true, async () => { starts += 1 })
  assert.equal(started, true)
  assert.equal(starts, 1)
})

test('a missing route does not start a mission', async () => {
  let starts = 0
  const started = await autoStartMission(false, async () => { starts += 1 })
  assert.equal(started, false)
  assert.equal(starts, 0)
})

import { describe, expect, it } from 'vitest'
import { parseMoney } from './format'

describe('parseMoney', () => {
  it('parses Russian formatted money to minor units without floats', () => expect(parseMoney('1 234,56')).toBe(123456))
  it('keeps exact kopecks', () => expect(parseMoney('0,01')).toBe(1))
  it('rejects excessive precision', () => expect(() => parseMoney('1,001')).toThrow())
})

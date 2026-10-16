import { describe, expect, it } from 'vitest'
import { superappReturnPath } from './authRedirect'

describe('superapp return after shared authentication', () => {
  it('returns to the requested photo page only in the combined app', () => {
    expect(superappReturnPath('?next=%2Fphoto%2F', '/budget/')).toBe('/photo/')
    expect(superappReturnPath('?next=%2Fphoto%2Ff%2F123%3Ftab%3Daccess', '/budget/')).toBe('/photo/f/123?tab=access')
    expect(superappReturnPath('?next=%2Fphoto%2F', '/')).toBeNull()
    expect(superappReturnPath('?next=%2Fadmin%2F', '/budget/')).toBe('/admin/')
    expect(superappReturnPath('?next=%2F', '/budget/')).toBe('/')
  })

  it('rejects other origins and unrelated routes', () => {
    expect(superappReturnPath('?next=https%3A%2F%2Fexample.com%2Fphoto%2F', '/budget/')).toBeNull()
    expect(superappReturnPath('?next=%2F%2Fexample.com%2Fphoto%2F', '/budget/')).toBeNull()
    expect(superappReturnPath('?next=%2Fbudget%2F', '/budget/')).toBeNull()
    expect(superappReturnPath('?next=%2Fadmin%2Fevil', '/budget/')).toBeNull()
  })
})

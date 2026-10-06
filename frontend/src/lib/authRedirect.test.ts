import { describe, expect, it } from 'vitest'
import { photoReturnPath } from './authRedirect'

describe('photo return after shared authentication', () => {
  it('returns to the requested photo page only in the combined app', () => {
    expect(photoReturnPath('?next=%2Fphoto%2F', '/budget/')).toBe('/photo/')
    expect(photoReturnPath('?next=%2Fphoto%2Ff%2F123%3Ftab%3Daccess', '/budget/')).toBe('/photo/f/123?tab=access')
    expect(photoReturnPath('?next=%2Fphoto%2F', '/')).toBeNull()
  })

  it('rejects other origins and unrelated routes', () => {
    expect(photoReturnPath('?next=https%3A%2F%2Fexample.com%2Fphoto%2F', '/budget/')).toBeNull()
    expect(photoReturnPath('?next=%2F%2Fexample.com%2Fphoto%2F', '/budget/')).toBeNull()
    expect(photoReturnPath('?next=%2Fbudget%2F', '/budget/')).toBeNull()
  })
})

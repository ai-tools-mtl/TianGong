import { Suspense } from 'react'

import { RegisterInner } from './register-inner'

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterInner />
    </Suspense>
  )
}

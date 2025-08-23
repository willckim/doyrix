import { useState } from 'react'
import { useRouter } from 'next/router'
import { supabase } from '../lib/supabase' // update this path if needed

export default function Signup() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const router = useRouter()

  const handleSignup = async (e: React.FormEvent) => {
  e.preventDefault()
  setError('')

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
  })

  if (error) {
    setError(error.message)
  } else {
    const user = data.user
    if (user) {
      // Insert 'free' role for new user
      await supabase.from('user_roles').insert({
        user_id: user.id,
        role: 'free',
      })
    }

    router.push('/dashboard')
  }
}

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-100">
      <form onSubmit={handleSignup} className="bg-white p-8 rounded shadow-md space-y-4 w-full max-w-md">
        <h2 className="text-2xl font-bold">Sign up for Doyrix</h2>
        <input
          type="email"
          placeholder="Email"
          className="border p-2 w-full"
          value={email}
          onChange={e => setEmail(e.target.value)}
        />
        <input
          type="password"
          placeholder="Password"
          className="border p-2 w-full"
          value={password}
          onChange={e => setPassword(e.target.value)}
        />
        <button type="submit" className="w-full bg-black text-white py-2 rounded">Sign Up</button>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </form>
    </main>
  )
}

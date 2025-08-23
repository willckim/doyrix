import { useUser } from '@supabase/auth-helpers-react'
import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/router'
import { supabase } from '../lib/supabase'

type RoleRow = { role: string | null; plan_expires_at: string | null }

export default function Dashboard() {
  const user = useUser()
  const router = useRouter()

  const [role, setRole] = useState<string>('free')
  const [expiresAt, setExpiresAt] = useState<Date | null>(null)
  const [loading, setLoading] = useState(true)
  const [upgrading, setUpgrading] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const status = useMemo(() => {
    if (typeof window === 'undefined') return null
    return new URLSearchParams(window.location.search).get('status') // "success" | "cancel" | null
  }, [])

  const fetchRole = async () => {
    if (!user?.id) { setLoading(false); return }
    setLoading(true)
    const { data, error } = await supabase.rpc('current_user_role_with_expiry')
    if (error) {
      if (process.env.NODE_ENV !== 'production') console.error('role rpc error:', error)
      setRole('free'); setExpiresAt(null); setLoading(false); return
    }
    const row = (Array.isArray(data) ? data[0] : null) as RoleRow | null
    setRole(row?.role ?? 'free')
    setExpiresAt(row?.plan_expires_at ? new Date(row.plan_expires_at) : null)
    setLoading(false)
  }

  useEffect(() => { fetchRole() }, [user?.id])

  // Redirect to /login when there is explicitly no session
  useEffect(() => {
    if (user === null) router.replace('/login')
  }, [user, router])

  // Re-check after returning from Stripe
  useEffect(() => {
    if (status === 'success') {
      setMsg('Payment success — updating your role…')
      const t = setTimeout(async () => { await fetchRole(); setMsg(null) }, 1200)
      return () => clearTimeout(t)
    }
    if (status === 'cancel') setMsg('Checkout was canceled.')
  }, [status])

  // Refresh on auth state change (sign in/out, token refresh)
  useEffect(() => {
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setMsg(null)
      setUpgrading(false)
      if (!session) {
        setRole('free')
        setExpiresAt(null)
      }
      fetchRole()
    })
    return () => { sub.subscription?.unsubscribe?.() }
  }, [])

  async function handleUpgrade() {
    if (upgrading) return
    setMsg(null); setUpgrading(true)

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15000)

    try {
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token

      const res = await fetch('/api/create-checkout-session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        signal: controller.signal,
      })

      const raw = await res.text()
      let data: any
      try { data = JSON.parse(raw) } catch { throw new Error(`Unexpected non-JSON response (${res.status})`) }

      if (!res.ok || data?.error) throw new Error(data?.error || `HTTP ${res.status}`)
      if (!data?.url) throw new Error('No checkout URL returned')

      window.location.href = data.url
    } catch (err: any) {
      if (err?.name === 'AbortError') setMsg('Upgrade timed out. Is the API route running?')
      else setMsg(err?.message || 'Upgrade failed. See console for details.')
      setUpgrading(false)
    } finally {
      clearTimeout(timer)
    }
  }

  async function handleSignOut() {
    await supabase.auth.signOut()
    // Redirect immediately; the auth listener will also clean local state
    router.replace('/login')
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-white text-black p-8">
      <h1 className="text-3xl font-bold mb-4">Welcome to Doyrix</h1>

      {user ? (
        <>
          <p className="text-lg mb-2">You&apos;re logged in as: <strong>{user.email}</strong></p>

          <p className="text-md">
            Your role: <strong>{loading ? 'Loading…' : role}</strong>
          </p>

          {!loading && expiresAt && role !== 'free' && (
            <p className="text-sm text-gray-600 mt-1">
              Plan renews/expires: <strong>{expiresAt.toLocaleDateString()}</strong>
            </p>
          )}

          <div className="mt-6 flex items-center gap-3">
            {!loading && role === 'free' && (
              <button
                type="button"
                onClick={handleUpgrade}
                disabled={upgrading}
                className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
              >
                {upgrading ? 'Redirecting…' : 'Upgrade to Pro'}
              </button>
            )}

            <button
              type="button"
              onClick={handleSignOut}
              className="rounded border px-3 py-2 text-sm"
            >
              Sign out
            </button>
          </div>

          <button
            type="button"
            onClick={fetchRole}
            className="mt-3 text-sm underline text-gray-600"
          >
            Refresh role
          </button>

          {msg && <p className="mt-3 text-sm text-amber-700">{msg}</p>}
        </>
      ) : (
        <p>Loading user info…</p>
      )}
    </main>
  )
}

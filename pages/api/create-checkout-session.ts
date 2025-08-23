import type { NextApiRequest, NextApiResponse } from 'next'
import Stripe from 'stripe'
import { createPagesServerClient } from '@supabase/auth-helpers-nextjs'
import { createClient } from '@supabase/supabase-js'

/**
 * Use a real pinned Stripe API version. (The "basil" tag isn't valid.)
 * Pick a recent stable version you’re comfortable with.
 */
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2024-06-20' as Stripe.StripeConfig['apiVersion'],
})

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST')
    return res.status(405).json({ error: 'Method Not Allowed' })
  }

  // Basic env guards (keep these fast & JSON)
  if (!process.env.STRIPE_SECRET_KEY) {
    return res.status(500).json({ error: 'Missing STRIPE_SECRET_KEY' })
  }
  if (!process.env.DOYRIX_PRO_PRICE_ID) {
    return res.status(500).json({ error: 'Missing DOYRIX_PRO_PRICE_ID' })
  }
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
    return res.status(500).json({ error: 'Supabase env not configured' })
  }

  try {
    // 1) Try cookie-based auth (Next.js pages client)
    const pagesClient = createPagesServerClient({ req, res })
    let { data: { user }, error: cookieErr } = await pagesClient.auth.getUser()
    let authPath: 'cookies' | 'bearer' | null = user ? 'cookies' : null

    // 2) Fallback to Authorization: Bearer <jwt>
    if (!user) {
      const authHeader = req.headers.authorization // "Bearer <jwt>"
      if (authHeader?.startsWith('Bearer ')) {
        const supaFromBearer = createClient(
          process.env.NEXT_PUBLIC_SUPABASE_URL!,
          process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
          { global: { headers: { Authorization: authHeader } } }
        )
        const r = await supaFromBearer.auth.getUser()
        user = r.data.user ?? null
        authPath = user ? 'bearer' : null
      }
    }

    if (!user) {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('Auth failed: no user from cookies or bearer', { cookieErr })
      }
      return res.status(401).json({ error: 'Not authenticated' })
    }

    const origin =
      req.headers.origin ??
      process.env.NEXT_PUBLIC_SITE_URL ??
      'http://localhost:3000'

    // Create Checkout Session
    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      line_items: [{ price: process.env.DOYRIX_PRO_PRICE_ID!, quantity: 1 }],
      success_url: `${origin}/dashboard?status=success`,
      cancel_url: `${origin}/dashboard?status=cancel`,
      customer_email: user.email ?? undefined,
      metadata: { user_id: user.id, auth_path: authPath ?? 'unknown' },
      allow_promotion_codes: true,
    })

    return res.status(200).json({ url: session.url })
  } catch (err: any) {
    const msg = err?.message ?? 'Unknown error'
    // Always JSON so the frontend debug parser is happy
    if (process.env.NODE_ENV !== 'production') {
      console.error('Stripe checkout error:', err)
    }
    return res.status(500).json({ error: msg })
  }
}

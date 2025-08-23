import type { NextApiRequest, NextApiResponse } from 'next'
import Stripe from 'stripe'
import { buffer } from 'micro'
import { createClient } from '@supabase/supabase-js'

export const config = { api: { bodyParser: false } }

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2024-06-20' as Stripe.StripeConfig['apiVersion'],
})

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
)

function getPeriodEnd(sub: unknown): number | null {
  const sec = (sub as any)?.current_period_end
  return typeof sec === 'number' ? sec : null
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST')
    return res.status(405).json({ error: 'Method Not Allowed' })
  }

  const sig = req.headers['stripe-signature']
  const whsec = process.env.STRIPE_WEBHOOK_SECRET
  if (!sig || !whsec) return res.status(400).json({ error: 'Missing webhook secret/signature' })

  let event: Stripe.Event
  try {
    const buf = await buffer(req)
    event = stripe.webhooks.constructEvent(buf, sig as string, whsec)
  } catch (err: any) {
    console.error('Webhook signature verification failed:', err?.message)
    return res.status(400).json({ error: `Invalid signature: ${err?.message}` })
  }

  try {
    switch (event.type) {
      case 'checkout.session.completed': {
        const s = event.data.object as Stripe.Checkout.Session
        const userId = s.metadata?.user_id
        const subId = (s.subscription as string) || null

        if (userId) {
          let expiresAt: string | null = null
          if (subId) {
            const sub = await stripe.subscriptions.retrieve(subId)
            const end = getPeriodEnd(sub)
            if (end) expiresAt = new Date(end * 1000).toISOString()
          }

          const { error } = await supabase
            .from('user_roles') // <-- adjust if your table/columns differ
            .upsert(
              {
                user_id: userId,
                role: 'pro',
                plan_expires_at: expiresAt,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' }
            )

          if (error) {
            console.error('Supabase upsert error:', error)
            return res.status(500).json({ error: 'Failed to update role' })
          }
        }
        break
      }

      case 'customer.subscription.updated':
      case 'customer.subscription.created': {
        const sub = event.data.object as Stripe.Subscription
        const userId = (sub as any)?.metadata?.user_id
        const end = getPeriodEnd(sub)
        const expiresAt = end ? new Date(end * 1000).toISOString() : null

        if (userId) {
          const { error } = await supabase
            .from('user_roles')
            .upsert(
              {
                user_id: userId,
                role: sub.status === 'active' ? 'pro' : 'free',
                plan_expires_at: expiresAt,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' }
            )
          if (error) {
            console.error('Supabase upsert error:', error)
            return res.status(500).json({ error: 'Failed to update role' })
          }
        }
        break
      }

      case 'customer.subscription.deleted': {
        const sub = event.data.object as Stripe.Subscription
        const userId = (sub as any)?.metadata?.user_id
        if (userId) {
          const { error } = await supabase
            .from('user_roles')
            .upsert(
              {
                user_id: userId,
                role: 'free',
                plan_expires_at: null,
                updated_at: new Date().toISOString(),
              },
              { onConflict: 'user_id' }
            )
          if (error) {
            console.error('Supabase upsert error:', error)
            return res.status(500).json({ error: 'Failed to downgrade role' })
          }
        }
        break
      }

      default:
        // ignore other events
        break
    }

    return res.json({ received: true })
  } catch (err: any) {
    console.error('Webhook handler error:', err)
    return res.status(500).json({ error: err?.message || 'Server error' })
  }
}

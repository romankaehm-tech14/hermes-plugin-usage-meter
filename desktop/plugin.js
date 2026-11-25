/**
 * Usage Meter — token and cost readout in the Desktop composer.
 *
 *   heute $0,38 · 1,3 Mio Tok   │   Chat $0,04 · 151 k Tok
 *
 * Left half: everything spent since local midnight, all models, from the
 * plugin's own backend (dashboard/plugin_api.py -> GET /today).
 * Right half: the focused chat, live from host.state.focusedUsage (no RPC).
 * Click cycles the detail strip: per-model -> top chats of the day -> closed.
 *
 * Plain ESM, loaded uncompiled: jsx() calls, not JSX syntax.
 */
import { COMPOSER_AREAS, host, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useEffect, useState } from 'react'

const ID = 'usage-meter'
const POLL_MS = 30000
const TOP_N = 5

// ctx.rest is only available inside register(); the component reads it here.
let rest = null

function num(obj, ...keys) {
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === 'number' && isFinite(v)) return v
  }
  return 0
}

/** Normalise whatever UsageStats shape the host streams into our own fields. */
function readUsage(u) {
  if (!u || typeof u !== 'object') return null
  const input = num(u, 'input_tokens', 'inputTokens', 'prompt_tokens', 'promptTokens')
  const output = num(u, 'output_tokens', 'outputTokens', 'completion_tokens', 'completionTokens')
  const reasoning = num(u, 'reasoning_tokens', 'reasoningTokens')
  const cacheRead = num(u, 'cache_read_tokens', 'cacheReadTokens', 'cached_tokens', 'cachedTokens')
  const cost = num(u, 'cost_usd', 'costUsd', 'estimated_cost_usd', 'estimatedCostUsd', 'cost', 'total_cost_usd')
  const tokens = input + output + reasoning
  if (!tokens && !cost) return null
  return { input, output, reasoning, cacheRead, cost, tokens }
}

function fmtTokens(n) {
  const v = Number(n) || 0
  if (v >= 1e9) return `${(v / 1e9).toFixed(2).replace('.', ',')} Mrd`
  if (v >= 1e6) return `${(v / 1e6).toFixed(2).replace('.', ',')} Mio`
  if (v >= 1e3) return `${Math.round(v / 1e3)} k`
  return String(Math.round(v))
}

function fmtCost(n) {
  const v = Number(n) || 0
  const s = v > 0 && v < 1 ? v.toFixed(3) : v.toFixed(2)
  return `$${s.replace('.', ',')}`
}

function shortModel(m) {
  if (!m) return '?'
  const s = String(m).split('/').pop()
  return s.length > 24 ? `${s.slice(0, 23)}…` : s
}

function clip(s, n) {
  const t = String(s || '')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

function Meter() {
  const live = useValue(host.state.focusedUsage)
  const storedId = useValue(host.state.focusedStoredSessionId)
  const [today, setToday] = useState(null)
  const [top, setTop] = useState(null)
  const [sess, setSess] = useState(null)
  const [offline, setOffline] = useState(false)
  const [mode, setMode] = useState(0) // 0 = zu, 1 = Modelle, 2 = Top-Chats

  useEffect(() => {
    let alive = true
    const load = async () => {
      if (!rest) return
      try {
        const t = await rest('/today')
        if (alive) {
          setToday(t)
          setOffline(false)
        }
      } catch (e) {
        if (alive) setOffline(true)
      }
      try {
        const tp = await rest(`/top?limit=${TOP_N}`)
        if (alive) setTop(tp)
      } catch (e) {
        /* backend without /top (older copy) — the chats view stays empty */
      }
      if (storedId) {
        try {
          const s = await rest(`/session/${encodeURIComponent(storedId)}`)
          if (alive) setSess(s)
        } catch (e) {
          /* session row may not exist yet on the first turn */
        }
      }
    }
    void load()
    const iv = setInterval(load, POLL_MS)
    return () => {
      alive = false
      clearInterval(iv)
    }
  }, [storedId])

  const liveU = readUsage(live)
  const sessTotals = liveU
    ? { tokens: liveU.tokens, cost: liveU.cost, input: liveU.input, output: liveU.output, cacheRead: liveU.cacheRead }
    : sess && sess.totals
      ? {
          tokens: sess.totals.tokens,
          cost: sess.totals.cost_usd,
          input: sess.totals.input_tokens,
          output: sess.totals.output_tokens,
          cacheRead: sess.totals.cache_read_tokens
        }
      : null
  const todayTotals = today && today.totals ? today.totals : null

  const dayText = todayTotals ? `${fmtCost(todayTotals.cost_usd)} · ${fmtTokens(todayTotals.tokens)} Tok` : offline ? '—' : '…'
  const chatText = sessTotals ? `${fmtCost(sessTotals.cost)} · ${fmtTokens(sessTotals.tokens)} Tok` : '—'

  const models = (today && today.by_model) || []
  const modelLine = models.length
    ? models
        .map(m => `${shortModel(m.model)}: ${fmtCost(m.cost_usd)} · ${fmtTokens(m.tokens)} Tok · ${Math.round(m.api_calls)} Calls`)
        .join('   ')
    : 'keine Daten'

  const topSessions = (top && top.sessions) || []

  const chipClass =
    'inline-flex items-center gap-1 whitespace-nowrap px-1.5 text-[0.6875rem] tabular-nums text-(--ui-text-tertiary) transition-colors hover:text-(--ui-text-secondary)'

  let detail = null
  if (mode === 1) {
    detail = jsx('div', {
      className: 'max-w-full truncate px-2 text-[0.625rem] text-(--ui-text-quaternary)',
      children: modelLine
    })
  } else if (mode === 2) {
    detail = jsx('div', {
      className: 'flex w-full max-w-[640px] flex-col gap-px px-2 text-[0.625rem] text-(--ui-text-quaternary)',
      children: topSessions.length
        ? topSessions.map((s, i) =>
            jsxs(
              'div',
              {
                className: 'flex w-full items-baseline gap-1.5',
                children: [
                  jsx('span', { className: 'w-3 shrink-0 text-right opacity-60', children: `${i + 1}.` }),
                  jsx('span', { className: 'min-w-0 flex-1 truncate', children: clip(s.title, 60) }),
                  jsx('span', {
                    className: 'shrink-0 tabular-nums',
                    children: `${fmtCost(s.cost_usd)} · ${fmtTokens(s.tokens)}`
                  }),
                  jsx('span', { className: 'w-14 shrink-0 text-right opacity-60', children: s.source })
                ]
              },
              s.session_id
            )
          )
        : jsx('div', { children: 'keine Daten' })
    })
  }

  return jsxs('div', {
    className: 'flex w-full flex-col items-center gap-0.5 pb-1',
    children: [
      detail,
      jsxs('button', {
        type: 'button',
        className: chipClass,
        title: 'Klick: Modelle → Top-Chats → zu',
        onClick: () => setMode(m => (m + 1) % 3),
        children: [
          jsx('span', { children: `heute ${dayText}` }),
          jsx('span', { className: 'opacity-40', children: '│' }),
          jsx('span', { children: `Chat ${chatText}` })
        ]
      })
    ]
  })
}

export default {
  id: ID,
  name: 'Usage Meter',
  register(ctx) {
    rest = path => ctx.rest(path)
    ctx.register({
      id: 'meter',
      area: COMPOSER_AREAS.underside,
      order: 90,
      render: () => jsx(Meter, {})
    })
  }
}

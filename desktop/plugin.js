/**
 * NE Observability. One Desktop page: instance + per-profile tokens, aux share,
 * models, skills triggered, subagents, permission issues.
 * Backend: ../dashboard/plugin_api.py (GET /report?days=N).
 */

import { useQuery, ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState } from 'react'

const PAGE_PATH = '/observability'
const RANGES = [1, 7, 30, 90]

const fmt = n => {
  const x = Number(n || 0)
  if (Math.abs(x) >= 1e9) return (x / 1e9).toFixed(1) + 'B'
  if (Math.abs(x) >= 1e6) return (x / 1e6).toFixed(1) + 'M'
  if (Math.abs(x) >= 1e3) return (x / 1e3).toFixed(1) + 'k'
  return String(Math.round(x))
}
const money = n => '$' + Number(n || 0).toFixed(2)
const when = ts => (ts ? new Date(ts * 1000).toLocaleString() : '')

const S = {
  page: { padding: '20px 24px', overflow: 'auto', height: '100%', color: 'var(--ui-text-primary)' },
  head: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 },
  h1: { fontSize: 18, fontWeight: 650, margin: 0, flex: 1 },
  h2: { fontSize: 13, fontWeight: 650, margin: '22px 0 8px', color: 'var(--ui-text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' },
  cards: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 },
  card: { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6, padding: '10px 12px' },
  cardLabel: { fontSize: 11, color: 'var(--ui-text-tertiary)' },
  cardVal: { fontSize: 20, fontWeight: 650, marginTop: 2 },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th: { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--ui-stroke-secondary)', color: 'var(--ui-text-tertiary)', fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap' },
  td: { padding: '5px 8px', borderBottom: '1px solid color-mix(in srgb, var(--ui-stroke-secondary) 50%, transparent)', whiteSpace: 'nowrap' },
  muted: { color: 'var(--ui-text-tertiary)', fontSize: 12 },
  seg: on => ({ border: '1px solid var(--ui-stroke-secondary)', background: on ? 'color-mix(in srgb, var(--ui-accent) 18%, transparent)' : 'transparent', color: on ? 'var(--ui-text-primary)' : 'var(--ui-text-tertiary)', borderRadius: 5, padding: '3px 10px', fontSize: 12, cursor: 'pointer', fontWeight: on ? 650 : 400 }),
  select: { background: 'transparent', color: 'var(--ui-text-primary)', border: '1px solid var(--ui-stroke-secondary)', borderRadius: 5, padding: '3px 6px', fontSize: 12 },
}

function Card({ label, value }) {
  return jsxs('div', { style: S.card, children: [jsx('div', { style: S.cardLabel, children: label }), jsx('div', { style: S.cardVal, children: value })] })
}

function Table({ cols, rows, empty }) {
  const [sort, setSort] = useState(null)
  if (!rows || rows.length === 0) return jsx('div', { style: S.muted, children: empty || 'Nothing yet.' })
  let data = rows
  if (sort) {
    const c = cols[sort.i]
    const v = r => (c.sortValue ? c.sortValue(r) : r[c.key])
    data = [...rows].sort((a, b) => {
      const x = v(a), y = v(b)
      const d = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return sort.desc ? -d : d
    })
  }
  return jsxs('table', {
    style: S.table,
    children: [
      jsx('thead', { children: jsx('tr', { children: cols.map((c, i) => jsx('th', {
        style: { ...S.th, textAlign: c.num ? 'right' : 'left' },
        onClick: () => setSort(s => ({ i, desc: s && s.i === i ? !s.desc : true })),
        children: c.label + (sort && sort.i === i ? (sort.desc ? ' ▾' : ' ▴') : ''),
      }, i)) }) }),
      jsx('tbody', { children: data.map((r, ri) => jsx('tr', { children: cols.map((c, i) => jsx('td', {
        style: { ...S.td, textAlign: c.num ? 'right' : 'left' },
        children: c.render ? c.render(r) : r[c.key],
      }, i)) }, ri)) }),
    ],
  })
}

function ObsPage({ ctx }) {
  const [days, setDays] = useState(30)
  const [profile, setProfile] = useState('')
  const [board, setBoard] = useState('')
  const q = useQuery({
    queryKey: ['ne-observability', days, board],
    queryFn: () => ctx.rest('/report?days=' + days + (board ? '&board=' + encodeURIComponent(board) : '')),
    keepPreviousData: true,
    refetchInterval: 60000,
  })
  const r = q.data
  const pick = rows => (profile && rows ? rows.filter(x => x.profile === profile) : rows || [])

  let body
  if (q.isLoading) body = jsx('div', { style: S.muted, children: 'Loading…' })
  else if (q.error || !r) body = jsx('div', { style: S.muted, children: 'Backend unavailable. Enable the ne-observability plugin in this profile and restart.' })
  else {
    const prof = profile ? r.profiles.find(p => p.profile === profile) : null
    const top = prof || r.instance
    const profSkills = profile ? pick(r.skills_by_profile) : r.skills
    body = jsxs('div', {
      children: [
        jsxs('div', { style: S.cards, children: [
          jsx(Card, { label: 'Sessions', value: fmt(top.sessions) }),
          jsx(Card, { label: 'Main tokens', value: fmt(top.main_tokens) }),
          jsx(Card, { label: 'Aux tokens', value: fmt(top.aux_tokens) }),
          jsx(Card, { label: 'Aux share (calls)', value: (top.aux_call_pct || 0) + '%' }),
          jsx(Card, { label: 'Cache-read tokens', value: fmt(top.cache_read_tokens) }),
          jsx(Card, { label: 'Cost (reported)', value: money(top.cost_usd) }),
        ] }),

        !profile && jsx('h2', { style: S.h2, children: 'By profile' }),
        !profile && jsx(Table, { rows: r.profiles, cols: [
          { label: 'Profile', key: 'profile', render: x => jsx('a', { style: { cursor: 'pointer', color: 'var(--ui-accent)' }, onClick: () => setProfile(x.profile), children: x.profile }) },
          { label: 'Sessions', key: 'sessions', num: true },
          { label: 'Main calls', key: 'main_calls', num: true, render: x => fmt(x.main_calls) },
          { label: 'Aux calls', key: 'aux_calls', num: true, render: x => fmt(x.aux_calls) },
          { label: 'Aux % calls', key: 'aux_call_pct', num: true, render: x => x.aux_call_pct + '%' },
          { label: 'Main tokens', key: 'main_tokens', num: true, render: x => fmt(x.main_tokens) },
          { label: 'Aux tokens', key: 'aux_tokens', num: true, render: x => fmt(x.aux_tokens) },
          { label: 'Cost', key: 'cost_usd', num: true, render: x => money(x.cost_usd) },
        ] }),

        jsx('h2', { style: S.h2, children: 'Crons (LLM usage)' }),
        jsx(Table, { rows: pick(r.crons), empty: board ? 'Crons do not run on a Kanban board. Clear the board filter to see them.' : 'No cron LLM usage in range.', cols: [
          { label: 'Profile', key: 'profile' },
          { label: 'Job', key: 'job', render: x => jsx('span', { title: x.job_id + (x.enabled === false ? ' (disabled)' : ''), style: x.enabled === false ? { color: 'var(--ui-text-tertiary)' } : undefined, children: x.job }) },
          { label: 'Schedule', key: 'schedule' },
          { label: 'Runs', key: 'runs', num: true },
          { label: 'Main calls', key: 'main_calls', num: true, render: x => fmt(x.main_calls) },
          { label: 'Aux calls', key: 'aux_calls', num: true, render: x => fmt(x.aux_calls) },
          { label: 'Input', key: 'input_tokens', num: true, render: x => fmt(x.input_tokens) },
          { label: 'Output', key: 'output_tokens', num: true, render: x => fmt(x.output_tokens) },
          { label: 'Tokens / run', key: 'per_run', num: true, sortValue: x => x.tokens / (x.runs || 1), render: x => fmt(x.tokens / (x.runs || 1)) },
          { label: 'Cost', key: 'cost_usd', num: true, render: x => money(x.cost_usd) },
          { label: 'Models', key: 'models', render: x => (x.models || []).join(', ') },
          { label: 'Last', key: 'last_ts', render: x => when(x.last_ts) },
        ] }),

        jsx('h2', { style: S.h2, children: 'Aux tasks' }),
        jsx(Table, { rows: pick(r.aux_tasks), empty: 'No aux calls in range.', cols: [
          { label: 'Profile', key: 'profile' },
          { label: 'Aux task', key: 'aux_task' },
          { label: 'Calls', key: 'calls', num: true },
          { label: 'Tokens', key: 'tokens', num: true, render: x => fmt(x.tokens) },
          { label: 'Models', key: 'models', render: x => (x.models || []).join(', ') },
        ] }),

        !profile && jsx('h2', { style: S.h2, children: 'Models (instance)' }),
        !profile && jsx(Table, { rows: r.models, cols: [
          { label: 'Model', key: 'model' },
          { label: 'Provider', key: 'provider' },
          { label: 'Role', key: 'role' },
          { label: 'Calls', key: 'calls', num: true, render: x => fmt(x.calls) },
          { label: 'Input', key: 'input_tokens', num: true, render: x => fmt(x.input_tokens) },
          { label: 'Output', key: 'output_tokens', num: true, render: x => fmt(x.output_tokens) },
          { label: 'Cache read', key: 'cache_read_tokens', num: true, render: x => fmt(x.cache_read_tokens) },
          { label: 'Cost', key: 'cost_usd', num: true, render: x => money(x.cost_usd) },
        ] }),

        jsx('h2', { style: S.h2, children: 'Skills triggered' }),
        jsx(Table, { rows: profSkills, empty: 'No skill loads captured yet.', cols: profile
          ? [{ label: 'Skill', key: 'skill' }, { label: 'Triggers', key: 'triggers', num: true }]
          : [{ label: 'Skill', key: 'skill' }, { label: 'Triggers', key: 'triggers', num: true }, { label: 'Profiles', key: 'profiles', num: true }, { label: 'Last', key: 'last_ts', render: x => when(x.last_ts) }] }),

        jsx('h2', { style: S.h2, children: 'Subagents' }),
        jsx(Table, { rows: pick(r.subagents), empty: 'No subagents captured yet.', cols: [
          { label: 'Profile', key: 'profile' },
          { label: 'Spawned', key: 'spawned', num: true },
          { label: 'Finished', key: 'finished', num: true },
          { label: 'Not ok', key: 'not_ok', num: true, render: x => x.not_ok || 0 },
          { label: 'Avg seconds', key: 'avg_seconds', num: true, render: x => x.avg_seconds || 0 },
        ] }),

        jsx('h2', { style: S.h2, children: 'Permission issues' }),
        jsx(Table, { rows: pick(r.permissions), empty: 'No approvals or permission issues captured yet.', cols: [
          { label: 'Profile', key: 'profile' },
          { label: 'Issues', key: 'issues', num: true },
          { label: 'Approvals asked', key: 'approvals_requested', num: true },
          { label: 'Denied / timed out', key: 'approvals_denied_or_timed_out', num: true, render: x => x.approvals_denied_or_timed_out || 0 },
          { label: 'Tools blocked', key: 'tools_blocked', num: true, render: x => x.tools_blocked || 0 },
          { label: 'Permission errors', key: 'tool_permission_errors', num: true, render: x => x.tool_permission_errors || 0 },
          { label: 'Provider 401/403', key: 'provider_auth_errors', num: true, render: x => x.provider_auth_errors || 0 },
        ] }),
        pick(r.permission_issues).length > 0 && jsx('h2', { style: S.h2, children: 'Recent permission issues' }),
        pick(r.permission_issues).length > 0 && jsx(Table, { rows: pick(r.permission_issues), cols: [
          { label: 'When', key: 'ts', render: x => when(x.ts) },
          { label: 'Profile', key: 'profile' },
          { label: 'Kind', key: 'kind' },
          { label: 'Name', key: 'name' },
          { label: 'Status', key: 'status' },
          { label: 'Detail', key: 'detail', render: x => { try { const d = JSON.parse(x.detail || '{}'); return String(d.error || d.description || '').slice(0, 120) } catch (e) { return '' } } },
        ] }),

        jsx('div', { style: { ...S.muted, marginTop: 20 }, children:
          'Tokens and models: every profile\'s state.db (full history). Skills, subagents and permissions: hook events'
          + (r.since ? ' since ' + when(r.since) + '.' : ', none captured yet.')
          + (board ? ' Board filter: Kanban worker sessions (and their subagents) matched to the board\'s task runs by profile and start time.' : '') }),
      ],
    })
  }

  const profiles = ((r && r.profiles) || []).map(p => p.profile)
  if (profile && !profiles.includes(profile)) profiles.unshift(profile)
  const boards = (r && r.boards) || []
  const boardName = (boards.find(b => b.slug === board) || {}).name || board
  const title = ['Observability', profile, board && 'board ' + boardName].filter(Boolean).join(': ')
  return jsxs('div', {
    style: S.page,
    children: [
      jsxs('div', { style: S.head, children: [
        jsx('h1', { style: S.h1, children: title }),
        jsxs('select', { style: S.select, value: profile, onChange: e => setProfile(e.target.value), children: [
          jsx('option', { value: '', children: 'All profiles' }),
          ...profiles.map(p => jsx('option', { value: p, children: p }, p)),
        ] }),
        jsxs('select', { style: S.select, value: board, title: 'Filter by Kanban board', onChange: e => setBoard(e.target.value), children: [
          jsx('option', { value: '', children: 'All boards' }),
          ...boards.map(b => jsx('option', { value: b.slug, children: b.name }, b.slug)),
        ] }),
        jsx('div', { style: { display: 'flex', gap: 4 }, children: RANGES.map(d => jsx('button', { style: S.seg(d === days), onClick: () => setDays(d), children: d + 'd' }, d)) }),
      ] }),
      body,
    ],
  })
}

export default {
  id: 'ne-observability',
  name: 'Observability',
  defaultEnabled: true,
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PAGE_PATH }, render: () => jsx(ObsPage, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, order: 46, data: { path: PAGE_PATH, label: 'Observability', codicon: 'graph' } },
    ])
  },
}

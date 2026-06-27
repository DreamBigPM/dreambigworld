import 'dotenv/config'

const API_KEY = process.env.RENTVINE_API_KEY!
const BASE_URL = process.env.RENTVINE_BASE_URL || 'https://api.rentvine.com/v1'

async function request(path: string, params: Record<string, string> = {}): Promise<any> {
  const url = new URL(`${BASE_URL}${path}`)
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v)

  const res = await fetch(url.toString(), {
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'X-API-Key': API_KEY,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    },
  })

  if (!res.ok) throw new Error(`Rentvine API ${path} → ${res.status} ${res.statusText}`)
  return res.json()
}

async function fetchAllPages(path: string, params: Record<string, string> = {}): Promise<any[]> {
  const records: any[] = []
  let page = 1
  while (true) {
    const data = await request(path, { ...params, page: String(page), pageSize: '100' })
    const items = data.data ?? data.items ?? data.results ?? data ?? []
    if (!Array.isArray(items) || items.length === 0) break
    records.push(...items)
    const total = data.total ?? data.totalCount ?? data.totalItems
    if (!total || records.length >= total) break
    page++
  }
  return records
}

export async function fetchPortfolios(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/portfolios', params)
}

export async function fetchProperties(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/properties', params)
}

export async function fetchUnits(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/units', params)
}

export async function fetchLeases(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/leases', params)
}

export async function fetchTenants(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/tenants', params)
}

export async function fetchVendors(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/vendors', params)
}

export async function fetchWorkOrders(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/workOrders', params)
}

export async function fetchTransactions(since?: string) {
  const params: Record<string, string> = {}
  if (since) params.updatedSince = since
  return fetchAllPages('/transactions', params)
}

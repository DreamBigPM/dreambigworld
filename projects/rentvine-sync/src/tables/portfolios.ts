import { fetchPortfolios } from '../rentvine.js'
import { upsertRecords } from '../supabase.js'

export async function syncPortfolios(since?: string): Promise<number> {
  const raw = await fetchPortfolios(since)
  const records = raw.map((r: any) => ({
    rentvine_id: String(r.id ?? r.portfolioId),
    name: r.name ?? r.portfolioName ?? null,
    owner_name: r.ownerName ?? r.owner?.name ?? null,
    owner_email: r.ownerEmail ?? r.owner?.email ?? null,
    raw_data: r,
    synced_at: new Date().toISOString(),
  }))
  return upsertRecords('portfolios', records)
}

import { fetchProperties } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncProperties(since?: string): Promise<number> {
  const raw = await fetchProperties(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const portfolioRentvineId = String(r.portfolioId ?? r.portfolio?.id ?? '')
    const portfolioId = portfolioRentvineId
      ? await lookupSupabaseId('portfolios', portfolioRentvineId)
      : null
    return {
      rentvine_id: String(r.id ?? r.propertyId),
      name: r.name ?? r.propertyName ?? null,
      address: r.address?.street ?? r.street ?? r.address ?? null,
      city: r.address?.city ?? r.city ?? null,
      state: r.address?.state ?? r.state ?? null,
      zip: r.address?.zip ?? r.address?.postalCode ?? r.zip ?? null,
      portfolio_id: portfolioId,
      unit_count: r.unitCount ?? r.units?.length ?? null,
      property_type: r.type ?? r.propertyType ?? null,
      year_built: r.yearBuilt ?? null,
      reserve: r.reserve ?? null,
      contract_start: r.contractStartDate ?? r.contractStart ?? null,
      contract_end: r.contractEndDate ?? r.contractEnd ?? null,
      maintenance_notes: r.maintenanceNotes ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('properties', records)
}

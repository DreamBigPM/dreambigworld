import { fetchUnits } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncUnits(since?: string): Promise<number> {
  const raw = await fetchUnits(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const propertyRentvineId = String(r.propertyId ?? r.property?.id ?? '')
    const propertyId = propertyRentvineId
      ? await lookupSupabaseId('properties', propertyRentvineId)
      : null
    return {
      rentvine_id: String(r.id ?? r.unitId),
      unit_number: r.unitNumber ?? r.unit ?? r.name ?? null,
      property_id: propertyId,
      bedrooms: r.bedrooms ?? r.beds ?? null,
      bathrooms: r.bathrooms ?? r.baths ?? null,
      square_feet: r.squareFeet ?? r.sqft ?? null,
      status: r.status ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('units', records)
}

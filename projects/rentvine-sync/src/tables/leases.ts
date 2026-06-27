import { fetchLeases } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncLeases(since?: string): Promise<number> {
  const raw = await fetchLeases(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const unitRentvineId = String(r.unitId ?? r.unit?.id ?? '')
    const unitId = unitRentvineId
      ? await lookupSupabaseId('units', unitRentvineId)
      : null
    return {
      rentvine_id: String(r.id ?? r.leaseId),
      unit_id: unitId,
      start_date: r.startDate ?? r.leaseStartDate ?? null,
      end_date: r.endDate ?? r.leaseEndDate ?? null,
      move_in_date: r.moveInDate ?? r.moveIn ?? null,
      monthly_rent: r.monthlyRent ?? r.rentAmount ?? r.rent ?? null,
      status: r.status ?? r.leaseStatus ?? null,
      lease_type: r.leaseType ?? r.type ?? null,
      portal_access: r.portalAccess ?? r.tenantPortalEnabled ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('leases', records)
}

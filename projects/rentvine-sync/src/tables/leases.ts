import { fetchLeases } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

async function mapLease(r: any): Promise<object> {
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
}

export async function syncLeases(since?: string): Promise<number> {
  // Active leases — incremental on delta syncs
  const activeRaw = await fetchLeases(since, 'Active')

  // Closed leases — always pull without a `since` cutoff so historical
  // renewals (where the old lease closed before the sync was set up) are
  // captured. On a full sync this is the same behaviour as before; on delta
  // syncs it ensures newly-closed leases and any previously-missed history
  // both land in Supabase.
  const closedRaw = await fetchLeases(undefined, 'Closed')

  const allRaw = [...activeRaw, ...closedRaw]
  const records = await Promise.all(allRaw.map(mapLease))
  return upsertRecords('leases', records)
}

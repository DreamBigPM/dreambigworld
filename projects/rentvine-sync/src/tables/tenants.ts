import { fetchTenants } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncTenants(since?: string): Promise<number> {
  const raw = await fetchTenants(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const leaseRentvineId = String(r.leaseId ?? r.lease?.id ?? '')
    const leaseId = leaseRentvineId
      ? await lookupSupabaseId('leases', leaseRentvineId)
      : null
    return {
      rentvine_id: String(r.id ?? r.tenantId ?? r.contactId),
      lease_id: leaseId,
      first_name: r.firstName ?? r.first ?? null,
      last_name: r.lastName ?? r.last ?? null,
      email: r.email ?? r.emailAddress ?? null,
      phone: r.phone ?? r.phoneNumber ?? r.mobilePhone ?? null,
      status: r.status ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('tenants', records)
}

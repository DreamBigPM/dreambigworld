import { fetchVendors } from '../rentvine.js'
import { upsertRecords } from '../supabase.js'

export async function syncVendors(since?: string): Promise<number> {
  const raw = await fetchVendors(since)
  const records = raw.map((r: any) => ({
    rentvine_id: String(r.id ?? r.vendorId ?? r.contactId),
    name: r.name ?? r.vendorName ?? r.displayName ?? null,
    email: r.email ?? r.emailAddress ?? null,
    phone: r.phone ?? r.phoneNumber ?? r.mobilePhone ?? null,
    trade: r.trade ?? r.primaryTrade ?? null,
    status: r.status ?? (r.isActive ? 'Active' : 'Inactive') ?? null,
    raw_data: r,
    synced_at: new Date().toISOString(),
  }))
  return upsertRecords('vendors', records)
}

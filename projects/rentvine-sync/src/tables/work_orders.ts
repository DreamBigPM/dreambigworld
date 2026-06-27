import { fetchWorkOrders } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncWorkOrders(since?: string): Promise<number> {
  const raw = await fetchWorkOrders(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const propertyRentvineId = String(r.propertyId ?? r.property?.id ?? '')
    const unitRentvineId = String(r.unitId ?? r.unit?.id ?? '')
    const vendorRentvineId = String(r.vendorId ?? r.vendor?.id ?? '')
    const [propertyId, unitId, vendorId] = await Promise.all([
      propertyRentvineId ? lookupSupabaseId('properties', propertyRentvineId) : null,
      unitRentvineId ? lookupSupabaseId('units', unitRentvineId) : null,
      vendorRentvineId ? lookupSupabaseId('vendors', vendorRentvineId) : null,
    ])
    return {
      rentvine_id: String(r.id ?? r.workOrderId),
      property_id: propertyId,
      unit_id: unitId,
      vendor_id: vendorId,
      title: r.title ?? r.subject ?? r.description?.substring(0, 100) ?? null,
      description: r.description ?? r.notes ?? null,
      status: r.status ?? r.workOrderStatus ?? null,
      priority: r.priority ?? null,
      source: r.source ?? null,
      owner_approved: r.ownerApproved ?? null,
      shared_with_tenant: r.sharedWithTenant ?? null,
      shared_with_owner: r.sharedWithOwner ?? null,
      estimated_cost: r.estimatedCost ?? r.estimate ?? null,
      actual_cost: r.actualCost ?? r.cost ?? null,
      opened_at: r.openedAt ?? r.createdAt ?? r.dateOpened ?? null,
      closed_at: r.closedAt ?? r.dateClosed ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('work_orders', records)
}

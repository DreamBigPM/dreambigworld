import { fetchTransactions } from '../rentvine.js'
import { upsertRecords, lookupSupabaseId } from '../supabase.js'

export async function syncTransactions(since?: string): Promise<number> {
  const raw = await fetchTransactions(since)
  const records = await Promise.all(raw.map(async (r: any) => {
    const leaseRentvineId = String(r.leaseId ?? r.lease?.id ?? '')
    const leaseId = leaseRentvineId
      ? await lookupSupabaseId('leases', leaseRentvineId)
      : null
    return {
      rentvine_id: String(r.id ?? r.transactionId),
      lease_id: leaseId,
      amount: r.amount ?? r.total ?? null,
      transaction_type: r.type ?? r.transactionType ?? null,
      description: r.description ?? r.memo ?? null,
      transaction_date: r.date ?? r.transactionDate ?? null,
      due_date: r.dueDate ?? null,
      status: r.status ?? null,
      raw_data: r,
      synced_at: new Date().toISOString(),
    }
  }))
  return upsertRecords('transactions', records)
}

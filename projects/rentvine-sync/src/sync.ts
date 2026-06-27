import 'dotenv/config'
import { getLastSyncTime, logSyncRun } from './supabase.js'
import { syncPortfolios } from './tables/portfolios.js'
import { syncProperties } from './tables/properties.js'
import { syncVendors } from './tables/vendors.js'
import { syncUnits } from './tables/units.js'
import { syncLeases } from './tables/leases.js'
import { syncTenants } from './tables/tenants.js'
import { syncWorkOrders } from './tables/work_orders.js'
import { syncTransactions } from './tables/transactions.js'

async function main() {
  const startedAt = new Date()
  let totalRecords = 0
  let errorMessage: string | undefined

  const forceFull = process.env.FORCE_FULL_SYNC === 'true'
  const lastSync = forceFull ? null : await getLastSyncTime()
  const runType = lastSync ? 'delta' : 'full'
  const since = lastSync ?? undefined

  console.log(`[sync] Starting ${runType} sync${since ? ` (since ${since})` : ''}`)

  // Order matters: parents before children for FK resolution
  const steps = [
    { name: 'portfolios',   fn: () => syncPortfolios(since) },
    { name: 'properties',   fn: () => syncProperties(since) },
    { name: 'vendors',      fn: () => syncVendors(since) },
    { name: 'units',        fn: () => syncUnits(since) },
    { name: 'leases',       fn: () => syncLeases(since) },
    { name: 'tenants',      fn: () => syncTenants(since) },
    { name: 'work_orders',  fn: () => syncWorkOrders(since) },
    { name: 'transactions', fn: () => syncTransactions(since) },
  ]

  for (const step of steps) {
    try {
      const count = await step.fn()
      totalRecords += count
      console.log(`[sync] ${step.name}: ${count} records`)
    } catch (err: any) {
      console.error(`[sync] ${step.name} failed:`, err.message)
      errorMessage = errorMessage
        ? `${errorMessage}; ${step.name}: ${err.message}`
        : `${step.name}: ${err.message}`
    }
  }

  const duration = Date.now() - startedAt.getTime()
  const status = errorMessage && totalRecords === 0 ? 'error' : 'success'

  await logSyncRun({
    run_type: runType,
    record_count: totalRecords,
    duration_ms: duration,
    status,
    error_message: errorMessage,
    started_at: startedAt,
  })

  console.log(`[sync] Done — ${totalRecords} records in ${duration}ms (${status})`)
  if (errorMessage) console.warn(`[sync] Errors: ${errorMessage}`)
}

main().catch((err) => {
  console.error('[sync] Fatal error:', err)
  process.exit(1)
})

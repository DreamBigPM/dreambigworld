import 'dotenv/config'
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
)

export async function upsertRecords(table: string, records: any[]): Promise<number> {
  if (records.length === 0) return 0
  const { error } = await supabase
    .from(table)
    .upsert(records, { onConflict: 'rentvine_id' })
  if (error) throw new Error(`Supabase upsert ${table}: ${error.message}`)
  return records.length
}

export async function lookupSupabaseId(table: string, rentvineId: string): Promise<string | null> {
  const { data } = await supabase
    .from(table)
    .select('id')
    .eq('rentvine_id', rentvineId)
    .single()
  return data?.id ?? null
}

export async function getLastSyncTime(): Promise<string | null> {
  const { data } = await supabase
    .from('sync_log')
    .select('completed_at')
    .eq('status', 'success')
    .order('completed_at', { ascending: false })
    .limit(1)
    .single()
  return data?.completed_at ?? null
}

export async function logSyncRun(entry: {
  run_type: 'full' | 'delta'
  record_count: number
  duration_ms: number
  status: 'success' | 'error'
  error_message?: string
  started_at: Date
}): Promise<void> {
  await supabase.from('sync_log').insert({
    table_name: 'all',
    run_type: entry.run_type,
    record_count: entry.record_count,
    duration_ms: entry.duration_ms,
    status: entry.status,
    error_message: entry.error_message ?? null,
    started_at: entry.started_at.toISOString(),
    completed_at: new Date().toISOString(),
  })
}

export { supabase }

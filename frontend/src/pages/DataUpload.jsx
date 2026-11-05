import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Database, Download, Upload, XCircle } from 'lucide-react'
import { errorMessage } from '../api/client'
import {
  deleteUpload, downloadTemplate, getReport, getStats, getUploads, ingestFailure, loadSample, uploadFile,
} from '../api/data'
import { useFilters } from '../context/FilterContext'
import { PageShell } from '../components/common/PageShell'
import { ErrorBanner, Spinner } from '../components/common/Feedback'
import Dropzone, { checkFile } from '../components/data/Dropzone'
import ValidationReport from '../components/data/ValidationReport'
import DatasetStats from '../components/data/DatasetStats'
import PreviewTable from '../components/data/PreviewTable'
import UploadHistory from '../components/data/UploadHistory'

function FailureCard({ failure, onDismiss }) {
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5">
      <div className="flex items-start gap-3">
        <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-sev-crit" aria-hidden="true" />
        <div className="flex-1">
          <h2 className="text-base font-semibold text-red-900">{failure.title ?? 'The file was not accepted'}</h2>
          <p className="mt-1 text-sm text-red-800">{failure.message}</p>
          {failure.details?.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-red-800">
              {failure.details.map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          )}
          <p className="mt-3 text-xs text-red-700">Nothing from this file was stored. Fix the issue and upload again.</p>
        </div>
        <button onClick={onDismiss} className="text-sm font-medium text-red-700 hover:underline">Dismiss</button>
      </div>
    </div>
  )
}

function ConfirmDelete({ upload, busy, onCancel, onConfirm }) {
  if (!upload) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" role="dialog" aria-modal="true" aria-labelledby="del-title">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-sev-warn" aria-hidden="true" />
          <div>
            <h2 id="del-title" className="text-base font-semibold text-slate-900">Delete this upload?</h2>
            <p className="mt-1 text-sm text-slate-600">
              “{upload.filename}” and the {upload.rows_valid.toLocaleString()} rows it stored will be removed from the dashboard and analytics. This cannot be undone.
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} disabled={busy} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</button>
          <button onClick={onConfirm} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-60">
            {busy && <Spinner />} Delete
          </button>
        </div>
      </div>
    </div>
  )
}

export default function DataUpload() {
  const { refreshDataRange } = useFilters()
  const [stats, setStats] = useState(null)
  const [uploads, setUploads] = useState(null)
  const [loadingMeta, setLoadingMeta] = useState(true)
  const [metaError, setMetaError] = useState('')

  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [result, setResult] = useState(null)   // { filename, report }
  const [failure, setFailure] = useState(null) // { message, details }
  const [refreshKey, setRefreshKey] = useState(0)

  const [toDelete, setToDelete] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  const refresh = useCallback(async () => {
    setMetaError('')
    try {
      const [s, u] = await Promise.all([getStats(), getUploads()])
      setStats(s.data)
      setUploads(u.data)
    } catch (e) {
      setMetaError(errorMessage(e, 'Could not load dataset information.'))
    } finally {
      setLoadingMeta(false)
    }
    setRefreshKey((k) => k + 1)
    refreshDataRange() // the date presets are anchored to the newest stored data
  }, [refreshDataRange])

  useEffect(() => { refresh() }, [refresh])

  const run = async (promiseFactory, fallbackName) => {
    setBusy(true)
    setProgress(null)
    setFailure(null)
    setResult(null)
    try {
      const { data } = await promiseFactory()
      setResult({ filename: data.upload.filename || fallbackName, report: data.report })
    } catch (e) {
      const f = ingestFailure(e)
      setFailure(f ?? { message: errorMessage(e, 'The upload failed. Please try again.'), details: [] })
    } finally {
      setBusy(false)
      setProgress(null)
      refresh()
    }
  }

  const onFile = (file) => run(() => uploadFile(file, setProgress), file.name)
  const onSample = () => run(() => loadSample(), 'hospital_operations.csv')

  const viewReport = async (u) => {
    setFailure(null)
    setResult(null)
    try {
      const { data } = await getReport(u.id)
      if (u.status === 'success') setResult({ filename: u.filename, report: data.report })
      else setFailure({ title: `Upload “${u.filename}” failed`, message: data.report.error ?? 'Processing failed.', details: data.report.details ?? [] })
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e) {
      setFailure({ message: errorMessage(e, 'Could not load that report.'), details: [] })
    }
  }

  const pickRef = useRef(null)
  const pick = (file) => {
    if (!file) return
    const problem = checkFile(file)
    if (problem) { setResult(null); setFailure({ message: problem, details: [] }); return }
    onFile(file)
  }

  const confirmDelete = async () => {
    setDeletingId(toDelete.id)
    try {
      await deleteUpload(toDelete.id)
      if (result) setResult(null)
      setToDelete(null)
      await refresh()
    } catch (e) {
      setToDelete(null)
      setFailure({ message: errorMessage(e, 'Could not delete the upload.'), details: [] })
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <PageShell
      title="Data Upload & Management"
      description="Upload hospital operational data. It is validated, cleaned and turned into analytics-ready features."
      actions={
        <>
          <input ref={pickRef} type="file" accept=".csv,.xlsx" className="sr-only" aria-label="Upload a dataset file" tabIndex={-1}
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <button onClick={() => pickRef.current?.click()} disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:opacity-50">
            <Upload className="h-4 w-4" /> Upload dataset
          </button>
          <button onClick={() => downloadTemplate().catch(() => setFailure({ message: 'Could not download the template.', details: [] }))}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            <Download className="h-4 w-4" /> Template
          </button>
          <button onClick={onSample} disabled={busy}
            className="inline-flex items-center gap-2 rounded-lg border border-brand-700 bg-white px-3 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-50 disabled:opacity-50">
            <Database className="h-4 w-4" /> Load sample dataset
          </button>
        </>
      }
    >
      <Dropzone onFile={onFile} busy={busy} progress={progress} onClientError={(m) => { setResult(null); setFailure({ message: m, details: [] }) }} />

      {failure && <FailureCard failure={failure} onDismiss={() => setFailure(null)} />}
      {result && <ValidationReport filename={result.filename} report={result.report} />}

      <ErrorBanner message={metaError} onRetry={refresh} />
      <DatasetStats stats={stats} loading={loadingMeta} />
      <PreviewTable refreshKey={refreshKey} />
      <UploadHistory uploads={uploads} loading={loadingMeta} busyId={deletingId} onView={viewReport} onDelete={setToDelete} />

      <ConfirmDelete upload={toDelete} busy={deletingId != null} onCancel={() => setToDelete(null)} onConfirm={confirmDelete} />
    </PageShell>
  )
}

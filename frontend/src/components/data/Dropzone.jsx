import { useRef, useState } from 'react'
import { FileSpreadsheet, UploadCloud } from 'lucide-react'
import { Spinner } from '../common/Feedback'

const MAX_MB = 10
const ALLOWED = ['.csv', '.xlsx']

/** Cheap client-side checks shared by the drop zone and the header button. Returns an error message or null. */
export function checkFile(file) {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!ALLOWED.includes(ext)) return `"${file.name}" is not supported. Upload a .csv or .xlsx file.`
  if (file.size > MAX_MB * 1024 * 1024) return `The file is larger than the ${MAX_MB} MB limit.`
  if (file.size === 0) return 'The file is empty.'
  return null
}

/** Drag-and-drop or click to choose a file. Does cheap client-side checks; the server re-validates everything. */
export default function Dropzone({ onFile, busy, progress, onClientError }) {
  const inputRef = useRef(null)
  const [over, setOver] = useState(false)

  const take = (file) => {
    if (!file) return
    const problem = checkFile(file)
    if (problem) return onClientError(problem)
    onFile(file)
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!busy) setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!busy) take(e.dataTransfer.files?.[0]) }}
      className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
        over ? 'border-brand-600 bg-brand-50' : 'border-slate-300 bg-white'
      } ${busy ? 'opacity-90' : ''}`}
    >
      <input ref={inputRef} type="file" accept=".csv,.xlsx" className="sr-only" aria-label="Choose a dataset file"
        onChange={(e) => { take(e.target.files?.[0]); e.target.value = '' }} />

      {busy ? (
        <div className="mx-auto max-w-xs" role="status" aria-live="polite">
          <Spinner className="mx-auto h-8 w-8 text-brand-600" />
          <p className="mt-3 text-sm font-medium text-slate-700">
            {progress != null && progress < 100 ? `Uploading… ${progress}%` : 'Validating and processing…'}
          </p>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div className={`h-full bg-brand-600 transition-all ${progress == null || progress >= 100 ? 'w-full animate-pulse' : ''}`}
              style={progress != null && progress < 100 ? { width: `${progress}%` } : undefined} />
          </div>
        </div>
      ) : (
        <>
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-700">
            <UploadCloud className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-slate-800">Drag a dataset here, or</p>
          <button type="button" onClick={() => inputRef.current?.click()}
            className="mt-2 inline-flex items-center gap-2 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800">
            <FileSpreadsheet className="h-4 w-4" /> Choose CSV or Excel file
          </button>
          <p className="mt-3 text-xs text-slate-500">
            .csv or .xlsx, up to {MAX_MB} MB. Operational data only. Files with patient names, phone numbers or addresses are rejected.
          </p>
        </>
      )}
    </div>
  )
}

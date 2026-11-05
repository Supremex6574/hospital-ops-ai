import api from './client'

const LONG = { timeout: 180000 } // processing a full year of hourly data takes a few seconds

export const uploadFile = (file, onProgress) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/data/upload', form, {
    ...LONG,
    onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
  })
}

export const loadSample = () => api.post('/data/load-sample', null, LONG)
export const getStats = () => api.get('/data/stats')
export const getPreview = (params) => api.get('/data/preview', { params })
export const getUploads = () => api.get('/data/uploads')
export const getReport = (id) => api.get(`/data/uploads/${id}/report`)
export const deleteUpload = (id) => api.delete(`/data/uploads/${id}`)

export async function downloadTemplate() {
  const { data } = await api.get('/data/template', { responseType: 'blob' })
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = 'hospital_data_template.csv'
  a.click()
  URL.revokeObjectURL(url)
}

/** Pull a user-facing message plus per-item details out of a failed upload response. */
export function ingestFailure(error) {
  const d = error.response?.data
  if (error.response?.status === 422 && d?.ingest_code) {
    return { message: d.detail, details: d.details || [] }
  }
  return null
}

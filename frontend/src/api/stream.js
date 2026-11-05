import api from './client'

export const getStreamStatus = () => api.get('/stream/status')
export const startStream = (interval_seconds) => api.post('/stream/start', { interval_seconds })
export const stopStream = () => api.post('/stream/stop')
export const stepStream = (hours) => api.post('/stream/step', { hours }, { timeout: 60000 })
export const injectSurge = (department, hours) => api.post('/stream/surge', { department, hours })
export const getSources = () => api.get('/integration/sources')

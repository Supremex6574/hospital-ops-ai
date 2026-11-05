import api from './client'

export const getAlerts = (params) => api.get('/alerts', { params })
export const getAlertSummary = () => api.get('/alerts/summary')
export const scanAlerts = () => api.post('/alerts/scan')
export const acknowledgeAlert = (id) => api.post(`/alerts/${id}/acknowledge`)
export const acknowledgeAll = () => api.post('/alerts/acknowledge-all')
export const getBottlenecks = (params) => api.get('/bottlenecks', { params })
export const getThresholds = () => api.get('/settings/thresholds')
export const saveThresholds = (values) => api.put('/settings/thresholds', { values })

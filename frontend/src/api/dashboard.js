import api from './client'

export const getKpis = (params) => api.get('/dashboard/kpis', { params })
export const getSummary = (params) => api.get('/dashboard/summary', { params })

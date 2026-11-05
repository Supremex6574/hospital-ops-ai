import api from './client'

export const getCompare = (params) => api.get('/resources/compare', { params })
export const getResource = (kind, params) => api.get(`/resources/${kind}`, { params })

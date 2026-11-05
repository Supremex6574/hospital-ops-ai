import api from './client'

export const runOptimization = (body) => api.post('/optimization/run', body, { timeout: 60000 })

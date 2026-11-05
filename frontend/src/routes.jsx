import { lazy } from 'react'
import {
  Activity, AlertTriangle, BarChart3, BrainCircuit, Gauge, LayoutDashboard, Lightbulb,
  LineChart, Network, SlidersHorizontal, Upload, Siren,
} from 'lucide-react'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const DataUpload = lazy(() => import('./pages/DataUpload'))
const PatientFlow = lazy(() => import('./pages/PatientFlow'))
const ResourceUtilization = lazy(() => import('./pages/ResourceUtilization'))
const Bottlenecks = lazy(() => import('./pages/Bottlenecks'))
const Forecasting = lazy(() => import('./pages/Forecasting'))
const AIInsights = lazy(() => import('./pages/AIInsights'))
const Recommendations = lazy(() => import('./pages/Recommendations'))
const WhatIf = lazy(() => import('./pages/WhatIf'))
const Optimization = lazy(() => import('./pages/Optimization'))
const Alerts = lazy(() => import('./pages/Alerts'))

/**
 * Single source of truth for navigation: the Sidebar renders it and App.jsx builds routes from it.
 * `group` controls the sidebar section; `phase` is shown on not-yet-built pages.
 */
export const NAV = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard, element: <Dashboard />, group: 'Overview', phase: 3 },
  { path: '/data', label: 'Data Upload', icon: Upload, element: <DataUpload />, group: 'Overview', phase: 2 },

  { path: '/flow', label: 'Patient Flow', icon: Activity, element: <PatientFlow />, group: 'Analytics', phase: 4 },
  { path: '/resources', label: 'Resource Utilization', icon: Gauge, element: <ResourceUtilization />, group: 'Analytics', phase: 4 },
  { path: '/bottlenecks', label: 'Bottlenecks', icon: Siren, element: <Bottlenecks />, group: 'Analytics', phase: 5 },

  { path: '/forecasting', label: 'Forecasting', icon: LineChart, element: <Forecasting />, group: 'Intelligence', phase: 6 },
  { path: '/insights', label: 'AI Insights', icon: BrainCircuit, element: <AIInsights />, group: 'Intelligence', phase: 7 },
  { path: '/recommendations', label: 'Recommendations', icon: Lightbulb, element: <Recommendations />, group: 'Intelligence', phase: 8 },

  { path: '/what-if', label: 'What-if Simulation', icon: SlidersHorizontal, element: <WhatIf />, group: 'Decision Support', phase: 9 },
  { path: '/optimization', label: 'Optimization', icon: Network, element: <Optimization />, group: 'Decision Support', phase: 10 },
  { path: '/alerts', label: 'Alerts & Monitoring', icon: AlertTriangle, element: <Alerts />, group: 'Decision Support', phase: 5 },
]

export const BRAND_ICON = BarChart3

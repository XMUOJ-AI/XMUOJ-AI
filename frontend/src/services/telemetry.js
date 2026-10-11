import { GOOGLE_ANALYTICS_ID } from '@/utils/constants'

export function installTelemetry (app, router) {
  if (process.env.AI_FEATURES_MOCK === true) return
  // Keep the existing analytics destination; do not introduce another service.
  if (GOOGLE_ANALYTICS_ID) {
    window.GoogleAnalyticsObject = 'ga'
    window.ga = window.ga || function () { (window.ga.q = window.ga.q || []).push(arguments) }
    window.ga.l = +new Date()
    const script = document.createElement('script')
    script.async = true
    script.src = 'https://www.google-analytics.com/analytics.js'
    document.head.appendChild(script)
    window.ga('create', GOOGLE_ANALYTICS_ID, 'auto')
    router.afterEach(to => window.ga('send', 'pageview', to.fullPath))
  }
  if (process.env.USE_SENTRY === '1') import('@/utils/sentry').then(module => module.installSentry(app))
}

import Raven from 'raven-js'

export function installSentry (app) {
  Raven.config('https://6234a51e61a743b089ed64c51d2f6ea9@sentry.io/258234', {
    release: process.env.VERSION,
    ignoreUrls: [/extensions\//i, /^chrome:\/\//i, /^resource:\/\//i, /\/(gtm|ga|analytics)\.js/i]
  }).install()
  const previous = app.config.errorHandler
  app.config.errorHandler = (error, component, info) => {
    Raven.captureException(error, { extra: { component: component?.$options.name, info } })
    if (previous) previous(error, component, info)
  }
  Raven.setUserContext({ version: process.env.VERSION, location: window.location })
}

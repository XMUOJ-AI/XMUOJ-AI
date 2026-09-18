const merge = require('webpack-merge')
const devEnv = require('./dev.env')

module.exports = merge(devEnv, {
  NODE_ENV: '"production"',
  LEARNING_PATH_MOCK: 'false',
  AI_FEATURES_MOCK: 'false'
})

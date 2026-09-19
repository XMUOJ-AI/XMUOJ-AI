'use strict'

const path = require('path')
const { spawnSync } = require('child_process')

module.exports = function (name) {
  const runner = path.join(path.dirname(require.resolve('vitest/package.json')), 'vitest.mjs')
  const result = spawnSync(process.execPath, [runner, 'run', 'tests/' + name + '.test.js'], { cwd: path.join(__dirname, '..'), stdio: 'inherit' })
  if (result.error) throw result.error
  process.exitCode = result.status === null ? 1 : result.status
}

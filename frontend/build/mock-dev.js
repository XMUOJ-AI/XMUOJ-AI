'use strict'

// Webpack 3 requires the legacy OpenSSL provider on modern Node versions.
const { spawn, spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const env = Object.assign({}, process.env, { MOCK: '1', NODE_ENV: 'development' })
if (Number(process.versions.node.split('.')[0]) >= 17 && !(env.NODE_OPTIONS || '').includes('--openssl-legacy-provider')) {
  env.NODE_OPTIONS = `${env.NODE_OPTIONS || ''} --openssl-legacy-provider`.trim()
}
const assets = path.resolve(__dirname, '../static/js')
if (!fs.existsSync(path.join(__dirname, 'vendor-manifest.json')) || !fs.existsSync(assets) || !fs.readdirSync(assets).some(name => /^vendor\.dll\..*\.js$/.test(name))) {
  const build = spawnSync(process.execPath, [require.resolve('webpack/bin/webpack'), '--config=build/webpack.dll.conf.js'], { env, stdio: 'inherit', cwd: path.resolve(__dirname, '..') })
  if (build.error || build.status !== 0) process.exit(1)
}
const child = spawn(process.execPath, [require.resolve('./dev-server')], { env, stdio: 'inherit' })
child.on('exit', code => process.exit(code || 0))
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal))
}

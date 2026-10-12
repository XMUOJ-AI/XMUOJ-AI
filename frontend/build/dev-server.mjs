import { createServer } from 'vite'

const mock = process.argv.includes('--mock') || process.env.MOCK === '1'
const server = await createServer({ mode: mock ? 'mock' : 'development' })
await server.listen()
if (mock) console.log('MOCK mode: local fixtures only; submissions are simulated.')
server.printUrls()
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, async () => { await server.close(); process.exit(0) })

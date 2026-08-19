import { IncomingMessage } from 'node:http'
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import { defineConfig, loadEnv, type Plugin } from 'vite'

function aiDevProxyPlugin(apiKey: string, apiUrl: string): Plugin {
  return {
    name: 'ai-dev-proxy',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (req.method !== 'POST' || !req.url) {
          next()
          return
        }

        const requestUrl = new URL(req.url, 'http://localhost')
        const isChat = requestUrl.pathname === '/api/ai/chat'
        const isStream = requestUrl.pathname === '/api/ai/chat-stream'

        if (!isChat && !isStream) {
          next()
          return
        }

        if (!apiKey) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify({ error: 'API key not configured' }))
          return
        }

        try {
          const body = await readJsonBody(req)

          if (!body?.messages || !Array.isArray(body.messages)) {
            res.statusCode = 400
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(JSON.stringify({ error: 'Invalid request: messages is required' }))
            return
          }

          const upstream = await fetch(apiUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
              model: body.model || 'deepseek-chat',
              messages: body.messages,
              max_tokens: body.max_tokens ?? 500,
              temperature: body.temperature ?? 0.7,
              stream: isStream,
            }),
          })

          if (!upstream.ok || !upstream.body) {
            const errorText = await upstream.text().catch(() => '')
            res.statusCode = upstream.status
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(
              JSON.stringify({
                error: `AI 服务错误（${upstream.status}）`,
                details: errorText,
              })
            )
            return
          }

          if (isStream) {
            res.statusCode = 200
            res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
            res.setHeader('Cache-Control', 'no-cache, no-transform')
            res.setHeader('Connection', 'keep-alive')

            const reader = upstream.body.getReader()
            const decoder = new TextDecoder('utf-8')

            while (true) {
              const { done, value } = await reader.read()
              if (done) break
              const chunk = decoder.decode(value, { stream: true })
              if (chunk) {
                res.write(chunk)
              }
            }

            res.end()
            return
          }

          const data = await upstream.json()
          res.statusCode = 200
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify(data))
        } catch (error) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(
            JSON.stringify({
              error: '服务器内部错误',
              message: error instanceof Error ? error.message : 'Unknown error',
            })
          )
        }
      })
    },
  }
}

function readJsonBody(req: IncomingMessage) {
  return new Promise<Record<string, unknown>>((resolve, reject) => {
    const chunks: Buffer[] = []

    req.on('data', (chunk) => {
      chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : Buffer.from(chunk))
    })

    req.on('end', () => {
      if (chunks.length === 0) {
        resolve({})
        return
      }

      try {
        const text = Buffer.concat(chunks).toString('utf-8')
        resolve(text ? JSON.parse(text) : {})
      } catch (error) {
        reject(error)
      }
    })

    req.on('error', reject)
  })
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiKey = env.DEEPSEEK_API_KEY || process.env.DEEPSEEK_API_KEY || ''
  const apiUrl = env.DEEPSEEK_API_URL || process.env.DEEPSEEK_API_URL || 'https://api.deepseek.com/chat/completions'

  return {
    plugins: [vue(), vueDevTools(), aiDevProxyPlugin(apiKey, apiUrl)],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
  }
})

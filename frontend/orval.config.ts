import { defineConfig } from 'orval'

export default defineConfig({
  botq: {
    input: { target: './openapi.orval.json' },
    output: {
      mode: 'single',
      target: './src/api/generated-hooks.ts',
      client: 'react-query',
      httpClient: 'fetch',
      clean: false,
      override: {
        query: { useQuery: true, useMutation: true, useInfinite: false },
        mutator: { path: './src/api/orval-mutator.ts', name: 'botqFetch' },
      },
    },
  },
})

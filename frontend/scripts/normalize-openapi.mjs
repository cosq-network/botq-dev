import { readFile, writeFile } from 'node:fs/promises'

const source = JSON.parse(await readFile(new URL('../openapi.json', import.meta.url), 'utf8'))

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize)
  if (!value || typeof value !== 'object') return value
  const result = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)]))
  if (Array.isArray(result.anyOf) && result.anyOf.length === 2 && result.anyOf.some((item) => item?.type === 'null')) {
    const nonNull = result.anyOf.find((item) => item?.type !== 'null')
    if (nonNull) return { ...nonNull, nullable: true, description: result.description }
  }
  if (result.description == null) delete result.description
  return result
}

await writeFile(new URL('../openapi.orval.json', import.meta.url), JSON.stringify(normalize(source), null, 2) + '\n')

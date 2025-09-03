// generate-validators.mjs
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import standaloneCode from 'ajv/dist/standalone/index.js'
import fs from 'fs'
import path from 'path'
import { version } from 'punycode'

/*
To run locally.
Install node and npm
  npm install ajv ajv-formats
Then run:
  node scripts/generate-validators.mjs
*/

// Schema files
const schemas = [
  {
    input: 'application/single_app/static/json/schemas/agent.schema.json',
    output: 'application/single_app/static/js/validateAgent.mjs',
  },
  {
    input: 'application/single_app/static/json/schemas/plugin.schema.json',
    output: 'application/single_app/static/js/validatePlugin.mjs',
  },
]

const ajv = new Ajv({ code: { source: true, esm: true } })
addFormats(ajv)

for (const { input, output } of schemas) {
  const schemaPath = path.resolve(input)
  const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'))
  const validate = ajv.compile(schema)
  const moduleCode = standaloneCode(ajv, validate)

  const outputPath = path.resolve(output)
  fs.writeFileSync(outputPath, moduleCode)
  console.log(`✅ Generated validator: ${output}`)
}

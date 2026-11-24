// Compare actual TypeScript AST shapes with the FastAPI-derived technical snapshot.
// The backend CI job independently checks this snapshot against app.openapi().
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from '@babel/parser';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const api = JSON.parse(fs.readFileSync(path.join(root, 'scripts/ci/api-contract.json'), 'utf8'));
const source = parse(fs.readFileSync(path.join(root, 'frontend/src/api/contracts.ts'), 'utf8'), { sourceType: 'module', plugins: ['typescript'] }).program;
const declarations = new Map();
const constants = new Map();
for (const exported of source.body) {
  const statement = exported.type === 'ExportNamedDeclaration' ? exported.declaration : exported;
  if (!statement) continue;
  if (['TSInterfaceDeclaration', 'TSTypeAliasDeclaration'].includes(statement.type)) declarations.set(statement.id.name, statement);
  if (statement.type === 'VariableDeclaration') for (const d of statement.declarations) {
    let value = d.init;
    if (value?.type === 'TSAsExpression') value = value.expression;
    if (value?.type === 'ArrayExpression') constants.set(d.id.name, value.elements.map(e => e.value));
  }
}
const union = members => {
  const values = members.flatMap(m => m.kind === 'enum' ? m.values : []);
  if (members.every(m => m.kind === 'enum')) return { kind: 'enum', values: [...new Set(values)].sort() };
  return { kind: 'union', members: members.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))) };
};
const object = properties => ({ kind: 'object', properties: Object.fromEntries(Object.entries(properties).sort(([a], [b]) => a.localeCompare(b))) });
function members(nodes) {
  return Object.fromEntries(nodes.filter(n => n.type === 'TSPropertySignature').map(n => [n.key.name || n.key.value, fromTs(n.typeAnnotation.typeAnnotation)]));
}
function declaration(name) {
  const d = declarations.get(name);
  assert.ok(d, `Unresolved TypeScript contract ${name}`);
  if (d.type === 'TSTypeAliasDeclaration') return fromTs(d.typeAnnotation);
  const properties = {};
  for (const parent of d.extends || []) Object.assign(properties, declaration(parent.expression.name).properties);
  return object({ ...properties, ...members(d.body.body) });
}
function fromTs(node) {
  const primitives = new Map([['TSStringKeyword', 'string'], ['TSNumberKeyword', 'number'], ['TSBooleanKeyword', 'boolean'], ['TSUnknownKeyword', 'any'], ['TSAnyKeyword', 'any'], ['TSNullKeyword', 'null']]);
  if (primitives.has(node.type)) return { kind: primitives.get(node.type) };
  if (node.type === 'TSArrayType') return { kind: 'array', items: fromTs(node.elementType) };
  if (node.type === 'TSUnionType') return union(node.types.map(fromTs));
  if (node.type === 'TSLiteralType') {
    if (node.literal.type === 'NullLiteral') return { kind: 'null' };
    return { kind: 'enum', values: [node.literal.value] };
  }
  if (node.type === 'TSTypeLiteral') return object(members(node.members));
  if (node.type === 'TSIndexedAccessType' && node.objectType.type === 'TSTypeQuery') {
    const values = constants.get(node.objectType.exprName.name);
    assert.ok(values, 'Unknown indexed constant contract');
    return { kind: 'enum', values: [...values].sort() };
  }
  if (node.type === 'TSTypeReference') {
    const name = node.typeName.name;
    if (name === 'Record') return { kind: 'record', values: fromTs((node.typeArguments || node.typeParameters).params[1]) };
    return declaration(name);
  }
  throw new Error(`Unsupported contract AST: ${node.type}`);
}
function fromApi(schema) {
  if (schema.$ref) return fromApi(api.schemas[schema.$ref.split('/').at(-1)]);
  if (schema.anyOf) return union(schema.anyOf.map(fromApi));
  if ('const' in schema) return { kind: 'enum', values: [schema.const] };
  if (schema.enum) return { kind: 'enum', values: [...schema.enum].sort() };
  if (schema.type === 'array') return { kind: 'array', items: fromApi(schema.items) };
  if (schema.type === 'object') {
    if (schema.properties) return object(Object.fromEntries(Object.entries(schema.properties).map(([k, v]) => [k, fromApi(v)])));
    return { kind: 'record', values: schema.additionalProperties === true ? { kind: 'any' } : fromApi(schema.additionalProperties || {}) };
  }
  return { kind: schema.type === 'integer' ? 'number' : schema.type || 'any' };
}
const pairs = { Health: 'HealthResponse', Metadata: 'MetadataResponse', ModelMetadata: 'ModelMetadata', Prediction: 'Prediction', Visualization: 'Visualization', VisualizedPrediction: 'VisualizedPrediction' };
for (const [frontend, backend] of Object.entries(pairs)) assert.deepEqual(declaration(frontend), fromApi(api.schemas[backend]), `${frontend} differs from actual FastAPI shape`);
for (const route of ['/predict', '/predict/visualize']) {
  const form = api.paths[route].post.requestBody.content['multipart/form-data'].schema;
  const schema = api.schemas[form.$ref.split('/').at(-1)];
  assert.deepEqual(fromApi(schema.properties.engine), declaration('Engine'));
  assert.deepEqual(fromApi(schema.properties.model), declaration('ModelName'));
  assert.deepEqual(fromApi(schema.properties.category), declaration('Category'));
  assert.equal(schema.properties.file.type, 'string');
  assert.equal(schema.properties.file.contentMediaType, 'application/octet-stream');
}
console.log('Six response shapes and both multipart engine/model/category contracts match the FastAPI snapshot. Optional defaults are allowed for frontend backward compatibility; tsc checks TypeScript usage. No live API inference claimed.');

import babelParser from '@babel/eslint-parser';
import globals from 'globals';

export default [
  { ignores: ['dist/**', 'node_modules/**', 'reports/**', 'src/components/reactbits/**'] },
  {
    files: ['src/**/*.{ts,tsx}', '*.{ts,mjs}', 'scripts/**/*.mjs'],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: { babelrc: false, configFile: false, parserOpts: { plugins: ['typescript', 'jsx'] } },
      },
      globals: { ...globals.browser, ...globals.node },
    },
    // Syntax/control-flow correctness. TypeScript 7 strict mode checks names/types.
    // No style rules, unused-import cleanup, vendor rewriting or autofix.
    rules: {
      'constructor-super': 'error',
      'no-dupe-args': 'error',
      'no-duplicate-case': 'error',
      'no-unsafe-finally': 'error',
      'no-unreachable': 'error',
      'no-this-before-super': 'error',
      'no-sparse-arrays': 'error',
      'valid-typeof': 'error',
      'use-isnan': 'error',
    },
  },
];

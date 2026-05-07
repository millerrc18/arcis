import globals from 'globals'
import noBareQueryFn from './no-bare-queryfn-with-args.js'

const localPlugin = {
  rules: {
    'no-bare-queryfn-with-args': noBareQueryFn,
  },
}

export default [
  {
    files: ['src/**/*.{js,jsx}'],
    plugins: {
      local: localPlugin,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'local/no-bare-queryfn-with-args': 'error',
    },
  },
]

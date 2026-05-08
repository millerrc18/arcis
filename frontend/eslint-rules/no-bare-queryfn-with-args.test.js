/**
 * Tests for no-bare-queryfn-with-args ESLint rule.
 *
 * Run: node frontend/eslint-rules/no-bare-queryfn-with-args.test.js
 *
 * Tests:
 * 1. Rule fires on Identifier  — queryFn: foo
 * 2. Rule does NOT fire on ArrowFunctionExpression — queryFn: () => foo()
 * 3. Rule does NOT fire on FunctionExpression     — queryFn: function() {}
 * 4. Rule fires on CallExpression               — queryFn: foo.bind(this)
 */

import { RuleTester } from 'eslint'
import rule from './no-bare-queryfn-with-args.js'

const tester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2020,
    sourceType: 'module',
    parserOptions: {
      ecmaVersion: 'latest',
      ecmaFeatures: { jsx: true },
      sourceType: 'module',
    },
  },
})

tester.run('no-bare-queryfn-with-args', rule, {
  valid: [
    {
      name: 'arrow function is allowed',
      code: `
        import { useQuery } from '@tanstack/react-query';
        function C() {
          useQuery({ queryKey: ['k'], queryFn: () => foo() });
        }
      `,
    },
    {
      name: 'function expression is allowed',
      code: `
        import { useQuery } from '@tanstack/react-query';
        function C() {
          useQuery({ queryKey: ['k'], queryFn: function() { return fetch('/x'); } });
        }
      `,
    },
  ],
  invalid: [
    {
      name: 'bare Identifier fires rule',
      code: `
        import { useQuery } from '@tanstack/react-query';
        function C() {
          useQuery({ queryKey: ['k'], queryFn: foo });
        }
      `,
      errors: [{ messageId: 'bareQueryFn' }],
    },
    {
      name: 'CallExpression (foo.bind) fires rule',
      code: `
        import { useQuery } from '@tanstack/react-query';
        function C() {
          useQuery({ queryKey: ['k'], queryFn: foo.bind(this) });
        }
      `,
      errors: [{ messageId: 'bareQueryFn' }],
    },
  ],
})

console.log('All no-bare-queryfn-with-args tests passed.')
